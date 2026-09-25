"""Run each declared authored refresh case once against real disposable Kubernetes."""

import argparse
import os
import subprocess
import sys
import time
import uuid

from check_ambiguity import change_routing
from check_ambiguity import run_case as run_ambiguity
from check_campaign import await_file, finalize_gate, wait_until
from check_recurrence import stop_and_reap

from autonomy_lab.campaign import active, operation_rows, read, spawn_worker, wait_ready
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.conflict import annotation_patch
from autonomy_lab.harness import client_path_failed, save
from autonomy_lab.kubernetes import ROOT, Kubernetes
from autonomy_lab.procedures import require
from autonomy_lab.refresh import CASES, declaration, evaluate
from autonomy_lab.withdrawal import capture_audit


def await_new_barrier(repair, seen, deadline):
    while time.time() < deadline:
        paths = [p for p in (repair / 'preflight').glob('*/preflight-barrier.json') if p.parent.name not in seen]
        require(len(paths) <= 1, 'Concurrent prepared operations')
        if paths:
            return paths[0], read(paths[0])
        if (repair / 'finished.json').exists() or (repair / 'failed.json').exists():
            raise AssertionError('Operator stopped before expected dispatch')
        time.sleep(.05)
    raise TimeoutError('Prepared operation barrier not reached')


def run_case(gate, spec, *, calibration=None, at_preflight=None, evaluator=None):
    evaluator = evaluator or evaluate
    directory = gate / 'campaign'
    result = {'status': 'failed', 'started_at': time.time(), 'declaration': spec}
    children, record, owner = [], {'attempts': []}, None
    save(gate / 'result.json', result)
    try:
        with (gate / 'owner.log').open('ab') as log:
            owner = subprocess.Popen([sys.executable, '-m', 'autonomy_lab.campaign', 'own',
                str(ROOT / spec['manifest']), str(directory),
                *(['--calibration', str(calibration)] if calibration is not None else [])],
                stdout=log, stderr=log, start_new_session=True,
                env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src')})
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
        require(any(s['started_at'] >= record['fault']['finished_at'] and client_path_failed(s.get('verification', {}))
                    for s in observed), 'Independent observer did not establish routing failure')
        record['repair_requested_at'] = time.time()
        repair, process = spawn_worker(directory, 'operator')
        children.append((repair, process))
        record['repair_worker'] = repair.name
        save(gate / 'record.json', record)
        wait_ready(repair, process, timeout=20)
        seen = set()
        cancelled = False
        for index in range(2):
            deadline = (window['start'] + spec['barrier_deadline_offset'] if index == 0 else
                        record['attempts'][0]['release_requested_at'] + spec['second_barrier_deadline_seconds'])
            path, barrier = await_new_barrier(repair, seen, deadline)
            seen.add(barrier['operation_id'])
            if index == 0:
                episodes = list(repair.glob('episode-*'))
                require(len(episodes) == 1, 'Expected one episode at first prepared dispatch')
                repair_episode = episodes[0]
            active(directory)
            attempt = {'barrier': barrier, 'operations': operation_rows(directory),
                       'before': kube.get_service(kube.namespace, 'inventory'), 'read_at': time.time()}
            record['attempts'].append(attempt)
            save(gate / 'record.json', record)
            cancelled = bool(at_preflight and at_preflight(gate, record, index))
            if not cancelled and (index == 0 or spec['refresh_case'] == 'continuing'):
                change = {'requested_at': time.time(), 'patch': annotation_patch(attempt['before'], barrier['operation_id'])}
                attempt['change'] = change
                save(gate / 'record.json', record)
                kube.audit_operation_id = 'refresh-version-bump-' + str(index + 1)
                attempt['changed_service'] = kube.patch_service(kube.namespace, 'inventory', change['patch'])
                change['finished_at'] = time.time()
                save(gate / 'record.json', record)
                require(attempt['changed_service']['spec'] == attempt['before']['spec']
                        and attempt['changed_service']['metadata']['uid'] == attempt['before']['metadata']['uid']
                        and attempt['changed_service']['metadata']['resourceVersion'] != attempt['before']['metadata']['resourceVersion'],
                        'Controller change did not preserve scope while changing version')
            active(directory)
            attempt['release_requested_at'] = time.time()
            attempt['release'] = {'operation_id': barrier['operation_id']}
            save(gate / 'record.json', record)
            save(path.parent / 'preflight-release.json', attempt['release'])
            if cancelled:
                break
        deadline = record['attempts'][0]['release_requested_at'] + spec['escalation_deadline_seconds']
        await_file(repair_episode / 'outcome.json', time.monotonic() + max(0, deadline - time.time()))
        if spec['refresh_case'] == 'continuing' or cancelled:
            require(process.wait(timeout=max(1, deadline - time.time())) == 0, 'Operator failed instead of escalating')
        record['after_operations'] = kube.get_service(kube.namespace, 'inventory')
        record['after_operations_at'] = time.time()
        save(gate / 'record.json', record)
        owner.wait(timeout=max(1, window['end'] - time.time()) + 180)
        require(owner.returncode == 0, 'Campaign owner failed')
        result['execution_completed'] = True
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        finalized = False
        try:
            if owner is not None:
                finalize_gate(owner, children, directory, gate, result)
                finalized = True
        finally:
            try:
                if (directory / 'window.json').exists():
                    capture_audit(gate)
                    for suffix in ('a', 'b'):
                        save(gate / f'scorecard-{suffix}.json', scorecard(directory))
                        save(gate / f'evaluation-{suffix}.json', evaluator(gate))
                    for name in ('scorecard', 'evaluation'):
                        require((gate / f'{name}-a.json').read_bytes() == (gate / f'{name}-b.json').read_bytes(), 'Offline export differs')
                    assessment = read(gate / 'evaluation-a.json')
                    result['evaluation_status'] = assessment['status']
                    if finalized and result.get('execution_completed') and not result.get('error_type') and not result.get('cleanup_errors') and assessment['status'] == 'passed':
                        result.update(status='passed', export_identical=True)
            except Exception as error:
                result.update(status='failed', export_error_type=type(error).__name__)
            finally:
                result['finished_at'] = time.time()
                save(gate / 'result.json', result)
    require(result['status'] == 'passed', 'Bounded refresh gate failed; evidence retained')


def evaluate_uncertain(gate):
    capture_audit(gate)
    return evaluate(gate)


def run(*, interpreted=False):
    gate = ROOT / 'artifacts' / (('program-refresh-gate-' if interpreted else 'refresh-gate-') + uuid.uuid4().hex[:8])
    gate.mkdir(parents=True, mode=0o700)
    specs = [declaration(case, interpreted=interpreted) for case in CASES]
    save(gate / 'declaration.json', {'cases': specs})
    ledger = {'status': 'running', 'started_at': time.time(), 'cases': {case: {'status': 'unrun'} for case in CASES}}
    save(gate / 'result.json', ledger)
    try:
        for spec in specs:
            case = gate / spec['refresh_case']
            case.mkdir()
            save(case / 'declaration.json', spec)
            ledger['cases'][spec['refresh_case']] = {'status': 'running'}
            save(gate / 'result.json', ledger)
            try:
                if spec['refresh_case'] == 'uncertain_external_change':
                    run_ambiguity(case, spec, manifest=ROOT / spec['manifest'], evaluator=evaluate_uncertain)
                else:
                    run_case(case, spec)
            except BaseException as error:
                ledger['cases'][spec['refresh_case']] = {'status': 'failed', 'error_type': type(error).__name__}
                if not isinstance(error, Exception):
                    raise
            else:
                ledger['cases'][spec['refresh_case']] = {'status': 'passed'}
            save(gate / 'result.json', ledger)
        ledger['status'] = 'passed' if all(r['status'] == 'passed' for r in ledger['cases'].values()) else 'failed'
        require(ledger['status'] == 'passed', 'One or more refresh cases failed; no retry')
    except BaseException as error:
        ledger.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        ledger['finished_at'] = time.time()
        save(gate / 'result.json', ledger)
        print(gate, flush=True)
    return gate


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interpreted', action='store_true')
    run(interpreted=parser.parse_args().interpreted)
