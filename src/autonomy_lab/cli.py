"""Local development and acceptance commands."""

import argparse
import math
from pathlib import Path

import yaml

from autonomy_lab.environment import teardown
from autonomy_lab.harness import run_demo


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("duration must be a finite positive number")
    return number


def main():
    parser = argparse.ArgumentParser(description="Autonomy Lab: real-cluster experiments")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser(
        "demo", help="create a fresh cluster, run acceptance checks, export evidence"
    )
    demo.add_argument("--window-seconds", type=positive_seconds, default=30)
    demo.add_argument("--keep", action="store_true", help="keep this run's cluster for inspection")
    cleanup = commands.add_parser(
        "cleanup", help="delete only the disposable cluster recorded in a run"
    )
    cleanup.add_argument("run_dir", type=Path)
    experiment = commands.add_parser(
        "experiment", help="run the declared development scenario matrix"
    )
    experiment.add_argument("--manifest", type=Path, default=Path("scenarios/pilot.yaml"))
    experiment.add_argument("--env-file", type=Path, default=Path("~/Dev/.env"))
    experiment.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.command == "demo":
        print(run_demo(window_seconds=args.window_seconds, keep=args.keep) / "REPORT.md")
    elif args.command == "cleanup":
        teardown(args.run_dir.resolve())
    elif args.command == "experiment":
        from autonomy_lab.experiments import run_experiment

        config = yaml.safe_load(args.manifest.read_text())
        print(run_experiment(config, env_file=args.env_file, keep=args.keep) / "REPORT.md")


if __name__ == "__main__":
    main()
