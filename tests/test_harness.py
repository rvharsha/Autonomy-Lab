"""Focused harness failure tests; cluster acceptance is exercised by the demo CLI."""

import json
import os
import sqlite3
import sys
import time

import pytest

from autonomy_lab import harness
from autonomy_lab.broker import ActionBroker, BrokerPolicy, Proposal
from autonomy_lab.harness import kill_at_barrier, save, write_report


def test_ci_verification_summary_keeps_failure_timing_without_raw_bodies():
    result = {
        "reasons": ["available-single: HTTP status differs"],
        "counts": {"total": 2, "verified_failure": 1, "verified_success": 1},
        "probes": [
            {"index": 0, "offset_seconds": 0.0, "elapsed_seconds": 0.1,
             "verdict": "verified_failure", "reasons": ["available-single: HTTP status differs"],
             "observations": {"body": "private diagnostic payload"}},
            {"index": 1, "offset_seconds": 1.0, "elapsed_seconds": 0.1,
             "verdict": "verified_success", "reasons": [], "observations": {}},
        ],
    }
    summary = harness.verification_summary(result)
    assert summary["counts"] == result["counts"]
    assert [p["verdict"] for p in summary["probes"]] == ["verified_failure", "verified_success"]
    assert summary["probes"][0]["offset_seconds"] == 0.0
    assert "observations" not in json.dumps(summary)
    assert "private diagnostic" not in json.dumps(summary)


def test_recovery_readiness_retains_early_failure_and_requires_later_success(tmp_path, monkeypatch):
    results = iter([
        {"verdict": "verified_failure", "reasons": ["quote available-single: HTTP 503 (expected 200)"], "counts": {}, "probes": []},
        {"verdict": "verified_success", "reasons": [], "counts": {}, "probes": []},
    ])
    monkeypatch.setattr(harness, "check", lambda *args, **kwargs: next(results))
    report = {}
    harness.establish_recovery(None, None, tmp_path, "final-recovery", report)
    assert report["status"] == "ready"
    assert [item["verdict"] for item in report["checks"]] == ["verified_failure", "verified_success"]
    assert json.loads((tmp_path / "final-recovery-readiness-1.json").read_text())["verdict"] == "verified_failure"


@pytest.mark.parametrize("verdict, reason", [
    ("verified_failure", "protected product rows changed"),
    ("verified_failure", "quote available-single: body differs"),
    ("indeterminate", "measurement unavailable"),
])
def test_readiness_cannot_wait_away_other_failures(tmp_path, monkeypatch, verdict, reason):
    calls = []

    def check(*args, **kwargs):
        calls.append(1)
        return {"verdict": verdict, "reasons": [reason], "counts": {}, "probes": []}

    monkeypatch.setattr(harness, "check", check)
    with pytest.raises(AssertionError, match="non-routing readiness failure"):
        harness.establish_recovery(None, None, tmp_path, "final-recovery", {})
    assert len(calls) == 1


def test_readiness_success_after_deadline_is_not_accepted(tmp_path, monkeypatch):
    times = iter([0, 0, 2, 2])
    monkeypatch.setattr(harness, "check", lambda *args, **kwargs: {
        "verdict": "verified_success", "reasons": [], "counts": {}, "probes": [],
    })
    report = {}
    with pytest.raises(TimeoutError, match="readiness exceeded"):
        harness.establish_recovery(None, None, tmp_path, "final-recovery", report,
                                   timeout_seconds=1, clock=lambda: next(times))
    assert report["status"] == "failed"


def test_real_sigkill_preserves_unsent_intent_and_revocation(tmp_path):
    proposal = Proposal(
        run_id="1234abcd",
        operation_id="kill-before-send",
        namespace="autonomy-lab",
        service_name="inventory",
        service_uid="unit-test-uid",
        resource_version="1",
        expected_target_port=8081,
        target_port=8080,
        evidence_ids=["unit-test-observation"],
    )
    journal = tmp_path / "broker.sqlite"
    settings = tmp_path / "worker.json"
    save(
        settings,
        {
            "stage": "after_intent",
            "proposal": proposal.model_dump(),
            "journal_path": str(journal),
            # This barrier is before any Kubernetes access. No cluster result is claimed.
            "kubeconfig": str(tmp_path / "unused-kubeconfig"),
            "cluster_name": "autolab-1234abcd",
        },
    )
    result = kill_at_barrier(
        [sys.executable, "-m", "autonomy_lab.crash_worker", str(settings)],
        "after_intent",
        proposal.operation_id,
        tmp_path / "worker.stderr.log",
    )
    assert result["exit_code"] == -9
    with sqlite3.connect(journal) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT status,budget_reserved FROM operations").fetchone() == (
            "prepared",
            1,
        )

    class NoInfrastructureAccess:
        def get_service(self, *_args):
            raise AssertionError("revoked authority must not read infrastructure")

        def patch_service(self, *_args):
            raise AssertionError("revoked authority must not mutate infrastructure")

    broker = ActionBroker(
        journal,
        BrokerPolicy("1234abcd", "autonomy-lab", "inventory", "unit-test-uid", enabled=False),
        NoInfrastructureAccess(),
    )
    resumed = broker.resume_prepared(proposal.operation_id)
    assert resumed["status"] == "rejected"
    assert resumed["reason"] == "policy_disabled"
    assert resumed["budget_used"] == 0
    assert [event["event"] for event in broker.events(proposal.operation_id)] == [
        "prepared",
        "rejected",
        "budget_released",
    ]


def test_wrong_barrier_is_rejected_and_child_is_terminated(tmp_path):
    pid_path = tmp_path / "child.pid"
    code = (
        "import json,os,signal; from pathlib import Path; "
        f"Path({str(pid_path)!r}).write_text(str(os.getpid())); "
        "print(json.dumps({'stage':'after_intent','operation_id':'wrong','pid':os.getpid()}),flush=True); "
        "signal.pause()"
    )
    with pytest.raises(RuntimeError, match="unexpected barrier"):
        kill_at_barrier(
            [sys.executable, "-c", code], "after_intent", "expected", tmp_path / "child.stderr.log"
        )
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


def test_partial_barrier_cannot_block_deadline_and_child_is_terminated(tmp_path):
    pid_path = tmp_path / "child.pid"
    code = (
        "import os,signal; from pathlib import Path; "
        f"Path({str(pid_path)!r}).write_text(str(os.getpid())); "
        "os.write(1,b'{\"stage\":'); signal.pause()"
    )
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="did not reach"):
        kill_at_barrier(
            [sys.executable, "-c", code], "after_intent", "expected",
            tmp_path / "child.stderr.log", timeout_seconds=1,
        )
    assert time.monotonic() - started < 5
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


def test_journal_export_failure_does_not_replace_primary_failure(tmp_path, monkeypatch):
    (tmp_path / "broker-corrupt.sqlite").write_bytes(b"not a sqlite journal")
    monkeypatch.setattr(harness, "service_identity", lambda *_args: object())

    class FailedSetup:
        def set_target_port(self, _port):
            raise AssertionError("primary acceptance failure")

    results = []
    with pytest.raises(AssertionError, match="primary acceptance failure"):
        harness.broker_acceptance(FailedSetup(), tmp_path, "unit-run", results=results)
    errors = json.loads((tmp_path / "broker-event-export-errors.json").read_text())
    assert errors == [{"journal": "broker-corrupt.sqlite", "error_type": "DatabaseError"}]
    assert results[-1]["name"] == "broker journal event export"
    assert not results[-1]["passed"]


def test_missing_operation_records_named_sigkill_failure(tmp_path, monkeypatch):
    proposal = Proposal(
        run_id="unit-run", operation_id="sigkill-after_intent", namespace="autonomy-lab",
        service_name="inventory", service_uid="unit-service", resource_version="1",
        expected_target_port=8081, target_port=8080, evidence_ids=["unit-observation"],
    )

    class UnitInfrastructure:
        namespace = "autonomy-lab"
        kubeconfig = tmp_path / "unused-kubeconfig"
        cluster_name = "unused-unit-cluster"

        def set_target_port(self, port):
            assert port == 8081

    def empty_journal_worker(command, stage, operation_id, _log_path):
        # Unit injection of a missing committed row; this is not a real process-kill claim.
        settings = json.loads(harness.Path(command[-1]).read_text())
        with sqlite3.connect(settings["journal_path"]) as db:
            db.execute("CREATE TABLE operations(operation_id TEXT,status TEXT)")
        return {"barrier": {"stage": stage, "operation_id": operation_id}, "exit_code": -9}

    monkeypatch.setattr(harness, "proposal_for", lambda *_args, **_kwargs: proposal)
    monkeypatch.setattr(harness, "kill_at_barrier", empty_journal_worker)
    records = []

    def record(name, passed, **evidence):
        records.append({"name": name, "passed": passed, **evidence})
        if not passed:
            raise AssertionError(name)

    kube = UnitInfrastructure()
    with pytest.raises(AssertionError, match="SIGKILL after_intent"):
        harness.sigkill_acceptance(kube, kube, tmp_path, "unit-run", record)
    assert len(records) == 1
    assert records[0]["reason"] == "operation_record_missing"
    assert records[0]["persisted_status"] is None
    assert records[0]["saved_operation"]["status"] is None
    assert records[0]["journal_integrity"] == "ok"


def test_report_surfaces_partial_broker_failure_and_cleanup_failure(tmp_path):
    summary = {
        "run_id": "unit-report",
        "status": "failed",
        "phases": [],
        "broker_checks": [
            {"name": "earlier check", "passed": True},
            {"name": "interrupted check", "passed": False},
        ],
        "error": "Broker acceptance failed: interrupted check",
        "cleanup": {"status": "failed"},
        "cleanup_error": "cluster removal failed",
    }
    write_report(tmp_path, summary)
    report = (tmp_path / "REPORT.md").read_text()
    assert "| interrupted check | enforced | failed | False |" in report
    assert "Failure: Broker acceptance failed: interrupted check" in report
    assert "Cleanup failure: cluster removal failed" in report
    assert "Environment cleanup: **failed**" in report


def test_journal_export_closes_connection_on_primary_failure(tmp_path, monkeypatch):
    journal = tmp_path / "broker-export.sqlite"
    connection = sqlite3.connect(journal)
    connection.execute("CREATE TABLE operation_events(sequence INTEGER)")
    connection.close()
    opened = []
    connect = sqlite3.connect

    def capture(*args, **kwargs):
        db = connect(*args, **kwargs)
        opened.append(db)
        return db

    monkeypatch.setattr(harness.sqlite3, "connect", capture)
    monkeypatch.setattr(harness, "service_identity", lambda *_args: object())

    class FailedSetup:
        def set_target_port(self, _port):
            raise AssertionError("primary acceptance failure")

    with pytest.raises(AssertionError, match="primary acceptance failure"):
        harness.broker_acceptance(FailedSetup(), tmp_path, "unit-run")
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def test_save_publish_failure_preserves_previous_complete_record(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    save(path, {"status": "before"})
    before = path.read_bytes()

    def failed_publish(*_args):
        raise OSError("injected replacement failure")

    monkeypatch.setattr(harness.os, "replace", failed_publish)
    with pytest.raises(OSError, match="injected replacement failure"):
        save(path, {"status": "after"})
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("journal_contents", [None, b"corrupt sqlite bytes"])
def test_unreadable_crash_journal_records_failure_without_creating_or_rewriting(tmp_path, monkeypatch, journal_contents):
    journal = tmp_path / "broker-sigkill-after_intent.sqlite"
    if journal_contents is not None:
        journal.write_bytes(journal_contents)
    proposal = Proposal(
        run_id="unit-run", operation_id="sigkill-after_intent", namespace="autonomy-lab",
        service_name="inventory", service_uid="unit-service", resource_version="1",
        expected_target_port=8081, target_port=8080, evidence_ids=["unit-observation"],
    )

    class UnitInfrastructure:
        kubeconfig = tmp_path / "unused-kubeconfig"
        cluster_name = "unused-unit-cluster"

        def set_target_port(self, _port):
            pass

    # Authored protocol-failure boundary, not a real child-process result.
    monkeypatch.setattr(harness, "proposal_for", lambda *_args, **_kwargs: proposal)
    monkeypatch.setattr(harness, "kill_at_barrier", lambda *_args: {"exit_code": -9})
    records = []

    def record(name, passed, **evidence):
        records.append({"name": name, "passed": passed, **evidence})
        raise AssertionError(name)

    kube = UnitInfrastructure()
    with pytest.raises(AssertionError, match="SIGKILL after_intent"):
        harness.sigkill_acceptance(kube, kube, tmp_path, "unit-run", record)
    assert records[0]["passed"] is False
    assert records[0]["reason"] == "journal_unreadable"
    assert (journal.read_bytes() if journal.exists() else None) == journal_contents
