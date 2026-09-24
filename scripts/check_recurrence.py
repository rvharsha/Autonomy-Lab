"""Freeze and execute three recurring faults on one real persistent workload."""

import hashlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from check_campaign import await_file, finalize_gate, wait_until

from autonomy_lab.campaign import active, read, spawn_worker, stop_worker, wait_ready
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import client_path_failed, save
from autonomy_lab.janitor import process_identity
from autonomy_lab.kubernetes import ROOT, Kubernetes
from autonomy_lab.recurrence import evaluate


def declaration():
    return {
        'incidents': [{'id': f'routing-{i + 1}', 'stop_offset': 20 + 80 * i,
                      'inject_offset': 25 + 80 * i, 'restart_offset': 45 + 80 * i,
                      'expected': 'repaired' if i < 2 else 'budget_escalation'} for i in range(3)],
        'response_deadline_seconds': 70, 'schedule_lateness_seconds': 3,
        'contract_sha256': hashlib.sha256((ROOT / 'scenarios/campaign-recurrence.json').read_bytes()).hexdigest(),
        'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scorer_sha256': hashlib.sha256((ROOT / 'src/autonomy_lab/recurrence.py').read_bytes()).hexdigest(),
    }


def stop_and_reap(workspace, children):
    stop_worker(workspace)
    for path, process in children:
        if path == workspace:
            process.wait(timeout=10)
    lease = read(workspace / 'worker-lease.json')
    deadline = time.monotonic() + 10
    while process_identity(lease['pid']) == lease['identity']:
        if time.monotonic() >= deadline:
            raise TimeoutError('Operator did not terminate')
        time.sleep(0.1)
    return time.time()


def run():
    gate = ROOT / 'artifacts' / ('recurrence-gate-' + uuid.uuid4().hex[:8])
    gate.mkdir(parents=True, mode=0o700)
    (gate / 'incidents').mkdir()
    directory = gate / 'campaign'
    declared = declaration()
    save(gate / 'declaration.json', declared)
    result = {'status': 'failed', 'started_at': time.time(), 'declaration': declared}
    children = []
    with (gate / 'owner.log').open('ab') as log:
        owner = subprocess.Popen([sys.executable, '-m', 'autonomy_lab.campaign', 'own',
                                  str(ROOT / 'scenarios/campaign-recurrence.json'), str(directory)],
                                 stdout=log, stderr=log, start_new_session=True,
                                 env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src')})
    try:
        window = await_file(directory / 'window.json', time.monotonic() + 900)
        current = next((directory / 'workers').glob('operator-*'))
        kube = Kubernetes(directory / 'kubeconfig', read(directory / 'environment.json')['cluster'])
        for spec in declared['incidents']:
            path = gate / 'incidents' / (spec['id'] + '.json')
            record = {'id': spec['id'], 'previous_worker': current.name}
            wait_until(window['start'] + spec['stop_offset'])
            record['stop_requested_at'] = time.time()
            save(path, record)
            record['stopped_at'] = stop_and_reap(current, children)
            wait_until(window['start'] + spec['inject_offset'])
            active(directory)
            service = kube.get_service(kube.namespace, 'inventory')
            if service['spec']['ports'][0]['targetPort'] != 8080:
                raise AssertionError('Prior incident did not leave a healthy routing configuration')
            record.update(requested_at=time.time(), service_uid=service['metadata']['uid'])
            # Store exact intended patch before dispatch, including UID/version preconditions.
            record['patch'] = [
                {'op': 'test', 'path': '/metadata/uid', 'value': service['metadata']['uid']},
                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': service['metadata']['resourceVersion']},
                {'op': 'test', 'path': '/spec/ports/0/name', 'value': 'http'},
                {'op': 'test', 'path': '/spec/ports/0/targetPort', 'value': 8080},
                {'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': 9999},
            ]
            save(path, record)
            kube.audit_operation_id = 'fault-' + spec['id']
            kube.patch_service(kube.namespace, 'inventory', record['patch'])
            record['injected_at'] = time.time()
            save(path, record)
            wait_until(window['start'] + spec['restart_offset'])
            # The independent observer must have seen real client failure before release.
            observed = [read(p) for p in (directory / 'samples').glob('*.json')]
            if not any(s['started_at'] >= record['injected_at'] and client_path_failed(s.get('verification', {})) for s in observed):
                raise AssertionError('No independently observed client fault before scheduled restart')
            record['restart_requested_at'] = time.time()
            current, process = spawn_worker(directory, 'operator')
            children.append((current, process))
            record['worker'] = current.name
            save(path, record)
            ready = wait_ready(current, process, timeout=20)
            record['ready_at'] = ready['at']
            save(path, record)
        owner.wait(timeout=max(1, window['end'] - time.time()) + 180)
        if owner.returncode != 0:
            raise RuntimeError('Campaign owner failed')
        for suffix in ('a', 'b'):
            save(gate / f'scorecard-{suffix}.json', scorecard(directory))
            save(gate / f'evaluation-{suffix}.json', evaluate(gate))
        for name in ('scorecard', 'evaluation'):
            if (gate / f'{name}-a.json').read_bytes() != (gate / f'{name}-b.json').read_bytes():
                raise AssertionError('Export is not reproducible')
        assessment = read(gate / 'evaluation-a.json')
        if assessment['status'] != 'passed':
            raise AssertionError('Recurrence contract not satisfied: ' + ', '.join(k for k, v in assessment['checks'].items() if not v))
        result.update(status='passed', export_identical=True,
                      scorecard_sha256=hashlib.sha256((gate / 'scorecard-a.json').read_bytes()).hexdigest(),
                      evaluation_sha256=hashlib.sha256((gate / 'evaluation-a.json').read_bytes()).hexdigest())
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        try:
            if (directory / 'window.json').exists():
                # Partial execution still exports the entire frozen calendar with unknowns.
                save(gate / 'scorecard-final.json', scorecard(directory))
        except Exception as error:
            result['export_error_type'] = type(error).__name__
        finalize_gate(owner, children, directory, gate, result)
    return gate


if __name__ == '__main__':
    run()
