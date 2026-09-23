"""Run explicit manifests once, retaining a suite ledger and every failed/unrun phase."""

import argparse
import hashlib
import json
import uuid
from pathlib import Path

import yaml

from autonomy_lab.experiments import release_manifest, run_experiment, validate_config
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT


def plan(paths):
    phases = []
    for path in paths:
        data = path.read_bytes()
        config = yaml.safe_load(data)
        validate_config(config)
        phases.append({"manifest_sha256": hashlib.sha256(data).hexdigest(),
                       "config": config, "status": "unrun",
                       "planned": len(config["scenarios"]) * len(config["variants"]) * config["repetitions"]})
    return {"status": "planned", "source_files": release_manifest(phases[0]["config"])["files"],
            "phases": phases, "planned": sum(p["planned"] for p in phases)}


def execute(record, output, env_file):
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    record["status"] = "running"
    save(output / "evaluation.json", record)
    try:
        for phase in record["phases"]:
            if release_manifest(phase["config"])["files"] != record["source_files"]:
                raise RuntimeError("Source changed after evaluation freeze")
            phase["status"] = "running"
            save(output / "evaluation.json", record)
            run_dir = run_experiment(phase["config"], env_file=env_file)
            phase.update(status="finished", run_dir=str(run_dir),
                         accounting=json.loads((run_dir / "accounting.json").read_text()))
            save(output / "evaluation.json", record)
            if release_manifest(phase["config"])["files"] != record["source_files"]:
                raise RuntimeError("Source changed during evaluation")
        record["status"] = "finished"
    except BaseException as error:
        for phase in record["phases"]:
            if phase["status"] == "running":
                phase.update(status="interrupted", error_type=type(error).__name__,
                             run_directory_unknown=True)
        record.update(status="stopped", error_type=type(error).__name__)
        raise
    finally:
        save(output / "evaluation.json", record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", nargs="+", type=Path)
    parser.add_argument("--env-file", type=Path, default=Path("~/Dev/.env"))
    parser.add_argument("--execute", action="store_true", help="Provision and run; may incur model charges")
    args = parser.parse_args()
    record = plan(args.manifests)
    if not args.execute:
        print(json.dumps(record, indent=2))
        return
    output = ROOT / "artifacts" / ("evaluation-" + uuid.uuid4().hex[:8])
    print(output, flush=True)
    execute(record, output, args.env_file)
    print(output / "evaluation.json", flush=True)


if __name__ == "__main__":
    main()
