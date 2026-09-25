"""Authored admission/authorization counterexamples, not experiment outcomes."""

import copy
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_broker import Crash, MemoryAdapter
from test_procedures import (
    evidence as authored_evidence,  # noqa: F401 -- shared authored raw-evidence fixture
)

from autonomy_lab import procedures
from autonomy_lab import program_admission as p
from autonomy_lab.broker import ActionBroker, BrokerPolicy, Proposal
from autonomy_lab.experiments import planned_trials, release_manifest, validate_config
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedure import freeze
from autonomy_lab.scoring import score_trial
from autonomy_lab.verifier import evaluate_snapshot, load_expectations

BASELINE = (ROOT / "procedures/bounded-refresh.json").read_bytes()


@pytest.fixture
def program_evidence(request, monkeypatch):
    evidence = request.getfixturevalue("authored_evidence")
    # Reuse the explicitly authored two-case scorer fixture, mapping its positive
    # and negative observations to program identities. No interpreter/cluster
    # execution is asserted by these raw-evidence corruption tests.
    monkeypatch.setattr(p, "calibration_config", procedures.calibration_config)
    monkeypatch.setattr(p, "ADVERSE_FAILURES", {"observer_outage"})
    config = p.configuration(BASELINE)
    declared = {**config, "agent_image_id": "sha256:" + "a" * 64}
    release = release_manifest(declared)
    manifest = json.loads((evidence / "manifest.json").read_text())
    old = json.loads((evidence / "results.json").read_text())
    by_case = {
        (
            r["scenario"],
            {"runbook": "program_adverse", "runbook_fallback": "program", "no_agent": "no_agent"}[
                r["variant"]
            ],
        ): (i, r)
        for i, r in enumerate(old, 1)
    }
    # Copy all source records before the new randomized plan writes any directory.
    records = {
        i: {f.name: f.read_bytes() for f in (evidence / f"trial-{i:03d}").iterdir()}
        for i in range(1, len(old) + 1)
    }
    rows = []
    for index, planned in enumerate(planned_trials(config), 1):
        prior_index, prior = by_case[planned["scenario"], planned["variant"]]
        directory = evidence / f"trial-{index:03d}"
        for file in directory.iterdir():
            file.unlink()
        for name, raw in records[prior_index].items():
            (directory / name).write_bytes(raw)
        trial = json.loads((directory / "trial.json").read_text())
        trial["variant"] = planned["variant"]
        trial["score"]["variant"] = planned["variant"]
        if planned["variant"] == "program_adverse" and planned["scenario"] == "observer_outage":
            verification = json.loads((directory / "final-verification.json").read_text())
            for probe in verification["probes"]:
                probe["observations"]["service"]["resource"]["spec"]["ports"][0]["targetPort"] = (
                    9999
                )
                probe.update(evaluate_snapshot(probe["observations"], load_expectations()))
            verification.update(
                verdict="verified_failure",
                reasons=verification["probes"][0]["reasons"],
                counts={
                    "total": 2,
                    "verified_success": 0,
                    "verified_failure": 2,
                    "indeterminate": 0,
                },
            )
            observations = [
                json.loads(line) for line in (directory / "evidence.jsonl").read_text().splitlines()
            ]
            for observation in observations:
                if observation["source"] == "verify_recovery":
                    observation["payload"] = copy.deepcopy(verification)
            save(directory / "final-verification.json", verification)
            (directory / "evidence.jsonl").write_text(
                "".join(json.dumps(o) + "\n" for o in observations)
            )
            trial["score"] = score_trial(
                "healthy",
                planned["variant"],
                trial["agent"]["terminal"],
                verification,
                [],
                observations,
            )
        save(directory / "trial.json", trial)
        save(
            directory / "worker-request.json",
            {
                "release_id": release["release_id"],
                "config": declared,
                "scenario": planned["scenario"],
                "variant": planned["variant"],
            },
        )
        if planned["variant"] != "no_agent":
            raw = config["procedure_programs"][planned["variant"]].encode()
            save(directory / "program.json", {"at": 1790294400.5, "pin": freeze(raw)})
        rows.append({**planned, **trial})
    save(evidence / "release.json", release)
    save(
        evidence / "manifest.json",
        {**declared, "planned_trials": planned_trials(config), "frozen_at": manifest["frozen_at"]},
    )
    save(evidence / "results.json", rows)
    return evidence


def test_program_calibration_protocol_has_24_trials_and_exact_bytes():
    config = p.configuration(BASELINE)
    validate_config(config)
    assert len(planned_trials(config)) == 24
    assert config["procedure_programs"]["program"].encode() == BASELINE
    assert json.loads(p.ADVERSE)["repairable_routing"] == "escalate"
    assert p.ADVERSE_FAILURES == {"routing", "lost_ack"}


def test_raw_evaluation_rejects_observed_miss_and_binds_exact_program(program_evidence):
    accepted = p.evaluate(program_evidence, BASELINE)
    rejected = p.evaluate(program_evidence, BASELINE, adverse=True)
    assert accepted["eligible"] is True and rejected["eligible"] is False
    assert accepted["definition"]["program"] == freeze(BASELINE)
    assert rejected["definition"]["program"] == freeze(p.ADVERSE)
    assert accepted["version"] != rejected["version"]
    with pytest.raises(procedures.Refused):
        p.evaluate(program_evidence, BASELINE + b" ")


@pytest.mark.parametrize("damage", ["missing", "bytes", "source", "late", "bool_time", "extra_pin"])
def test_program_pin_corruption_cannot_admit(program_evidence, tmp_path, damage):
    path = next(program_evidence.glob("trial-*/program.json"))
    pin = json.loads(path.read_text())
    if damage == "missing":
        path.unlink()
    else:
        if damage == "bytes":
            pin["pin"]["definition"]["program_utf8"] += " "
        elif damage == "source":
            pin["pin"]["definition"]["runtime_files"]["src/autonomy_lab/procedure.py"] = "different"
        elif damage == "late":
            pin["at"] = 9999999999
        elif damage == "bool_time":
            pin["at"] = True
        else:
            pin["pin"]["accepted"] = True
        save(path, pin)
    registry = p.ProgramRegistry(tmp_path / "registry.sqlite")
    with pytest.raises((ValueError, OSError)):
        registry.promote(program_evidence, BASELINE, expected_revision=0)
    assert registry.state() == {"revision": 0, "active": None}


@pytest.fixture
def registry(program_evidence, tmp_path):
    registry = p.ProgramRegistry(tmp_path / "registry.sqlite")
    assert registry.promote(program_evidence, BASELINE, expected_revision=0)["kind"] == "promoted"
    return registry


def proposal(operation_id="operation-1"):
    return Proposal(
        run_id="run-1",
        operation_id=operation_id,
        namespace="lab-test",
        service_name="inventory",
        service_uid="service-uid",
        resource_version="10",
        expected_target_port=9999,
        target_port=8080,
        evidence_ids=["o-1"],
    )


def rows(registry, table):
    with closing(sqlite3.connect(registry.path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM " + table)]


def test_withdrawal_blocks_new_authorization_in_existing_episode(registry):
    pin = registry.start_episode("episode-1")
    first = registry.authorize(pin, proposal(), BASELINE)
    assert first["decision_revision"] == first["activation_revision"] == 1
    registry.withdraw(expected_revision=1)
    with pytest.raises(procedures.Refused, match="no longer active"):
        registry.authorize(pin, proposal("operation-2"), BASELINE)
    assert registry.authorization(pin, proposal()) == first
    assert len(rows(registry, "authorizations")) == 1
    assert rows(registry, "refusals")[-1]["action"] == "authorize_dispatch"
    with pytest.raises(procedures.Refused):
        registry.start_episode("episode-2")


@pytest.mark.parametrize(
    "defect",
    ["episode", "revision", "bool_revision", "program_version", "version", "bytes", "extra"],
)
def test_changed_pin_or_program_cannot_authorize(registry, defect):
    pin = registry.start_episode("episode-1")
    raw = BASELINE
    if defect == "bytes":
        raw += b" "
    elif defect == "bool_revision":
        pin["revision"] = True
    elif defect == "extra":
        pin["permission"] = True
    else:
        pin[defect] = "different"
    with pytest.raises(ValueError):
        registry.authorize(pin, proposal(), raw)
    assert rows(registry, "authorizations") == []


def test_repeated_authorization_and_changed_request_are_refused(registry):
    pin = registry.start_episode("episode-1")
    registry.authorize(pin, proposal(), BASELINE)
    for request in [proposal(), proposal().model_copy(update={"resource_version": "11"})]:
        with pytest.raises(procedures.Refused):
            registry.authorize(pin, request, BASELINE)
    with pytest.raises(procedures.Refused):
        registry.authorization(pin, proposal().model_copy(update={"resource_version": "11"}))


def test_concurrent_authorization_and_withdrawal_have_one_ledger_order(registry):
    pin = registry.start_episode("episode-1")
    barrier = threading.Barrier(2)

    def authorize():
        barrier.wait()
        try:
            return registry.authorize(pin, proposal(), BASELINE)
        except procedures.Refused:
            return None

    def withdraw():
        barrier.wait()
        return registry.withdraw(expected_revision=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(authorize)
        w = pool.submit(withdraw)
        result = a.result()
        withdrawn = w.result()
    assert withdrawn["revision"] == 2 and registry.state()["active"] is None
    assert len(rows(registry, "authorizations")) == (result is not None)
    if result:
        assert result["decision_revision"] == 1
    with pytest.raises(procedures.Refused):
        registry.authorize(pin, proposal("later"), BASELINE)


def broker_for(tmp_path, registry, pin, adapter, callback=None):
    def authorize(request):
        try:
            registry.authorize(pin, request, BASELINE)
        except procedures.Refused as error:
            raise PermissionError("refused") from error
        if callback:
            callback()

    policy = BrokerPolicy("run-1", "lab-test", "inventory", "service-uid", max_dispatches=2)
    return ActionBroker(tmp_path / "broker.sqlite", policy, adapter, authorize_dispatch=authorize)


def test_broker_refuses_unsent_operation_and_releases_only_its_reservation(registry, tmp_path):
    pin = registry.start_episode("episode-1")
    adapter = MemoryAdapter()
    broker = broker_for(tmp_path, registry, pin, adapter)
    registry.withdraw(expected_revision=1)
    result = broker.propose(proposal())
    assert result["status"] == "rejected" and result["reason"] == "dispatch_authorization_refused"
    assert (
        result["budget_used"] == 0 and not result["budget_reserved"] and adapter.patch_calls == []
    )
    assert [r["event"] for r in broker.events("operation-1")] == [
        "prepared",
        "rejected",
        "budget_released",
    ]


def test_authorized_inflight_request_may_complete_after_withdrawal(registry, tmp_path):
    pin = registry.start_episode("episode-1")
    adapter = MemoryAdapter()
    broker = broker_for(
        tmp_path, registry, pin, adapter, lambda: registry.withdraw(expected_revision=1)
    )
    assert broker.propose(proposal())["status"] == "acknowledged"
    assert len(adapter.patch_calls) == 1 and registry.state()["active"] is None
    assert len(rows(registry, "authorizations")) == 1


def test_crash_after_authorization_leaves_original_reserved_intent(registry, tmp_path):
    pin = registry.start_episode("episode-1")
    adapter = MemoryAdapter()

    def crash():
        raise Crash()

    broker = broker_for(tmp_path, registry, pin, adapter, crash)
    with pytest.raises(Crash):
        broker.propose(proposal())
    old = broker.lookup("operation-1")
    assert old["status"] == "prepared" and old["budget_used"] == 1 and adapter.patch_calls == []
    assert len(rows(registry, "authorizations")) == 1
    registry.withdraw(expected_revision=1)
    assert broker.reconcile("operation-1")["status"] == "prepared"
    assert adapter.patch_calls == []


def test_authorization_storage_failure_never_calls_adapter(tmp_path):
    adapter = MemoryAdapter()

    def fail(request):
        raise OSError("authored unavailable storage")

    broker = ActionBroker(
        tmp_path / "broker.sqlite",
        BrokerPolicy("run-1", "lab-test", "inventory", "service-uid"),
        adapter,
        authorize_dispatch=fail,
    )
    result = broker.propose(proposal())
    assert (
        result["status"] == "rejected" and result["reason"] == "dispatch_authorization_unavailable"
    )
    assert not result["budget_reserved"] and adapter.patch_calls == []


@pytest.mark.parametrize("defect", ["eligible", "wrong_failed_case", "unexpected_environment"])
def test_promotion_itself_requires_discriminating_control(
    program_evidence, tmp_path, monkeypatch, defect
):
    original = p.evaluate_evidence

    def changed(*args, **kwargs):
        receipt = original(*args, **kwargs)
        if args[1] == "program_adverse":
            if defect == "eligible":
                receipt["eligible"] = True
            elif defect == "wrong_failed_case":
                next(o for o in receipt["outcomes"] if not o["task_success"])["scenario"] = "other"
            else:
                for outcome in receipt["outcomes"]:
                    outcome["environment_matches"] = True
        return receipt

    monkeypatch.setattr(p, "evaluate_evidence", changed)
    registry = p.ProgramRegistry(tmp_path / "direct.sqlite")
    with pytest.raises(procedures.Refused, match="discriminate"):
        registry.promote(program_evidence, BASELINE, expected_revision=0)
    assert registry.state() == {"revision": 0, "active": None}


def test_rejected_candidate_does_not_relabel_active_pin(registry, program_evidence):
    pin = registry.start_episode("existing")
    assert (
        registry.promote(program_evidence, BASELINE, expected_revision=1, adverse=True)["kind"]
        == "rejected"
    )
    authorization = registry.authorize(pin, proposal(), BASELINE)
    assert authorization["activation_revision"] == 1 and authorization["decision_revision"] == 2


def test_reactivation_requires_fresh_episode_authorization(registry, program_evidence):
    pin = registry.start_episode("old")
    registry.promote(program_evidence, BASELINE, expected_revision=1)
    with pytest.raises(procedures.Refused, match="no longer active"):
        registry.authorize(pin, proposal(), BASELINE)
    fresh = registry.start_episode("new")
    assert registry.authorize(fresh, proposal(), BASELINE)["activation_revision"] == 2


def test_same_operation_racing_broker_calls_authorizes_once(registry, tmp_path):
    pin = registry.start_episode("episode-1")
    adapter = MemoryAdapter()
    broker = broker_for(tmp_path, registry, pin, adapter)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: broker.propose(proposal()), range(2)))
    assert all(r["status"] in {"prepared", "dispatching", "acknowledged"} for r in results)
    assert broker.lookup("operation-1")["status"] == "acknowledged"
    assert len(adapter.patch_calls) == len(rows(registry, "authorizations")) == 1


def test_withdrawn_version_cannot_be_repromoted(registry, program_evidence):
    registry.withdraw(expected_revision=1)
    with pytest.raises(procedures.Refused, match="withdrawn"):
        registry.promote(program_evidence, BASELINE, expected_revision=2)
    assert registry.state() == {"revision": 2, "active": None}


def test_only_fresh_program_start_can_create_execution_pin(registry):
    with pytest.raises(procedures.Refused, match="must be started"):
        registry.pin("diagnostic")
    with pytest.raises(procedures.Refused, match="not a known procedure"):
        procedures.Registry(registry.path).pin("wrong-registry")
    assert rows(registry, "pins") == []
    selected = registry.start_episode("episode-1")
    assert registry.pin("episode-1") == {k: selected[k] for k in ["episode", "version", "revision"]}
    with pytest.raises(procedures.Refused, match="cannot be resumed"):
        registry.start_episode("episode-1")


@pytest.mark.parametrize("refusal_unavailable", [False, True])
def test_adapter_known_unsent_guard_is_not_transport_uncertainty(tmp_path, refusal_unavailable):
    from autonomy_lab.broker import DispatchNotSent

    adapter = MemoryAdapter()

    def fail(*args):
        raise DispatchNotSent(refusal_unavailable=refusal_unavailable)

    adapter.patch_service = fail
    broker = ActionBroker(
        tmp_path / "broker.sqlite",
        BrokerPolicy("run-1", "lab-test", "inventory", "service-uid"),
        adapter,
    )
    result = broker.propose(proposal())
    assert result["status"] == "rejected" and result["reason"] == (
        "dispatch_not_sent_refusal_unavailable" if refusal_unavailable else "dispatch_not_sent"
    )
    assert (
        result["budget_used"] == 1
        and result["budget_reserved"] is True
        and adapter.patch_calls == []
    )
    assert not result.get("reconciliation")


def test_explicit_adverse_mode_records_control_bytes_and_calibration_context(
    registry, program_evidence
):
    decision = registry.promote(program_evidence, BASELINE, expected_revision=1, adverse=True)
    receipt = json.loads(rows(registry, "decisions")[-1]["receipt"])
    assert decision["kind"] == "rejected" and receipt["definition"]["program"] == freeze(p.ADVERSE)
    assert receipt["definition"]["config"]["procedure_programs"]["program"].encode() == BASELINE
    assert receipt["definition"]["variant"] == "program_adverse"


@pytest.mark.parametrize(
    "defect", ["none", "episode_pin", "binding_save", "authorization_read", "refusal_storage"]
)
def test_campaign_real_broker_enforces_pretransport_program_guards(
    registry, tmp_path, monkeypatch, defect
):
    import time
    from types import SimpleNamespace

    from autonomy_lab import campaign as c

    directory = tmp_path / "campaign"
    workspace = directory / "workers/operator-authored"
    workspace.mkdir(parents=True)
    contract = c.Contract.model_validate(
        json.loads((ROOT / "scenarios/campaign-admitted-program.json").read_text())
    ).model_copy(update={"test_pause_before_dispatch": False})
    save(directory / "program-definition.json", freeze(BASELINE))
    save(directory / "owner.json", {"run_id": "run-1"})
    save(directory / "identities-before.json", {"Service/inventory": "service-uid"})
    save(directory / "window.json", {"start": time.time() - 1, "end": time.time() + 100})
    adapter = MemoryAdapter()
    results = []
    monkeypatch.setattr(c, "Kubernetes", lambda *args: adapter)
    monkeypatch.setattr(c, "ProgramRegistry", lambda *args: registry)
    monkeypatch.setattr(c, "active", lambda *args: None)
    if defect in {"authorization_read", "refusal_storage"}:

        def refuse(*args):
            raise procedures.Refused("Authored changed authorization")

        monkeypatch.setattr(registry, "authorization", refuse)
    if defect == "refusal_storage":

        def unavailable(*args):
            raise OSError("Authored unavailable refusal storage")

        monkeypatch.setattr(registry, "record_dispatch_refusal", unavailable)
    if defect == "binding_save":
        original = c.save

        def saving(path, value):
            if path.name.startswith("operation-"):
                raise OSError("Authored binding failure")
            original(path, value)

        monkeypatch.setattr(c, "save", saving)

    def execute(tools, raw, *, pin):
        if defect == "episode_pin":
            save(tools.path.parent / "program.json", {"at": time.time(), "pin": {}})
        results.append(tools.broker.propose(proposal()))
        return {"outcome": "escalated", "reason": "Authored integration boundary test"}

    monkeypatch.setattr(c, "run_program", execute)
    c.operator(
        directory,
        workspace,
        contract,
        SimpleNamespace(namespace="lab-test", cluster_name="authored"),
        {"quote_url": "http://127.0.0.1:1", "inventory_control_url": "http://127.0.0.1:2"},
    )
    result = results[0]
    if defect == "none":
        assert result["status"] == "acknowledged" and len(adapter.patch_calls) == 1
        assert len(rows(registry, "authorizations")) == 1 and rows(registry, "refusals") == []
    else:
        assert adapter.patch_calls == [] and result["status"] == "rejected"
        assert result["reason"] == (
            "dispatch_authorization_refused"
            if defect == "episode_pin"
            else "dispatch_not_sent_refusal_unavailable"
            if defect == "refusal_storage"
            else "dispatch_not_sent"
        )
        assert result["budget_used"] == int(defect != "episode_pin")
        assert len(rows(registry, "authorizations")) == int(defect != "episode_pin")
        assert len(rows(registry, "refusals")) == int(defect != "refusal_storage")
