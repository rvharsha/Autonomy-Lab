"""Reproduce experience, freeze its choice, execute once, independently assess."""

import argparse
import tempfile
import time
from pathlib import Path

from autonomy_lab.campaign import read
from autonomy_lab.harness import save
from autonomy_lab.procedures import require
from experiments.contract_confirmation import run as shared
from experiments.final_slot.gate import SEQUENCES

from .gate import SHARDS, declaration, evaluate, plan, select
from .negative import challenge
from .training import reproduce_training


def freeze(archives, destination):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    selection = reproduce_training(archives, destination / 'training')
    value = plan(selection, time.time())
    save(destination / 'plan.json', value)
    return value


def run_shard(plan_path, shard, destination):
    declared = read(plan_path)
    selection, frozen_at = declared['selection'], declared['frozen_at']

    def runner(path, spec):
        return shared.run_case(
            path, spec,
            declaration_fn=lambda r, c: declaration(r, c, selection),
            evaluate_fn=lambda p: evaluate(p, selection, frozen_at),
            conflict_phase='second', sequences=SEQUENCES,
            early_change=spec['context'] == 'protected_before',
        )

    return shared.run_shard(plan_path, shard, destination,
                            plan_fn=lambda: plan(selection, frozen_at), runner=runner, shards=SHARDS)


def reproduce(plan_path, source, archives, destination):
    declared = read(plan_path)
    # Recreate selection from the original raw cohort; edited training summaries
    # cannot approve a different choice or retroactively use evaluation outcomes.
    with tempfile.TemporaryDirectory(prefix='shadow-training-') as temporary:
        selection = reproduce_training(archives, Path(temporary) / 'training')
    require(selection == declared['selection'], 'Frozen selection does not reproduce from training')
    frozen_at = declared['frozen_at']
    return shared.reproduce(
        plan_path, source, destination,
        plan_fn=lambda: plan(selection, frozen_at),
        evaluate_fn=lambda p: evaluate(p, selection, frozen_at),
        challenge_fn=lambda p: challenge(p, selection, frozen_at),
        select_fn=select, shards=SHARDS, artifact_prefix='shadow-selection',
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    frozen = commands.add_parser('freeze')
    frozen.add_argument('archives', type=Path)
    frozen.add_argument('destination', type=Path)
    run = commands.add_parser('run')
    run.add_argument('plan', type=Path)
    run.add_argument('shard', type=int)
    run.add_argument('destination', type=Path)
    replay = commands.add_parser('reproduce')
    replay.add_argument('plan', type=Path)
    replay.add_argument('source', type=Path)
    replay.add_argument('archives', type=Path)
    replay.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        freeze(args.archives, args.destination)
    elif args.command == 'run':
        run_shard(args.plan, args.shard, args.destination)
    else:
        reproduce(args.plan, args.source, args.archives, args.destination)
