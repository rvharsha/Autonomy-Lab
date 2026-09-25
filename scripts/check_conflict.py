"""Execute once: actual API rejection after a harmless concurrent version change."""

import os
import subprocess
import sys
import time
import uuid

from check_ambiguity import change_routing
from check_campaign import await_file, finalize_gate, wait_until
from check_recurrence import stop_and_reap

from autonomy_lab.audit import read_events
from autonomy_lab.campaign import active, operation_rows, read, spawn_worker, wait_ready
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.conflict import annotation_patch, declaration, evaluate
from autonomy_lab.harness import client_path_failed, save
from autonomy_lab.kubernetes import ROOT, Kubernetes
from autonomy_lab.procedures import require


def run_case(gate, spec):
    directory = gate / 'campaign'
    result = {'status': 'failed', 'started_at': time.time(), 'declaration': spec}
    children = []
    record = {}
    owner = None
    save(gate / 'result.json', result)
    try:
        with (gate / 'owner.log').open('ab') as log:
            owner = subprocess.Popen([sys.executable, '-m', 'autonomy_lab.campaign', 'own',
                str(ROOT / 'scenarios/campaign-conflict.json'), str(directory)],
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
        barrier = await_file(repair / 'preflight-barrier.json', time.monotonic() + max(
            0, window['start'] + spec['barrier_deadline_offset'] - time.time()))
        prior = operation_rows(directory)
        save(gate / 'before-release.json', prior)
        require(len(prior) == 1 and prior[0]['status'] == 'prepared'
                and prior[0]['operation_id'] == barrier['operation_id'], 'Original prepared operation missing')
        active(directory)
        before = kube.get_service(kube.namespace, 'inventory')
        record['before_change'] = before
        change = {'requested_at': time.time(), 'patch': annotation_patch(before, barrier['operation_id'])}
        record['change'] = change
        save(gate / 'record.json', record)
        kube.audit_operation_id = 'conflict-version-bump'
        changed = kube.patch_service(kube.namespace, 'inventory', change['patch'])
        change['finished_at'] = time.time()
        record['changed_service'] = changed
        save(gate / 'record.json', record)
        require(changed['spec'] == before['spec'] and changed['metadata']['uid'] == before['metadata']['uid']
                and changed['metadata']['resourceVersion'] != before['metadata']['resourceVersion'],
                'Controller change did not preserve scope while changing version')
        active(directory)
        record['release_requested_at'] = time.time()
        save(gate / 'record.json', record)
        save(repair / 'preflight-release.json', {'operation_id': barrier['operation_id']})
        require(process.wait(timeout=max(1, record['release_requested_at'] + spec['escalation_deadline_seconds'] - time.time())) == 0,
                'Operator failed instead of escalating')
        record['after_rejection'] = kube.get_service(kube.namespace, 'inventory')
        record['after_rejection_at'] = time.time()
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
                    save(gate / 'server-audit.json', {**read_events(directory / 'server-audit'),
                         'collection_closed': read(directory / 'environment.json')['status'] == 'deleted'})
                    for suffix in ('a', 'b'):
                        save(gate / f'scorecard-{suffix}.json', scorecard(directory))
                        save(gate / f'evaluation-{suffix}.json', evaluate(gate))
                    for name in ('scorecard', 'evaluation'):
                        require((gate / f'{name}-a.json').read_bytes() == (gate / f'{name}-b.json').read_bytes(),
                                'Offline export differs')
                    assessment = read(gate / 'evaluation-a.json')
                    result['evaluation_status'] = assessment['status']
                    if finalized and result.get('execution_completed') and not result.get('error_type') and not result.get('cleanup_errors') and assessment['status'] == 'passed':
                        result.update(status='passed', export_identical=True)
            except Exception as error:
                result.update(status='failed', export_error_type=type(error).__name__)
            finally:
                result['finished_at'] = time.time()
                save(gate / 'result.json', result)
    require(result['status'] == 'passed', 'Conditional rejection gate failed; evidence retained')


def run():
    gate = ROOT / 'artifacts' / ('conflict-gate-' + uuid.uuid4().hex[:8])
    gate.mkdir(parents=True, mode=0o700)
    spec = declaration()
    save(gate / 'declaration.json', spec)
    try:
        run_case(gate, spec)
    finally:
        print(gate, flush=True)
    return gate


if __name__ == '__main__':
    run()
