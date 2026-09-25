"""Real observation suspension and denied reconciliation on one persistent workload."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid

from check_ambiguity import change_routing
from check_campaign import await_file, finalize_gate, wait_until
from check_recurrence import stop_and_reap

from autonomy_lab.campaign import active, operation_rows, read, spawn_worker, wait_ready
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import client_path_failed, save
from autonomy_lab.janitor import process_identity
from autonomy_lab.kubernetes import ROOT, Kubernetes
from autonomy_lab.telemetry import declaration, evaluate


def signal_worker(workspace, value):
    if value not in (signal.SIGSTOP, signal.SIGCONT):
        raise ValueError('Only suspension and continuation are supported')
    lease = read(workspace / 'worker-lease.json')
    pid = lease['pid']
    if (type(pid) is not int or pid <= 1 or not lease.get('identity')
            or process_identity(pid) != lease['identity'] or os.getpgid(pid) != pid):
        raise RuntimeError('Worker identity changed; signal refused')
    at = time.time()
    os.killpg(pid, value)
    deadline = time.monotonic() + 3
    while True:
        state = subprocess.check_output(['ps', '-p', str(pid), '-o', 'stat='], text=True, timeout=3).strip()
        if state and state.startswith('T') == (value == signal.SIGSTOP):
            return {'at': at, 'identity': lease['identity'], 'state': state}
        if time.monotonic() >= deadline:
            raise TimeoutError('Worker did not reach declared signal state')
        time.sleep(0.05)


def revoke_read(kube, gate, record):
    role = json.loads(kube.call('get', 'role', 'broker', '-o', 'json'))
    rules = role['rules']
    if rules != [{'apiGroups': [''], 'resources': ['services'], 'resourceNames': ['inventory'], 'verbs': ['get', 'patch']}]:
        raise AssertionError('Unexpected broker Role before revocation')
    patch = [{'op': 'test', 'path': '/metadata/uid', 'value': role['metadata']['uid']},
             {'op': 'test', 'path': '/metadata/resourceVersion', 'value': role['metadata']['resourceVersion']},
             {'op': 'test', 'path': '/rules', 'value': rules},
             {'op': 'replace', 'path': '/rules/0/verbs', 'value': ['patch']}]
    action = {'requested_at': time.time(), 'patch': patch, 'before_rules': rules}
    record['revocation'] = action
    save(gate / 'record.json', record)
    result = json.loads(kube.call('patch', 'role', 'broker', '--type=json', '-p', json.dumps(patch), '-o', 'json'))
    action.update(finished_at=time.time(), after_rules=result['rules'], resource_version=result['metadata']['resourceVersion'])
    save(gate / 'record.json', record)


def run():
    gate = ROOT / 'artifacts' / ('telemetry-gate-' + uuid.uuid4().hex[:8])
    gate.mkdir(parents=True, mode=0o700)
    directory, spec = gate / 'campaign', declaration()
    save(gate / 'declaration.json', spec)
    result, record, children = {'status': 'failed', 'started_at': time.time()}, {}, []
    with (gate / 'owner.log').open('ab') as log:
        owner = subprocess.Popen([sys.executable, '-m', 'autonomy_lab.campaign', 'own',
            str(ROOT / 'scenarios/campaign-telemetry.json'), str(directory)], stdout=log, stderr=log,
            start_new_session=True, env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src')})
    try:
        window = await_file(directory / 'window.json', time.monotonic() + 900)
        observer = next((directory / 'workers').glob('observer-*'))
        initial = next((directory / 'workers').glob('operator-*'))
        record.update(run_id=read(directory / 'owner.json')['run_id'], observer=observer.name, initial_worker=initial.name)
        kube = Kubernetes(directory / 'kubeconfig', read(directory / 'environment.json')['cluster'])
        wait_until(window['start'] + spec['pause_offset'])
        pause = signal_worker(observer, signal.SIGSTOP)
        record.update(paused_at=pause['at'], pause_state=pause['state'], observer_identity_before=pause['identity'],
                      samples_before_pause={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (directory / 'samples').glob('*.json')})
        save(gate / 'record.json', record)
        wait_until(window['start'] + spec['resume_offset'])
        resumed = signal_worker(observer, signal.SIGCONT)
        record.update(resumed_at=resumed['at'], observer_identity_after=resumed['identity'])
        save(gate / 'record.json', record)
        wait_until(window['start'] + spec['stop_offset'])
        record['initial_stop_requested_at'] = time.time()
        save(gate / 'record.json', record)
        record['initial_stopped_at'] = stop_and_reap(initial, children)
        wait_until(window['start'] + spec['inject_offset'])
        change_routing(kube, directory, gate, record, 'fault', 8080, 9999)
        wait_until(window['start'] + spec['repair_start_offset'])
        observed = [read(p) for p in (directory / 'samples').glob('*.json')]
        if not any(s['started_at'] >= record['fault']['finished_at'] and client_path_failed(s.get('verification', {})) for s in observed):
            raise AssertionError('Independent observer did not resume and establish client failure')
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
            raise AssertionError('Missing real post-response/pre-acknowledgement boundary')
        record['kill_requested_at'] = time.time()
        save(gate / 'record.json', record)
        record['stopped_at'] = stop_and_reap(repair, children)
        save(gate / 'record.json', record)
        wait_until(record['stopped_at'] + spec['revoke_after_stop_seconds'])
        active(directory)
        revoke_read(kube, gate, record)
        wait_until(record['stopped_at'] + spec['restart_after_stop_seconds'])
        record['restart_requested_at'] = time.time()
        resumed, process = spawn_worker(directory, 'operator')
        children.append((resumed, process))
        record['resumed_worker'] = resumed.name
        save(gate / 'record.json', record)
        record['resumed_ready_at'] = wait_ready(resumed, process, timeout=10)['at']
        save(gate / 'record.json', record)
        if process.wait(timeout=max(1, record['restart_requested_at'] + spec['escalation_deadline_seconds'] - time.time())) != 0:
            raise AssertionError('Missing clean escalation after unavailable reconciliation')
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
            raise AssertionError('Telemetry contract not satisfied: ' + ', '.join(k for k, v in assessment['checks'].items() if not v))
        result.update(status='passed', export_identical=True,
            scorecard_sha256=hashlib.sha256((gate / 'scorecard-a.json').read_bytes()).hexdigest(),
            evaluation_sha256=hashlib.sha256((gate / 'evaluation-a.json').read_bytes()).hexdigest())
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        try:
            if (directory / 'window.json').exists():
                save(gate / 'scorecard-final.json', scorecard(directory))
                save(gate / 'evaluation-final.json', evaluate(gate))
        except Exception as error:
            result['export_error_type'] = type(error).__name__
        finalize_gate(owner, children, directory, gate, result)
    return gate


if __name__ == '__main__':
    run()
