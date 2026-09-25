"""Freeze, execute once, and independently reproduce every finite-search case."""

import argparse
import time
from pathlib import Path

from check_budget_horizon import run_case

from autonomy_lab.campaign import read
from autonomy_lab.harness import save
from autonomy_lab.policy_search import SHARDS, declaration, evaluate, plan, select
from autonomy_lab.procedures import require


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
                run_case(gate, spec, declaration(spec['policy'], spec['context']), evaluate)
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
    require(result['status'] == 'passed', 'Search shard incomplete; all attempts retained')


def reproduce(plan_path, source, destination):
    source, destination = source.resolve(), destination.resolve()
    declared = read(plan_path)
    require(declared == plan(), 'Frozen plan or source changed')
    destination.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'incomplete', 'evaluations': {}, 'errors': {}, 'shards': {},
               'selection': None, 'evidence_use': 'finite_development'}
    save(destination / 'reproduction.json', receipt)
    for shard in range(SHARDS):
        path = source / f'policy-search-shard-{shard}'
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
    require(receipt['status'] == 'complete', 'Finite comparison incomplete; selection withheld')
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
    args = parser.parse_args()
    if args.command == 'freeze':
        require(not args.destination.exists(), 'Cannot overwrite frozen plan')
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        save(args.destination, plan())
    elif args.command == 'run':
        run_shard(args.plan, args.shard, args.destination)
    else:
        reproduce(args.plan, args.source, args.destination)
