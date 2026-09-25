"""Kill an operator after a real effect, then reconcile with and without external change."""

import hashlib
import os
import subprocess
import sys
import time
import uuid

from check_campaign import await_file, finalize_gate, wait_until
from check_recurrence import stop_and_reap

from autonomy_lab.ambiguity import CASES, declaration, evaluate
from autonomy_lab.campaign import active, operation_rows, read, spawn_worker, wait_ready
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import client_path_failed, save
from autonomy_lab.kubernetes import ROOT, Kubernetes


def change_routing(kube, directory, gate, record, name, expected, target):
    active(directory)
    service = kube.get_service(kube.namespace, 'inventory')
    if service['spec']['ports'][0]['name'] != 'http' or service['spec']['ports'][0]['targetPort'] != expected:
        raise AssertionError('Unexpected routing state before controlled change')
    action = {'requested_at': time.time(), 'old_target_port': expected, 'new_target_port': target,
              'patch': [
                  {'op': 'test', 'path': '/metadata/uid', 'value': service['metadata']['uid']},
                  {'op': 'test', 'path': '/metadata/resourceVersion', 'value': service['metadata']['resourceVersion']},
                  {'op': 'test', 'path': '/spec/ports/0/name', 'value': 'http'},
                  {'op': 'test', 'path': '/spec/ports/0/targetPort', 'value': expected},
                  {'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': target},
              ]}
    record[name] = action
    save(gate / 'record.json', record)
    kube.audit_operation_id = 'ambiguity-' + name
    response = kube.patch_service(kube.namespace, 'inventory', action['patch'])
    action.update(finished_at=time.time(), resource_version=response['metadata']['resourceVersion'])
    save(gate / 'record.json', record)


def run_case(gate, spec, *, manifest=None, calibration=None, at_barrier=None, evaluator=evaluate):
    directory = gate / 'campaign'
    result = {'status': 'failed', 'started_at': time.time(), 'declaration': spec}
    children = []
    record = {}
    with (gate / 'owner.log').open('ab') as log:
        owner = subprocess.Popen([sys.executable, '-m', 'autonomy_lab.campaign', 'own',
                                  str(manifest or ROOT / 'scenarios/campaign-ambiguity.json'), str(directory),
                                  *(['--calibration', str(calibration)] if calibration is not None else [])],
                                 stdout=log, stderr=log, start_new_session=True,
                                 env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src')})
    try:
        window = await_file(directory / 'window.json', time.monotonic() + 900)
        record['run_id'] = read(directory / 'owner.json')['run_id']
        initial = next((directory / 'workers').glob('operator-*'))
        record['initial_worker'] = initial.name
        kube = Kubernetes(directory / 'kubeconfig', read(directory / 'environment.json')['cluster'])
        wait_until(window['start'] + spec['stop_offset'])
        record['initial_stop_requested_at'] = time.time()
        save(gate / 'record.json', record)
        record['initial_stopped_at'] = stop_and_reap(initial, children)
        wait_until(window['start'] + spec['inject_offset'])
        change_routing(kube, directory, gate, record, 'fault', 8080, 9999)
        wait_until(window['start'] + spec['repair_start_offset'])
        observed = [read(p) for p in (directory / 'samples').glob('*.json')]
        if not any(s['started_at'] >= record['fault']['finished_at'] and client_path_failed(s.get('verification', {})) for s in observed):
            raise AssertionError('Independent observer did not establish the injected fault')
        record['repair_requested_at'] = time.time()
        repair, process = spawn_worker(directory, 'operator')
        children.append((repair, process))
        record['repair_worker'] = repair.name
        save(gate / 'record.json', record)
        record['repair_ready_at'] = wait_ready(repair, process, timeout=20)['at']
        barrier = await_file(repair / 'dispatch-barrier.json', time.monotonic() + max(0, window['start'] + spec['barrier_deadline_offset'] - time.time()))
        before = operation_rows(directory)
        save(gate / 'before-kill.json', before)
        if len(before) != 1 or before[0]['status'] != 'dispatching' or before[0]['result'] is not None or before[0]['operation_id'] != barrier['operation_id']:
            raise AssertionError('Real effect did not stop before durable acknowledgement')
        if at_barrier is not None:
            at_barrier(gate, record)
        record['kill_requested_at'] = time.time()
        save(gate / 'record.json', record)
        record['stopped_at'] = stop_and_reap(repair, children)
        save(gate / 'record.json', record)
        if spec['case'] == 'external_change':
            wait_until(record['stopped_at'] + spec['external_change_after_stop_seconds'])
            change_routing(kube, directory, gate, record, 'external', 8080, 9998)
        wait_until(record['stopped_at'] + spec['restart_after_stop_seconds'])
        record['restart_requested_at'] = time.time()
        resumed, process = spawn_worker(directory, 'operator')
        children.append((resumed, process))
        record['resumed_worker'] = resumed.name
        save(gate / 'record.json', record)
        record['resumed_ready_at'] = wait_ready(resumed, process, timeout=10)['at']
        save(gate / 'record.json', record)
        if process.wait(timeout=max(1, record['restart_requested_at'] + spec['escalation_deadline_seconds'] - time.time())) != 0:
            raise AssertionError('Restarted operator did not exit cleanly after escalation')
        owner.wait(timeout=max(1, window['end'] - time.time()) + 180)
        if owner.returncode != 0:
            raise RuntimeError('Campaign owner failed')
        for suffix in ('a', 'b'):
            save(gate / f'scorecard-{suffix}.json', scorecard(directory))
            save(gate / f'evaluation-{suffix}.json', evaluator(gate))
        for name in ('scorecard', 'evaluation'):
            if (gate / f'{name}-a.json').read_bytes() != (gate / f'{name}-b.json').read_bytes():
                raise AssertionError('Export is not reproducible')
        assessment = read(gate / 'evaluation-a.json')
        if assessment['status'] != 'passed':
            raise AssertionError('Ambiguity contract not satisfied: ' + ', '.join(k for k, v in assessment['checks'].items() if not v))
        result.update(status='passed', export_identical=True,
                      scorecard_sha256=hashlib.sha256((gate / 'scorecard-a.json').read_bytes()).hexdigest(),
                      evaluation_sha256=hashlib.sha256((gate / 'evaluation-a.json').read_bytes()).hexdigest())
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        try:
            finalize_gate(owner, children, directory, gate, result)
        finally:
            try:
                if (directory / 'window.json').exists():
                    save(gate / 'scorecard-final.json', scorecard(directory))
                    save(gate / 'evaluation-final.json', evaluator(gate))
            except Exception as error:
                result['export_error_type'] = type(error).__name__
                if result['status'] == 'passed':
                    result['status'] = 'failed'
                    raise
            finally:
                save(gate / 'result.json', result)


def run():
    gate = ROOT / 'artifacts' / ('ambiguity-gate-' + uuid.uuid4().hex[:8])
    gate.mkdir(parents=True, mode=0o700)
    specs = [declaration(case) for case in CASES]
    save(gate / 'declaration.json', {'cases': specs})
    ledger = {'status': 'running', 'started_at': time.time(), 'cases': {case: {'status': 'unrun'} for case in CASES}}
    save(gate / 'result.json', ledger)
    try:
        for spec in specs:
            case = gate / spec['case']
            case.mkdir()
            save(case / 'declaration.json', spec)
            ledger['cases'][spec['case']] = {'status': 'running'}
            save(gate / 'result.json', ledger)
            try:
                run_case(case, spec)
            except BaseException as error:
                ledger['cases'][spec['case']] = {'status': 'failed', 'error_type': type(error).__name__}
                if not isinstance(error, Exception):
                    raise
                # Keep the second independently declared case; never retry a failed identity.
            else:
                ledger['cases'][spec['case']] = {'status': 'passed'}
            save(gate / 'result.json', ledger)
        ledger['status'] = 'passed' if all(r['status'] == 'passed' for r in ledger['cases'].values()) else 'failed'
        if ledger['status'] != 'passed':
            raise AssertionError('One or more declared ambiguity campaigns failed')
    except BaseException as error:
        ledger.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        ledger['finished_at'] = time.time()
        save(gate / 'result.json', ledger)
        print(gate, flush=True)
    return gate


if __name__ == '__main__':
    run()
