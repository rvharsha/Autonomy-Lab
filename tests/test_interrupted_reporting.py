"""Adversarial offline-recovery fixtures, never measured experiment outcomes."""

import importlib.util
import json
import sys

import pytest
from test_value_reporting import SCRIPTS, fixture_run, reporter, write

sys.modules.setdefault("report_agent_value", reporter)
spec = importlib.util.spec_from_file_location("recover_interrupted_report", SCRIPTS / "recover_interrupted_report.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


@pytest.fixture
def interrupted(tmp_path):
    run = tmp_path / "experiment-example"
    run.mkdir()
    fixture_run(run, "runbook-fallback-comparison")
    for name in ("accounting.json", "cleanup.json"):
        (run / name).unlink()
    item = json.loads((run / "manifest.json").read_text())["planned_trials"][3]
    trial = run / "trial-004"
    trial.mkdir()
    write(trial / "trial.json", {**item, "status": "running", "agent": None,
                                "started_at": "2026-09-24T06:40:00+00:00", "private": "PRIVATE_PAYLOAD"})
    (trial / "evidence.jsonl").write_text('{"source":')
    journal = tmp_path / "journal.jsonl"
    journal.write_text(json.dumps({"SYSLOG_IDENTIFIER": "systemd", "MESSAGE": "Stopping autolab-example.service - PRIVATE_LOG",
                                   "__REALTIME_TIMESTAMP": "1790232087744285"}) + "\n")
    cleanup = tmp_path / "cleanup.json"
    write(cleanup, {"run_id": run.name, "status": "deleted",
                    "method": "manual_invocation_of_owned_resource_janitor_after_archival",
                    "original_archive_sha256": "f" * 64,
                    "finished_at": "2026-09-24T06:48:00+00:00", "private": "PRIVATE_RECEIPT"})
    return run, journal, cleanup, "autolab-example.service"


def test_interrupted_trial_is_retained_unknown_without_modifying_sources(interrupted):
    run, *_ = interrupted
    before = {str(p): p.read_bytes() for p in run.rglob("*") if p.is_file()}
    report = recovery.recover(*interrupted)
    assert report == recovery.recover(*interrupted)
    assert report["planned"] == 80 and report["recorded"] == 4 and len(report["unrun"]) == 76
    row = report["trials"][-1]
    assert row["status"] == "interrupted" and row["status_source"] == "operator_recovery_from_service_stop"
    for key in ("task_success", "elapsed_seconds", "protected_state_damage", "actor_verification_verdicts",
                "final_verification_verdict", "unmatched_successful_mutations", "external_tool_calls"):
        assert row[key] is None
    assert not row["audit_assessed"]
    assert row["original_trial_sha256"] == recovery.digest(run / "trial-004/trial.json")
    assert report["evidence_sha256"]["results.json"] == recovery.digest(run / "results.json")
    assert set(report["recovery"]["derived_accounting_sha256"]) == {"results.json", "accounting.json", "cleanup.json"}
    assert "Operator-recovered accounting" in reporter.render(report)
    assert "PRIVATE" not in json.dumps(report) + reporter.render(report)
    assert before == {str(p): p.read_bytes() for p in run.rglob("*") if p.is_file()}


@pytest.mark.parametrize("case", ["finalized", "wrong_plan", "wrong_repetition", "boolean_repetition", "scored_partial", "later_trial", "wrong_service", "early_stop", "wrong_cleanup", "early_cleanup"])
def test_recovery_rejects_ambiguous_or_contradictory_evidence(interrupted, case):
    run, journal, cleanup, unit = interrupted
    partial = run / "trial-004/trial.json"
    if case == "finalized":
        write(run / "accounting.json", {})
    elif case in {"wrong_plan", "wrong_repetition", "boolean_repetition", "scored_partial"}:
        row = json.loads(partial.read_text())
        row.update({"wrong_plan": {"scenario": "healthy"}, "wrong_repetition": {"repetition": 0},
                    "boolean_repetition": {"repetition": True}, "scored_partial": {"score": {"task_success": True}}}[case])
        write(partial, row)
    elif case == "later_trial":
        (run / "trial-005").mkdir()
    elif case == "wrong_service":
        unit = "autolab-other.service"
    elif case == "early_stop":
        row = json.loads(journal.read_text())
        row["__REALTIME_TIMESTAMP"] = "1"
        journal.write_text(json.dumps(row) + "\n")
    else:
        row = json.loads(cleanup.read_text())
        row.update({"run_id": "other"} if case == "wrong_cleanup" else {"finished_at": "2020-01-01T00:00:00Z"})
        write(cleanup, row)
    with pytest.raises(ValueError):
        recovery.recover(run, journal, cleanup, unit)


def test_worker_missing_repetition_is_explicitly_bound_to_ordered_plan(interrupted):
    run, *_ = interrupted
    path = run / "trial-004/trial.json"
    row = json.loads(path.read_text())
    del row["repetition"]
    write(path, row)
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["planned_trials"][3]["score"] = {"task_success": True}
    manifest["planned_trials"][4]["private_metadata"] = "PRIVATE_PLAN_METADATA"
    write(run / "manifest.json", manifest)
    report = recovery.recover(*interrupted)
    assert report["trials"][-1]["repetition"] == 1
    assert report["trials"][-1]["task_success"] is None
    assert report["recovery"]["partial_repetition_source"] == "ordered_manifest_position"
    assert "PRIVATE_PLAN_METADATA" not in json.dumps(report)


def test_unrelated_binary_journal_messages_and_blank_lines_do_not_hide_stop(interrupted):
    _, journal, *_ = interrupted
    with journal.open("a") as stream:
        stream.write('\n' + json.dumps({"SYSLOG_IDENTIFIER": "systemd", "MESSAGE": [255, 0, 1]}) + '\n')
    assert recovery.recover(*interrupted)["trials"][-1]["status"] == "interrupted"


def test_nonobject_journal_record_fails_closed(interrupted):
    _, journal, *_ = interrupted
    with journal.open("a") as stream:
        stream.write('[]\n')
    with pytest.raises(ValueError, match="Invalid journal record"):
        recovery.recover(*interrupted)
