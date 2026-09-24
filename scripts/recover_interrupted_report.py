"""Account for a service-interrupted trial without modifying its original evidence.

This is operator recovery, not a controller-finalized run or a re-score. A stopped
running trial remains unassessed. Supplied logs support integrity checks, not
independent authentication of the observations.
"""

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from export_report import identity
from report_agent_value import build, render


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recover(run, service_journal, cleanup_receipt, unit):
    if re.fullmatch(r"autolab-[a-z0-9-]+\.service", unit) is None:
        raise ValueError("Invalid study service identity")
    if (run / "accounting.json").exists() or (run / "cleanup.json").exists():
        raise ValueError("Use the ordinary exporter for finalized accounting")
    manifest = read(run / "manifest.json")
    results = read(run / "results.json")
    plan = manifest["planned_trials"]
    index = len(results) + 1
    if index > len(plan):
        raise ValueError("No planned interrupted trial remains")
    directory = run / f"trial-{index:03d}"
    partial = read(directory / "trial.json")
    if partial.get("status") != "running" or any(
        partial.get(key) is not None for key in
        ("score", "execution_audit", "protected_state_damage", "elapsed_seconds")
    ):
        raise ValueError("Expected an unassessed running trial")
    if any(partial.get(key) != plan[index - 1][key] for key in ("scenario", "variant")):
        raise ValueError("Partial trial does not match the plan")
    # Worker records normally omit repetition; the controller adds it to the
    # results list. Reject a contradictory supplied value instead of replacing it.
    if "repetition" in partial and (type(partial["repetition"]) is not int
                                   or partial["repetition"] != plan[index - 1]["repetition"]):
        raise ValueError("Partial repetition does not match the plan")
    expected_directories = {f"trial-{i:03d}" for i in range(1, index + 1)}
    if {p.name for p in run.glob("trial-*") if p.is_dir()} != expected_directories:
        raise ValueError("Trial directories do not match the accounted prefix")

    journal = [json.loads(line) for line in service_journal.read_text().splitlines() if line.strip()]
    if any(not isinstance(record, dict) for record in journal):
        raise ValueError("Invalid journal record")
    stops = [r for r in journal if r.get("SYSLOG_IDENTIFIER") == "systemd"
             and isinstance(r.get("MESSAGE"), str) and r["MESSAGE"].startswith(f"Stopping {unit} - ")]
    if len(stops) != 1:
        raise ValueError("Expected one explicit service-stop record")
    stopped = datetime.fromtimestamp(int(stops[0]["__REALTIME_TIMESTAMP"]) / 1_000_000, timezone.utc)
    started = datetime.fromisoformat(partial["started_at"])
    if started.tzinfo is None or stopped < started:
        raise ValueError("Service stop precedes the partial trial")
    cleanup = read(cleanup_receipt)
    if cleanup.get("run_id") != run.name or cleanup.get("status") != "deleted":
        raise ValueError("Cleanup receipt does not establish this run's deletion")
    if cleanup.get("method") != "manual_invocation_of_owned_resource_janitor_after_archival":
        raise ValueError("Unsupported cleanup receipt")
    archive_hash = cleanup.get("original_archive_sha256")
    if not isinstance(archive_hash, str) or re.fullmatch(r"[a-f0-9]{64}", archive_hash) is None:
        raise ValueError("Missing original archive digest")
    cleaned = datetime.fromisoformat(cleanup["finished_at"])
    if cleaned.tzinfo is None or cleaned < stopped:
        raise ValueError("Cleanup receipt precedes interruption")

    # The temporary copy contains only files used by the selected exporter.
    # Original trial bytes, provider records and credentials are never rewritten.
    recovered = {**partial, "repetition": plan[index - 1]["repetition"], "status": "interrupted"}
    combined = results + [recovered]
    with tempfile.TemporaryDirectory(prefix="autolab-interrupted-report-") as temp:
        target = Path(temp)
        for name in ("manifest.json", "release.json"):
            shutil.copyfile(run / name, target / name)
        for i in range(1, index + 1):
            name = f"trial-{i:03d}"
            (target / name).mkdir(mode=0o700)
            for filename in ("trial.json", "evidence.jsonl"):
                source = run / name / filename
                if source.exists():
                    shutil.copyfile(source, target / name / filename)
        # Keep trial.json itself unmodified so every trial digest refers to the
        # original bytes, including the interrupted worker's partial record.
        for filename, value in {
            "results.json": combined,
            "accounting.json": {"planned": len(plan), "recorded": len(combined), "unrun": [identity(p) for p in plan[index:]]},
            "cleanup.json": {"status": "deleted"},
        }.items():
            (target / filename).write_text(json.dumps(value))
        report = build(target)
        derived_hashes = {name: digest(target / name) for name in
                          ("results.json", "accounting.json", "cleanup.json")}
    report["evidence_sha256"] = {name: digest(run / name) for name in
                                 ("manifest.json", "release.json", "results.json")}
    report["trials"][-1]["status_source"] = "operator_recovery_from_service_stop"
    report["recovery"] = {
        "kind": "operator_reconstructed_accounting",
        "controller_final_accounting_available": False,
        "controller_finalized_trials": len(results), "interrupted_trial_index": index,
        "partial_repetition_source": "original_worker_record" if "repetition" in partial else "ordered_manifest_position",
        "original_partial_trial_sha256": digest(directory / "trial.json"),
        "service_unit": unit, "service_stopped_at": stopped.isoformat(),
        "service_journal_sha256": digest(service_journal),
        "cleanup_receipt_sha256": digest(cleanup_receipt),
        "original_archive_sha256": archive_hash,
        "derived_accounting_sha256": derived_hashes,
        "limitations": "Operator classified the unfinished running trial using retained service-stop evidence. Its task outcome, final verification, duration and audit remain unassessed. Cleanup was manual after original archival. No trial or generation was rerun.",
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--service-journal", type=Path, required=True)
    parser.add_argument("--cleanup-receipt", type=Path, required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = recover(args.run, args.service_journal, args.cleanup_receipt, args.unit)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (args.output / "REPORT.md").write_text(render(report))
    print(args.output / "REPORT.md")


if __name__ == "__main__":
    main()
