"""Execute the frozen eight-case comparison once, and reproduce from raw evidence."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from autonomy_lab.campaign import active, operation_rows, read, spawn_worker, wait_ready
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT, Kubernetes
from autonomy_lab.procedures import Refused, require
from autonomy_lab.withdrawal import capture_audit
from scripts.check_campaign import await_file, finalize_gate, wait_until
from scripts.check_recurrence import stop_and_reap

from .audit import SEQUENCES, bindings, controller_patch
from .gate import (
    SHARDS,
    declaration,
    evaluate,
    plan,
    recovered_before_recurrence,
    select,
)


def run_case(
    gate,
    spec,
    *,
    declaration_fn=None,
    evaluate_fn=None,
    conflict_phase="first",
    sequences=None,
    early_change=False,
):
    declaration_fn = declaration if declaration_fn is None else declaration_fn
    evaluate_fn = evaluate if evaluate_fn is None else evaluate_fn
    sequences = SEQUENCES if sequences is None else sequences
    require(
        spec == declaration_fn(spec["arm"], spec["context"]),
        "Frozen case changed before provisioning",
    )
    directory = gate / "campaign"
    save(gate / "declaration.json", spec)
    save(gate / "manifest.json", spec["contract"])
    result = {"status": "failed", "started_at": time.time()}
    record, children = {"checkpoints": []}, []
    save(gate / "result.json", result)
    with (gate / "owner.log").open("ab") as log:
        owner = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "autonomy_lab.campaign",
                "own",
                str(gate / "manifest.json"),
                str(directory),
            ],
            stdout=log,
            stderr=log,
            start_new_session=True,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(ROOT / "src")},
        )
    try:
        window = await_file(
            directory / "window.json", time.monotonic() + spec["provision_timeout_seconds"]
        )
        start = window["start"]
        record["run_id"] = read(directory / "owner.json")["run_id"]
        initial = next((directory / "workers").glob("operator-*"))
        record["initial_worker"] = initial.name
        kube = Kubernetes(directory / "kubeconfig", read(directory / "environment.json")["cluster"])

        def change(kind, target, key, before=None):
            active(directory)
            before = kube.get_service(kube.namespace, "inventory") if before is None else before
            action = {
                "kind": kind,
                "before": before,
                "patch": controller_patch(before, kind),
                "tag": "confirmation-" + kind + "-" + str(len(record["checkpoints"])),
                "requested_at": time.time(),
            }
            target[key] = action
            save(gate / "record.json", record)
            kube.audit_operation_id = action["tag"]
            action["response"] = kube.patch_service(kube.namespace, "inventory", action["patch"])
            action["finished_at"] = time.time()
            save(gate / "record.json", record)

        def response(phase):
            wait_until(start + spec[phase + "_start_offset"])
            record[phase + "_requested_at"] = time.time()
            worker, process = spawn_worker(directory, "operator")
            children.append((worker, process))
            record[phase + "_worker"] = worker.name
            save(gate / "record.json", record)
            wait_ready(worker, process, timeout=20)
            # Continue releasing barriers after the first episode. The evaluator
            # measures its deadline independently of the worker's lifetime.
            deadline = start + spec["first_stop_offset"] if phase == "first" else window["end"]
            seen = set()
            while process.poll() is None and time.time() < deadline:
                queued = [
                    (stage, path, read(path))
                    for stage in ("intent", "preflight")
                    for path in (worker / stage).glob("*/" + stage + "-barrier.json")
                    if (stage, path.parent.name) not in seen
                ]
                if (
                    phase == "first"
                    and spec["context"] == "heartbeat_post_ack"
                    and "post_ack" not in record
                    and time.time() >= start + spec["post_ack_offset"]
                ):
                    operations = operation_rows(directory)
                    acknowledged = [o for o in operations if o["status"] == "acknowledged"]
                    require(
                        len(acknowledged) == 1
                        and all(o["status"] in {"acknowledged", "rejected"} for o in operations),
                        "Post-ack intervention lacks completed original repair",
                    )
                    record["post_ack_operation"] = acknowledged[0]
                    change("tick-1", record, "post_ack")
                if not queued:
                    time.sleep(0.05)
                    continue
                stage, path, barrier = min(queued, key=lambda item: item[2]["at"])
                op_id = barrier["operation_id"]
                seen.add((stage, op_id))
                active(directory)
                point = {
                    "phase": phase,
                    "stage": stage,
                    "operation_id": op_id,
                    "barrier": barrier,
                    "operation": next(
                        o for o in operation_rows(directory) if o["operation_id"] == op_id
                    ),
                    "binding": bindings(directory)[op_id],
                    "before": kube.get_service(kube.namespace, "inventory"),
                    "before_at": time.time(),
                }
                record["checkpoints"].append(point)
                save(gate / "record.json", record)
                first_id = next(
                    p["operation_id"] for p in record["checkpoints"] if p["phase"] == phase
                )
                if phase == conflict_phase and op_id == first_id and stage == "preflight":
                    point["changes"] = []
                    for kind in sequences[spec["context"]]:
                        entry = {}
                        point["changes"].append(entry)
                        # A separate real read and conditional API request for each change.
                        change(kind, entry, "action")
                        point["changes"][-1] = entry["action"]
                        save(gate / "record.json", record)
                point["after"] = kube.get_service(kube.namespace, "inventory")
                point["after_at"] = time.time()
                point["release_requested_at"] = time.time()
                save(gate / "record.json", record)
                save(path.parent / (stage + "-release.json"), {"operation_id": op_id})

        wait_until(start + spec["fixture_offset"])
        change("fixture", record, "fixture")
        wait_until(start + spec["stop_offset"])
        record["stop_requested_at"] = time.time()
        save(gate / "record.json", record)
        record["stopped_at"] = stop_and_reap(initial, children)
        wait_until(start + spec["fault_offset"])
        change("fault", record, "fault")
        response("first")
        wait_until(start + spec["first_stop_offset"])
        record["first_stop_requested_at"] = time.time()
        save(gate / "record.json", record)
        record["first_stopped_at"] = stop_and_reap(
            directory / "workers" / record["first_worker"], children
        )
        record["operations_first"] = operation_rows(directory)
        wait_until(start + spec["second_fault_offset"] - 1)
        samples = [read(p) for p in sorted((directory / "samples").glob("*.json"))]
        require(
            {9, 10, 11} <= {s["slot"] for s in samples},
            "Recovery-window samples missing before recurrence decision",
        )
        recovered = recovered_before_recurrence(samples, start)
        record["recurrence_opportunity"] = "realized" if recovered else "unrealized"
        save(gate / "record.json", record)
        if record["recurrence_opportunity"] == "realized":
            wait_until(start + spec["second_fault_offset"])
            change("second_fault", record, "second_fault")
        if early_change and record["recurrence_opportunity"] == "realized":
            wait_until(start + spec["early_change_offset"])
            change("annotation", record, "early_change")
        response("second")
        owner.wait(timeout=max(1, window["end"] - time.time()) + 180)
        require(owner.returncode == 0, "Campaign owner failed")
        capture_audit(gate)
        for suffix in ("a", "b"):
            save(gate / f"scorecard-{suffix}.json", scorecard(directory))
            save(gate / f"evaluation-{suffix}.json", evaluate_fn(gate))
        for name in ("scorecard", "evaluation"):
            require(
                (gate / f"{name}-a.json").read_bytes() == (gate / f"{name}-b.json").read_bytes(),
                "Offline export differs",
            )
        result.update(status="passed", evaluation=read(gate / "evaluation-a.json"))
    except BaseException as error:
        result["error_type"] = type(error).__name__
        if isinstance(error, Refused):
            result["check_failure"] = str(error)
        raise
    finally:
        try:
            if (directory / "window.json").exists():
                save(gate / "scorecard-final.json", scorecard(directory))
        except Exception as error:
            result["export_error_type"] = type(error).__name__
        try:
            finalize_gate(owner, children, directory, gate, result)
        finally:
            try:
                if (directory / "environment.json").exists():
                    capture_audit(gate)
            except Exception as error:
                result.update(status="failed", audit_capture_error_type=type(error).__name__)
            save(gate / "result.json", result)


def run_shard(plan_path, shard, destination, *, plan_fn=None, runner=None, shards=SHARDS):
    plan_fn = plan if plan_fn is None else plan_fn
    runner = run_case if runner is None else runner
    destination = destination.resolve()
    declared = read(plan_path)
    require(
        declared == plan_fn() and type(shard) is int and 0 <= shard < shards,
        "Frozen plan or shard differs",
    )
    destination.mkdir(parents=True, exist_ok=False)
    save(destination / "plan.json", declared)
    result = {
        "status": "failed",
        "shard": shard,
        "started_at": time.time(),
        "cases": {},
        "unrun": declared["shards"][shard][:],
    }
    save(destination / "result.json", result)
    try:
        for name in declared["shards"][shard]:
            gate = destination / "cases" / name
            gate.mkdir(parents=True)
            result["unrun"].remove(name)
            result["cases"][name] = {"status": "attempting", "started_at": time.time()}
            save(destination / "result.json", result)
            try:
                runner(gate, declared["cases"][name])
                result["cases"][name] = read(gate / "result.json")
            except Exception as error:
                result["cases"][name] = {
                    **(read(gate / "result.json") if (gate / "result.json").exists() else {}),
                    "status": "failed",
                    "error_type": type(error).__name__,
                }
            save(destination / "result.json", result)
        result["status"] = (
            "passed" if all(c["status"] == "passed" for c in result["cases"].values()) else "failed"
        )
    finally:
        result["finished_at"] = time.time()
        save(destination / "result.json", result)
    require(result["status"] == "passed", "Comparison shard incomplete; all attempts retained")


def reproduce(
    plan_path,
    source,
    destination,
    *,
    plan_fn=None,
    evaluate_fn=None,
    challenge_fn=None,
    select_fn=None,
    shards=SHARDS,
    artifact_prefix="contract-confirmation",
):
    plan_fn = plan if plan_fn is None else plan_fn
    evaluate_fn = evaluate if evaluate_fn is None else evaluate_fn
    select_fn = select if select_fn is None else select_fn
    declared, source, destination = read(plan_path), source.resolve(), destination.resolve()
    require(declared == plan_fn(), "Frozen plan or source changed")
    destination.mkdir(parents=True, exist_ok=False)
    receipt = {
        "status": "incomplete",
        "evaluations": {},
        "errors": {},
        "shards": {},
        "selection": None,
    }
    save(destination / "reproduction.json", receipt)
    for shard in range(shards):
        path = source / f"{artifact_prefix}-shard-{shard}"
        try:
            require(read(path / "plan.json") == declared, "Shard used different plan")
            ledger = read(path / "result.json")
            receipt["shards"][str(shard)] = ledger
            require(
                ledger["shard"] == shard
                and ledger["status"] == "passed"
                and ledger["unrun"] == []
                and set(ledger["cases"]) == set(declared["shards"][shard]),
                "Incomplete shard ledger",
            )
            require(
                {p.name for p in (path / "cases").iterdir()} == set(declared["shards"][shard]),
                "Case inventory differs",
            )
        except (OSError, KeyError, ValueError, TypeError) as error:
            receipt["errors"][f"shard-{shard}"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            continue
        for name in declared["shards"][shard]:
            try:
                gate = path / "cases" / name
                require(
                    ledger["cases"][name]["status"]
                    == read(gate / "result.json")["status"]
                    == "passed",
                    "Original case did not pass",
                )
                value = evaluate_fn(gate)
                require(
                    value == read(gate / "evaluation-a.json") == read(gate / "evaluation-b.json"),
                    "Original exports differ",
                )
                receipt["evaluations"][name] = value
            except (
                OSError,
                KeyError,
                ValueError,
                TypeError,
                AssertionError,
                StopIteration,
            ) as error:
                receipt["errors"][name] = {"type": type(error).__name__, "message": str(error)}
    if not receipt["errors"]:
        try:
            from .negative import challenge

            receipt["negative_controls"] = (challenge if challenge_fn is None else challenge_fn)(
                source
            )
            receipt["selection"] = select_fn(declared, receipt["evaluations"])
            receipt["status"] = "complete"
        except (OSError, KeyError, ValueError, TypeError, AssertionError) as error:
            receipt["errors"]["qualification"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
    save(destination / "reproduction.json", receipt)
    require(receipt["status"] == "complete", "Comparison incomplete; selection withheld")
    return receipt


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
