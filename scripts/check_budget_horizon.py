"""Compare three authored policies once each on the same frozen incident rule."""

import os
import random
import subprocess
import sys
import time
import uuid

from check_ambiguity import change_routing
from check_campaign import await_file, finalize_gate, wait_until
from check_recurrence import stop_and_reap
from check_refresh import await_new_barrier

from autonomy_lab.budget_horizon import ARMS, declaration, evaluate
from autonomy_lab.campaign import active, read, spawn_worker, wait_ready
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.conflict import annotation_patch
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT, Kubernetes
from autonomy_lab.procedures import require
from autonomy_lab.withdrawal import capture_audit


def run_case(gate, spec):
    require(spec == declaration(spec['arm']), 'Frozen comparison changed before provisioning')
    directory = gate / 'campaign'
    save(gate / 'declaration.json', spec)
    manifest = gate / 'manifest.json'
    save(manifest, spec['contract'])
    result = {'status': 'failed', 'started_at': time.time()}
    record, children = {'attempts': []}, []
    with (gate / 'owner.log').open('ab') as log:
        owner = subprocess.Popen([sys.executable, '-m', 'autonomy_lab.campaign', 'own', str(manifest), str(directory)],
                                 stdout=log, stderr=log, start_new_session=True,
                                 env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src')})
    try:
        window = await_file(directory / 'window.json', time.monotonic() + 900)
        start = window['start']
        initial = next((directory / 'workers').glob('operator-*'))
        record['initial_worker'] = initial.name
        kube = Kubernetes(directory / 'kubeconfig', read(directory / 'environment.json')['cluster'])
        wait_until(start + spec['stop_offset'])
        record['stop_requested_at'] = time.time()
        save(gate / 'record.json', record)
        record['stopped_at'] = stop_and_reap(initial, children)
        wait_until(start + spec['fault_offset'])
        change_routing(kube, directory, gate, record, 'fault', 8080, 9999)
        for phase in ('first', 'second'):
            if phase == 'second':
                wait_until(start + spec['external_restore_offset'])
                change_routing(kube, directory, gate, record, 'external_restore', 9999, 8080)
                wait_until(start + spec['second_fault_offset'])
                change_routing(kube, directory, gate, record, 'second_fault', 8080, 9999)
            wait_until(start + spec[phase + '_start_offset'])
            record[phase + '_requested_at'] = time.time()
            worker, process = spawn_worker(directory, 'operator')
            children.append((worker, process))
            record[phase + '_worker'] = worker.name
            save(gate / 'record.json', record)
            wait_ready(worker, process, timeout=20)
            seen = set()
            deadline = record[phase + '_requested_at'] + spec['response_deadline_seconds']
            # Do not assume a policy repairs or refreshes. The same controller
            # rule conflicts every actual first-incident attempt, and none later.
            while process.poll() is None and time.time() < deadline:
                paths = [p for p in (worker / 'preflight').glob('*/preflight-barrier.json')
                         if p.parent.name not in seen]
                if not paths:
                    if any(worker.glob('episode-*/outcome.json')):
                        break
                    time.sleep(.05)
                    continue
                path, barrier = await_new_barrier(worker, seen, deadline)
                seen.add(barrier['operation_id'])
                active(directory)
                attempt = {'phase': phase, 'operation_id': barrier['operation_id'], 'barrier': barrier,
                           'before': kube.get_service(kube.namespace, 'inventory')}
                record['attempts'].append(attempt)
                save(gate / 'record.json', record)
                if phase == 'first':
                    change = {'requested_at': time.time(),
                              'patch': annotation_patch(attempt['before'], barrier['operation_id'])}
                    attempt['change'] = change
                    save(gate / 'record.json', record)
                    kube.audit_operation_id = 'horizon-conflict-' + barrier['operation_id']
                    attempt['changed_service'] = kube.patch_service(kube.namespace, 'inventory', change['patch'])
                    change['finished_at'] = time.time()
                attempt['release_requested_at'] = time.time()
                save(gate / 'record.json', record)
                save(path.parent / 'preflight-release.json', {'operation_id': barrier['operation_id']})
            require(any(worker.glob('episode-*/outcome.json')), 'Operator did not finish its first episode')
            if phase == 'first':
                require(process.wait(timeout=max(1, deadline - time.time())) == 0, 'First operator failed')
        owner.wait(timeout=max(1, window['end'] - time.time()) + 180)
        require(owner.returncode == 0, 'Campaign owner failed')
        capture_audit(gate)
        for label in ('a', 'b'):
            save(gate / f'scorecard-{label}.json', scorecard(directory))
            save(gate / f'evaluation-{label}.json', evaluate(gate))
        for name in ('scorecard', 'evaluation'):
            require((gate / f'{name}-a.json').read_bytes() == (gate / f'{name}-b.json').read_bytes(),
                    'Repeated offline export differs')
        result.update(status='passed', evaluation=read(gate / 'evaluation-a.json'))
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        try:
            if (directory / 'window.json').exists():
                save(gate / 'scorecard-final.json', scorecard(directory))
        except Exception as error:
            result['export_error_type'] = type(error).__name__
        try:
            finalize_gate(owner, children, directory, gate, result)
        finally:
            try:
                if (directory / 'environment.json').exists():
                    capture_audit(gate)
            except Exception as error:
                result.update(status='failed', audit_capture_error_type=type(error).__name__)
            save(gate / 'result.json', result)


def run():
    gate = ROOT / 'artifacts' / ('budget-horizon-' + uuid.uuid4().hex[:8])
    gate.mkdir(parents=True, mode=0o700)
    order = list(ARMS)
    random.Random(2026092502).shuffle(order)
    specs = {arm: declaration(arm) for arm in order}
    save(gate / 'declaration.json', {'order_seed': 2026092502, 'order': order, 'cases': specs,
                                    'attempts_per_policy': 1})
    result = {'status': 'failed', 'cases': {}, 'unrun': list(order)}
    save(gate / 'result.json', result)
    for arm in order:
        case = gate / arm
        case.mkdir()
        result['unrun'].remove(arm)
        result['cases'][arm] = {'status': 'attempting'}
        save(gate / 'result.json', result)
        try:
            run_case(case, specs[arm])
            result['cases'][arm] = read(case / 'result.json')
        except Exception as error:
            result['cases'][arm] = {**(read(case / 'result.json') if (case / 'result.json').exists() else {}),
                                    'status': 'failed', 'error_type': type(error).__name__}
        save(gate / 'result.json', result)
    result['status'] = 'passed' if all(c['status'] == 'passed' for c in result['cases'].values()) else 'failed'
    save(gate / 'result.json', result)
    require(result['status'] == 'passed', 'Comparison incomplete; all attempts retained')
    return gate


if __name__ == '__main__':
    print(run())
