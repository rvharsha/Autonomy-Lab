"""Freeze, execute once, and reproduce the final-slot cohort."""

import argparse
from pathlib import Path

from autonomy_lab.harness import save
from autonomy_lab.procedures import require
from experiments.contract_confirmation import run as shared

from .gate import SEQUENCES, SHARDS, declaration, evaluate, plan, select
from .negative import challenge


def run_case(gate, spec):
    shared.run_case(
        gate,
        spec,
        declaration_fn=declaration,
        evaluate_fn=evaluate,
        conflict_phase="second",
        sequences=SEQUENCES,
        early_change=spec["context"] == "protected_before",
    )


def run_shard(plan_path, shard, destination):
    return shared.run_shard(
        plan_path, shard, destination, plan_fn=plan, runner=run_case, shards=SHARDS
    )


def reproduce(plan_path, source, destination):
    return shared.reproduce(
        plan_path,
        source,
        destination,
        plan_fn=plan,
        evaluate_fn=evaluate,
        challenge_fn=challenge,
        select_fn=select,
        shards=SHARDS,
        artifact_prefix="final-slot",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("destination", type=Path)
    run = commands.add_parser("run")
    run.add_argument("plan", type=Path)
    run.add_argument("shard", type=int)
    run.add_argument("destination", type=Path)
    replay = commands.add_parser("reproduce")
    replay.add_argument("plan", type=Path)
    replay.add_argument("source", type=Path)
    replay.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        require(not args.destination.exists(), "Cannot overwrite frozen plan")
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        save(args.destination, plan())
    elif args.command == "run":
        run_shard(args.plan, args.shard, args.destination)
    else:
        reproduce(args.plan, args.source, args.destination)
