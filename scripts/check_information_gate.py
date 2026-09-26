"""Run real contention schedules independent of the response's dispatches."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from check_ambiguity import change_routing
from check_campaign import await_file, finalize_gate, wait_until
from check_recurrence import stop_and_reap

from autonomy_lab.campaign import active, read, spawn_worker
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import save
from autonomy_lab.information_gate import (
    SHARDS,
    churn_patch,
    declaration,
    evaluate,
    launch_decision,
    plan,
    select,
)
from autonomy_lab.kubernetes import ROOT, Kubernetes
from autonomy_lab.procedures import require
from autonomy_lab.withdrawal import capture_audit


def churn(gate):
    """Separate controller: no worker paths, barriers or policy choice are read."""
    gate = gate.resolve()
    spec, directory = read(gate / 'declaration.json'), gate / 'campaign'
    require(spec == declaration(spec['arm'], spec['context']), 'Controller source or declaration changed')
    start = read(directory / 'window.json')['start']
    kube = Kubernetes(directory / 'kubeconfig', read(directory / 'environment.json')['cluster'])
    service = kube.get_service(kube.namespace, 'inventory')
    record = {'initial_annotations': service['metadata'].get('annotations', {}),
              'actions': [], 'finished': False}
    save(gate / 'churn.json', record)
    for index, offset in enumerate(spec['churn_offsets']):
        wait_until(start + offset)
        active(directory)
        row = {'index': index, 'requested_at': time.time(),
               'patch': churn_patch(service['metadata']['uid'], record['initial_annotations'], index)}
        record['actions'].append(row)
        save(gate / 'churn.json', record)
        require(0 <= row['requested_at'] - (start + offset) <= 1, 'Churn missed its calendar')
        kube.audit_operation_id = 'information-churn-' + str(index)
        row['response'] = kube.patch_service(kube.namespace, 'inventory', row['patch'])
        row['finished_at'] = time.time()
        save(gate / 'churn.json', record)
    record['finished'] = True
    save(gate / 'churn.json', record)


def run_case(gate, spec):
    gate = gate.resolve()
    require(spec == declaration(spec['arm'], spec['context']), 'Frozen case changed')
    directory = gate / 'campaign'
    save(gate / 'declaration.json', spec)
    save(gate / 'manifest.json', spec['contract'])
    result = {'status': 'failed', 'started_at': time.time()}
    record = {'decisions': [], 'barriers': []}
    children, controller = [], None
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src')}
    with (gate / 'owner.log').open('ab') as log:
        owner = subprocess.Popen([sys.executable, '-m', 'autonomy_lab.campaign', 'own',
                                  str(gate / 'manifest.json'), str(directory)], stdout=log, stderr=log,
                                 start_new_session=True, env=env)
    try:
        window = await_file(directory / 'window.json', time.monotonic() + 900)
        start = window['start']
        initial = next((directory / 'workers').glob('operator-*'))
        record['initial_worker'] = initial.name
        cluster = read(directory / 'environment.json')['cluster']
        kube = Kubernetes(directory / 'kubeconfig', cluster)
        observer = Kubernetes(directory / 'observer-kubeconfig', cluster)
        wait_until(start + spec['stop_offset'])
        record['stop_requested_at'] = time.time()
        save(gate / 'record.json', record)
        record['stopped_at'] = stop_and_reap(initial, children)
        wait_until(start + spec['fault_offset'])
        change_routing(kube, directory, gate, record, 'fault', 8080, 9999)
        with (gate / 'churn.log').open('ab') as log:
            controller = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'churn', str(gate)],
                                          stdout=log, stderr=log, start_new_session=True, env=env)
        origin = start + spec['decision_offset']
        history, repair, index, terminal = [], None, 0, False
        while time.time() < window['end']:
            active(directory)
            require(controller.poll() in {None, 0}, 'Independent controller failed')
            if not terminal and time.time() >= origin + index:
                row = {}
                if spec['arm'] == 'observe_quiet':
                    observation = {'requested_at': time.time()}
                    row['observation'] = observation
                    service = json.loads(observer.call('get', 'service', 'inventory', '-o', 'json', timeout=1))
                    observation.update(finished_at=time.time(), service=service)
                    history.append({'elapsed': observation['finished_at'] - origin,
                                    'uid': service['metadata']['uid'], 'version': service['metadata']['resourceVersion']})
                row['at'] = time.time()
                row['decision'] = launch_decision(spec['arm'], history, row['at'] - origin)
                record['decisions'].append(row)
                save(gate / 'record.json', record)
                index += 1
                terminal = row['decision'] != 'wait'
                if row['decision'] == 'launch':
                    record['launch_requested_at'] = time.time()
                    repair, process = spawn_worker(directory, 'operator')
                    children.append((repair, process))
                    record['repair_worker'] = repair.name
                    save(gate / 'record.json', record)
            if repair is not None:
                for path in sorted((repair / 'preflight').glob('*/preflight-barrier.json')):
                    barrier = read(path)
                    if not any(b['operation_id'] == barrier['operation_id'] for b in record['barriers']):
                        record['barriers'].append(barrier)
                        save(gate / 'record.json', record)
                    row = next(b for b in record['barriers'] if b['operation_id'] == barrier['operation_id'])
                    if 'release_at' not in row and time.time() >= barrier['at'] + spec['dispatch_delay_seconds']:
                        row['release_at'] = time.time()
                        save(gate / 'record.json', record)
                        save(path.parent / 'preflight-release.json', {'operation_id': barrier['operation_id']})
            time.sleep(.025)
        require(terminal, 'Selector never finished')
        require(controller.wait(timeout=5) == 0, 'Independent controller failed')
        frozen_churn = read(gate / 'churn.json')
        record.update(churn=frozen_churn['actions'], churn_finished=frozen_churn['finished'],
                      initial_annotations=frozen_churn['initial_annotations'])
        save(gate / 'record.json', record)
        owner.wait(timeout=180)
        require(owner.returncode == 0, 'Campaign owner failed')
        capture_audit(gate)
        for label in ('a', 'b'):
            save(gate / f'scorecard-{label}.json', scorecard(directory))
            save(gate / f'evaluation-{label}.json', evaluate(gate))
        for name in ('scorecard', 'evaluation'):
            require((gate / f'{name}-a.json').read_bytes() == (gate / f'{name}-b.json').read_bytes(),
                    'Repeated offline exports differ')
        result.update(status='passed', evaluation=read(gate / 'evaluation-a.json'))
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        try:
            if controller is not None:
                if controller.poll() is None:
                    os.killpg(controller.pid, signal.SIGKILL)
                controller.wait(timeout=10)
        except Exception as error:
            result.update(status='failed', controller_cleanup_error_type=type(error).__name__)
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


def run_shard(plan_path, shard, destination):
    destination = destination.resolve()
    declared = read(plan_path)
    require(declared == plan() and type(shard) is int and 0 <= shard < SHARDS,
            'Frozen plan or shard differs')
    destination.mkdir(parents=True, exist_ok=False)
    save(destination / 'plan.json', declared)
    order = declared['shards'][shard]
    result = {'status': 'failed', 'shard': shard, 'started_at': time.time(),
              'cases': {}, 'unrun': list(order)}
    save(destination / 'result.json', result)
    try:
        for name in order:
            spec = declared['cases'][name]
            gate = destination / 'cases' / name
            gate.mkdir(parents=True)
            result['unrun'].remove(name)
            result['cases'][name] = {'status': 'attempting', 'started_at': time.time()}
            save(destination / 'result.json', result)
            try:
                run_case(gate, spec)
                result['cases'][name] = read(gate / 'result.json')
            except Exception as error:
                result['cases'][name] = {**(read(gate / 'result.json') if (gate / 'result.json').exists() else {}),
                                         'status': 'failed', 'error_type': type(error).__name__}
            result['cases'][name]['finished_at'] = time.time()
            save(destination / 'result.json', result)
        result['status'] = 'passed' if all(c['status'] == 'passed' for c in result['cases'].values()) else 'failed'
    finally:
        result['finished_at'] = time.time()
        save(destination / 'result.json', result)
    require(result['status'] == 'passed', 'Information shard incomplete; all attempts retained')


def reproduce(plan_path, source, destination):
    source, destination = source.resolve(), destination.resolve()
    declared = read(plan_path)
    require(declared == plan(), 'Frozen plan or source changed')
    destination.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'incomplete', 'evaluations': {}, 'errors': {}, 'shards': {},
               'selection': None, 'evidence_use': 'information_development'}
    save(destination / 'reproduction.json', receipt)
    for shard in range(SHARDS):
        path = source / f'information-gate-shard-{shard}'
        try:
            require(read(path / 'plan.json') == declared, 'Shard ran a different plan')
            ledger = read(path / 'result.json')
            receipt['shards'][str(shard)] = ledger
            require(ledger['shard'] == shard and ledger['status'] == 'passed' and ledger['unrun'] == []
                    and set(ledger['cases']) == set(declared['shards'][shard]), 'Incomplete shard ledger')
            require({p.name for p in (path / 'cases').iterdir()} == set(declared['shards'][shard]),
                    'Unexpected or missing case directory')
        except (OSError, KeyError, TypeError, ValueError) as error:
            receipt['errors'][f'shard-{shard}'] = {'error_type': type(error).__name__, 'message': str(error)}
            continue
        for name in declared['shards'][shard]:
            try:
                gate = path / 'cases' / name
                require(ledger['cases'][name]['status'] == read(gate / 'result.json')['status'] == 'passed',
                        'Original attempt did not pass')
                value = evaluate(gate)
                # Recompute from raw probes, journal, pins and API audit, never
                # select from caller-supplied summaries or a favorable subset.
                require(value == read(gate / 'evaluation-a.json') == read(gate / 'evaluation-b.json'),
                        'Original exports differ from independent reproduction')
                receipt['evaluations'][name] = value
            except (OSError, KeyError, TypeError, ValueError, AssertionError) as error:
                receipt['errors'][name] = {'error_type': type(error).__name__, 'message': str(error)}
    if not receipt['errors']:
        try:
            receipt['selection'] = select(declared, receipt['evaluations'])
            receipt['status'] = 'complete'
        except (KeyError, TypeError, ValueError) as error:
            receipt['errors']['selection'] = {'error_type': type(error).__name__, 'message': str(error)}
    save(destination / 'reproduction.json', receipt)
    require(receipt['status'] == 'complete', 'Information comparison incomplete; selection withheld')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    freeze = commands.add_parser('freeze')
    freeze.add_argument('destination', type=Path)
    shard = commands.add_parser('run')
    shard.add_argument('plan', type=Path)
    shard.add_argument('shard', type=int)
    shard.add_argument('destination', type=Path)
    replay = commands.add_parser('reproduce')
    replay.add_argument('plan', type=Path)
    replay.add_argument('source', type=Path)
    replay.add_argument('destination', type=Path)
    controller = commands.add_parser('churn')
    controller.add_argument('gate', type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        require(not args.destination.exists(), 'Cannot overwrite frozen plan')
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        save(args.destination, plan())
    elif args.command == 'run':
        run_shard(args.plan, args.shard, args.destination)
    elif args.command == 'churn':
        churn(args.gate)
    else:
        reproduce(args.plan, args.source, args.destination)
