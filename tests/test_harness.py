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
