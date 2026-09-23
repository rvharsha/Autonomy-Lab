"""Broker unit tests. The adapter here is a test double, not cluster evidence."""

from __future__ import annotations

import copy
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from autonomy_lab.broker import (
    ActionBroker,
    BrokerPolicy,
    OperationConflict,
    PatchRejected,
    Proposal,
)


class Crash(BaseException):
    """Simulate abrupt termination without running broker exception handling."""


class MemoryAdapter:
    def __init__(self):
        self.service = {
            "metadata": {
                "namespace": "lab-test", "name": "inventory", "uid": "service-uid",
                "resourceVersion": "10",
            },
            "spec": {
                "ports": [
                    {"name": "metrics", "port": 9090, "targetPort": 9090},
                    {"name": "http", "port": 80, "targetPort": 9999},
                ]
            },
        }
        self.patch_calls = []
        self.read_calls = 0
        self.lock = threading.Lock()
        self.before_patch = None
        self.lose_ack = False
        self.read_unavailable = False

    def get_service(self, namespace, name):
        self.read_calls += 1
        if self.read_unavailable:
            raise ConnectionError("test-only read failure")
        assert (namespace, name) == ("lab-test", "inventory")
        with self.lock:
            return copy.deepcopy(self.service)

    def patch_service(self, namespace, name, patch):
        assert (namespace, name) == ("lab-test", "inventory")
        with self.lock:
            self.patch_calls.append(copy.deepcopy(patch))
            if self.before_patch:
                self.before_patch(self.service)
            candidate = copy.deepcopy(self.service)
            for operation in patch:
                path = operation["path"].split("/")[1:]
                parent = candidate
                for part in path[:-1]:
                    parent = parent[int(part)] if isinstance(parent, list) else parent[part]
                key = int(path[-1]) if isinstance(parent, list) else path[-1]
                if operation["op"] == "test":
                    if parent[key] != operation["value"]:
                        raise PatchRejected()
                elif operation["op"] == "replace":
                    parent[key] = operation["value"]
                else:
                    raise AssertionError("broker constructed unexpected patch operation")
            candidate["metadata"]["resourceVersion"] = str(
                int(candidate["metadata"]["resourceVersion"]) + 1
            )
            self.service = candidate
            if self.lose_ack:
                raise TimeoutError("test-only lost acknowledgement")
            return copy.deepcopy(candidate)


@pytest.fixture
def policy():
    return BrokerPolicy(
        run_id="run-1", namespace="lab-test", service_name="inventory", service_uid="service-uid"
    )


@pytest.fixture
def proposal():
    return Proposal(
        run_id="run-1", operation_id="operation-1", namespace="lab-test", service_name="inventory",
        service_uid="service-uid", resource_version="10", expected_target_port=9999,
        target_port=8080, evidence_ids=["observation-1", "observation-2"],
    )


@pytest.fixture
def adapter():
    return MemoryAdapter()


@pytest.fixture
def broker(tmp_path, policy, adapter):
    return ActionBroker(tmp_path / "broker.sqlite", policy, adapter)


def test_repair_conditions_only_designated_named_port_and_records_ack(broker, proposal, adapter):
    result = broker.propose(proposal)
    assert result["status"] == "acknowledged"
    assert result["reason"] == "api_acknowledged"
    assert result["result"] == {"service_uid": "service-uid", "resource_version": "11"}
    assert result["budget_used"] == 1
    assert adapter.service["spec"]["ports"] == [
        {"name": "metrics", "port": 9090, "targetPort": 9090},
        {"name": "http", "port": 80, "targetPort": 8080},
    ]
    assert adapter.patch_calls == [[
        {"op": "test", "path": "/metadata/uid", "value": "service-uid"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "10"},
        {"op": "test", "path": "/spec/ports/1/name", "value": "http"},
        {"op": "test", "path": "/spec/ports/1/targetPort", "value": 9999},
        {"op": "replace", "path": "/spec/ports/1/targetPort", "value": 8080},
    ]]
    assert [e["event"] for e in broker.events(proposal.operation_id)] == [
        "prepared", "dispatching", "acknowledged"
    ]


@pytest.mark.parametrize("changes", [
    {"patch": []}, {"target_port": "8080"}, {"target_port": True}, {"target_port": 65536},
    {"expected_target_port": 0}, {"evidence_ids": []}, {"evidence_ids": [""]},
    {"resource_version": ""},
])
def test_invalid_proposal_cannot_read_or_mutate(broker, proposal, adapter, changes):
    with pytest.raises(ValidationError):
        broker.propose({**proposal.model_dump(), **changes})
    assert adapter.patch_calls == []
    assert adapter.read_calls == 0


def test_proposal_instances_are_revalidated_at_boundary(broker, proposal, adapter):
    unchecked = proposal.model_copy(update={"evidence_ids": []})
    with pytest.raises(ValidationError):
        broker.propose(unchecked)
    assert adapter.patch_calls == []


@pytest.mark.parametrize("field,value", [
    ("run_id", "other-run"), ("namespace", "production"), ("service_name", "postgres"),
    ("service_uid", "other-uid"), ("port_name", "metrics"), ("target_port", 22),
])
def test_out_of_policy_request_rejected_and_reconcile_respects_read_scope(
    broker, proposal, adapter, field, value
):
    result = broker.propose({**proposal.model_dump(), field: value})
    assert result["status"] == "rejected"
    assert not result["budget_reserved"]
    assert adapter.read_calls == 0
    assert adapter.patch_calls == []
    broker.reconcile(proposal.operation_id)
    if field != "target_port":
        assert adapter.read_calls == 0
    assert adapter.patch_calls == []


def test_noop_is_rejected(broker, proposal, adapter):
    result = broker.propose({**proposal.model_dump(), "expected_target_port": 8080})
    assert result["reason"] == "no_change"
    assert adapter.patch_calls == []


def test_duplicate_returns_original_and_changed_content_conflicts(broker, proposal, adapter):
    first = broker.propose(proposal)
    duplicate = broker.propose(proposal)
    assert duplicate == first
    with pytest.raises(OperationConflict):
        broker.propose({**proposal.model_dump(), "evidence_ids": ["new-evidence"]})
    assert len(adapter.patch_calls) == 1


def test_budget_persists_across_reopen(broker, proposal, policy, adapter):
    broker.propose(proposal)
    restarted = ActionBroker(broker.journal_path, policy, adapter)
    assert restarted.lookup(proposal.operation_id)["status"] == "acknowledged"
    denied = restarted.propose({**proposal.model_dump(), "operation_id": "second"})
    assert denied["reason"] == "budget_exhausted"
    assert denied["budget_used"] == 1
    assert not denied["budget_reserved"]
    assert len(adapter.patch_calls) == 1


def test_unsent_stale_rejection_releases_budget_durably(broker, proposal, policy, adapter):
    adapter.service["metadata"]["resourceVersion"] = "11"
    rejected = broker.propose(proposal)
    assert rejected["reason"] == "resource_version_changed"
    assert not rejected["budget_reserved"]
    assert rejected["budget_used"] == 0
    assert adapter.patch_calls == []
    assert [event["event"] for event in broker.events(proposal.operation_id)] == [
        "prepared", "rejected", "budget_released"
    ]
    restarted = ActionBroker(broker.journal_path, policy, adapter)
    repaired = restarted.propose({
        **proposal.model_dump(), "operation_id": "fresh-version", "resource_version": "11"
    })
    assert repaired["status"] == "acknowledged"
    assert repaired["budget_used"] == 1
    assert len(adapter.patch_calls) == 1


@pytest.mark.parametrize("field,value,reason", [
    ("uid", "recreated-uid", "service_uid_changed"),
    ("resourceVersion", "11", "resource_version_changed"),
    ("namespace", "other", "service_namespace_changed"),
    ("name", "other", "service_name_changed"),
])
def test_changed_resource_rejected_before_dispatch(broker, proposal, adapter, field, value, reason):
    adapter.service["metadata"][field] = value
    assert broker.propose(proposal)["reason"] == reason
    assert adapter.patch_calls == []


def test_changed_target_rejected_before_dispatch(broker, proposal, adapter):
    adapter.service["spec"]["ports"][1]["targetPort"] = "http"
    assert broker.propose(proposal)["reason"] == "target_port_changed"
    assert adapter.patch_calls == []


@pytest.mark.parametrize("mutate", [
    lambda service: service["metadata"].update(resourceVersion="12"),
    lambda service: service["metadata"].update(uid="recreated"),
    lambda service: service["spec"]["ports"].reverse(),
    lambda service: service["spec"]["ports"][1].update(targetPort=8888),
])
def test_race_after_read_fails_conditional_patch(broker, proposal, adapter, mutate):
    adapter.before_patch = mutate
    result = broker.propose(proposal)
    assert result["status"] == "rejected"
    assert result["reason"] == "precondition_failed"
    assert result["budget_reserved"] and result["budget_used"] == 1
    assert all(port["targetPort"] != 8080 for port in adapter.service["spec"]["ports"])


def test_lost_ack_never_redispatches_or_claims_attribution(broker, proposal, policy, adapter):
    adapter.lose_ack = True
    assert broker.propose(proposal)["status"] == "uncertain"
    restarted = ActionBroker(broker.journal_path, policy, adapter)
    assert restarted.propose(proposal)["status"] == "uncertain"
    assert restarted.resume_prepared(proposal.operation_id)["status"] == "uncertain"
    reconciled = restarted.reconcile(proposal.operation_id)
    assert reconciled["status"] == "uncertain"
    assert reconciled["reconciliation"]["observation"] == "desired_state_observed"
    assert reconciled["reconciliation"]["attribution"] == "not_established"
    assert reconciled["reconciliation"]["recovery"] == "not_verified"
    assert len(adapter.patch_calls) == 1


@pytest.mark.parametrize("stage", ["after_dispatch", "before_record"])
def test_crash_after_mutation_leaves_uncertainty_across_restart(
    tmp_path, policy, proposal, adapter, stage
):
    def hook(point):
        if point == stage:
            raise Crash()

    broker = ActionBroker(tmp_path / "journal.sqlite", policy, adapter, hook=hook)
    with pytest.raises(Crash):
        broker.propose(proposal)
    with sqlite3.connect(broker.journal_path) as db:
        assert db.execute("SELECT status FROM operations").fetchone()[0] == "dispatching"
    restarted = ActionBroker(broker.journal_path, policy, adapter)
    result = restarted.lookup(proposal.operation_id)
    assert result["status"] == "uncertain"
    assert result["journal_status"] == "dispatching"
    restarted.propose(proposal)
    restarted.resume_prepared(proposal.operation_id)
    assert restarted.reconcile(proposal.operation_id)["status"] == "uncertain"
    assert len(adapter.patch_calls) == 1


def test_dispatch_crash_before_external_effect_still_cannot_be_retried(
    broker, proposal, policy, adapter
):
    def crash(_service):
        raise Crash()

    adapter.before_patch = crash
    with pytest.raises(Crash):
        broker.propose(proposal)
    restarted = ActionBroker(broker.journal_path, policy, adapter)
    observed = restarted.reconcile(proposal.operation_id)
    assert observed["status"] == "uncertain"
    assert observed["reconciliation"]["observation"] == "desired_state_not_observed"
    restarted.resume_prepared(proposal.operation_id)
    assert len(adapter.patch_calls) == 1


@pytest.mark.parametrize("code,status", [(409, "rejected"), (422, "rejected"), (500, "uncertain")])
def test_api_rejection_is_distinct_from_unknown_outcome(broker, proposal, adapter, code, status):
    class ApiError(RuntimeError):
        status_code = code

    def fail(_service):
        raise ApiError()

    adapter.before_patch = fail
    result = broker.propose(proposal)
    assert result["status"] == status
    assert result["budget_reserved"] and result["budget_used"] == 1
    assert not any(event["event"] == "budget_released" for event in broker.events(proposal.operation_id))
    assert len(adapter.patch_calls) == 1


@pytest.mark.parametrize("acknowledgement", [
    None, [], {}, {"metadata": None}, {"metadata": []},
    {"metadata": {"uid": "wrong-service", "resourceVersion": "11"}},
    {"metadata": {"uid": "service-uid", "resourceVersion": None}},
    {"metadata": {"uid": "service-uid", "resourceVersion": ""}},
])
def test_malformed_ack_becomes_uncertain_without_redispatch(
    broker, proposal, policy, adapter, monkeypatch, acknowledgement
):
    original_patch = adapter.patch_service

    def malformed(namespace, name, patch):
        original_patch(namespace, name, patch)
        return acknowledgement

    monkeypatch.setattr(adapter, "patch_service", malformed)
    result = broker.propose(proposal)
    assert result["status"] == "uncertain"
    assert result["reason"] == "ack_unparseable"
    assert result["budget_reserved"] and result["budget_used"] == 1
    assert broker.lookup(proposal.operation_id)["status"] == "uncertain"
    assert broker.propose(proposal)["status"] == "uncertain"
    restarted = ActionBroker(broker.journal_path, policy, adapter)
    assert restarted.resume_prepared(proposal.operation_id)["status"] == "uncertain"
    assert restarted.reconcile(proposal.operation_id)["reconciliation"]["attribution"] == "not_established"
    assert len(adapter.patch_calls) == 1


@pytest.mark.parametrize("mutate", [
    lambda result: result["metadata"].update(resourceVersion="10"),
    lambda result: result["spec"]["ports"][1].update(targetPort=9999),
    lambda result: result["spec"]["ports"][1].update(targetPort="8080"),
    lambda result: result.update(spec=None),
    lambda result: result.update(spec=[]),
    lambda result: result["spec"].pop("ports"),
    lambda result: result["spec"].update(ports=None),
    lambda result: result["spec"].update(ports={"name": "http", "targetPort": 8080}),
    lambda result: result["spec"]["ports"].append(None),
    lambda result: result["spec"]["ports"].append({"name": "http", "targetPort": 8080}),
])
def test_inconsistent_service_ack_is_uncertain_and_retains_dispatch_budget(
    broker, proposal, adapter, monkeypatch, mutate
):
    original_patch = adapter.patch_service

    def inconsistent(namespace, name, patch):
        response = original_patch(namespace, name, patch)
        mutate(response)
        return response

    monkeypatch.setattr(adapter, "patch_service", inconsistent)
    result = broker.propose(proposal)
    assert result["status"] == "uncertain"
    assert result["reason"] == "ack_unparseable"
    assert result["budget_reserved"] and result["budget_used"] == 1
    assert broker.propose(proposal)["status"] == "uncertain"
    assert len(adapter.patch_calls) == 1
    assert adapter.service["spec"]["ports"][1]["targetPort"] == 8080


def prepare_with_crash(tmp_path, policy, adapter, proposal):
    def crash(stage):
        if stage == "after_intent":
            raise Crash()

    broker = ActionBroker(tmp_path / "journal.sqlite", policy, adapter, hook=crash)
    with pytest.raises(Crash):
        broker.propose(proposal)
    assert broker.lookup(proposal.operation_id)["status"] == "prepared"
    assert adapter.patch_calls == []
    return broker


def test_prepared_requires_explicit_resume_and_retains_reservation(tmp_path, policy, adapter, proposal):
    broker = prepare_with_crash(tmp_path, policy, adapter, proposal)
    restarted = ActionBroker(broker.journal_path, policy, adapter)
    assert restarted.propose(proposal)["status"] == "prepared"
    assert restarted.reconcile(proposal.operation_id)["status"] == "prepared"
    assert adapter.patch_calls == []
    result = restarted.resume_prepared(proposal.operation_id)
    assert result["status"] == "acknowledged"
    assert result["budget_used"] == 1
    assert len(adapter.patch_calls) == 1


@pytest.mark.parametrize("revocation,reason", [
    (lambda policy: setattr(policy, "enabled", False), "policy_disabled"),
    (lambda policy: setattr(policy, "max_dispatches", 0), "budget_revoked"),
    (lambda policy: setattr(policy, "allowed_target_ports", frozenset({9090})), "target_port_not_allowed"),
])
def test_prepared_revalidates_revoked_authority_and_budget(
    tmp_path, policy, adapter, proposal, revocation, reason
):
    broker = prepare_with_crash(tmp_path, policy, adapter, proposal)
    revocation(policy)
    restarted = ActionBroker(broker.journal_path, policy, adapter)
    result = restarted.resume_prepared(proposal.operation_id)
    assert result["reason"] == reason
    assert not result["budget_reserved"] and result["budget_used"] == 0
    assert adapter.patch_calls == []


@pytest.mark.parametrize("field,value,reason", [
    ("enabled", False, "policy_disabled"),
    ("max_dispatches", 0, "budget_revoked"),
])
def test_policy_revocation_immediately_before_send_is_respected(
    broker, proposal, policy, adapter, field, value, reason
):
    def revoke(stage):
        if stage == "before_dispatch":
            setattr(policy, field, value)

    broker.hook = revoke
    result = broker.propose(proposal)
    assert result["reason"] == reason
    assert not result["budget_reserved"] and result["budget_used"] == 0
    assert broker.events(proposal.operation_id)[-1]["event"] == "budget_released"
    assert adapter.patch_calls == []


def test_prepared_revalidates_version_after_restart(tmp_path, policy, adapter, proposal):
    broker = prepare_with_crash(tmp_path, policy, adapter, proposal)
    adapter.service["metadata"]["resourceVersion"] = "11"
    restarted = ActionBroker(broker.journal_path, policy, adapter)
    assert restarted.resume_prepared(proposal.operation_id)["reason"] == "resource_version_changed"
    assert adapter.patch_calls == []


def test_concurrent_duplicate_submissions_have_one_dispatch_owner(broker, policy, proposal, adapter):
    second = ActionBroker(broker.journal_path, policy, adapter)
    barrier = threading.Barrier(12)

    def submit(index):
        barrier.wait(timeout=10)
        return (broker if index % 2 else second).propose(proposal)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(submit, range(12)))
    assert all(result["status"] in {"prepared", "dispatching", "uncertain", "acknowledged"} for result in results)
    assert broker.lookup(proposal.operation_id)["status"] == "acknowledged"
    assert len(adapter.patch_calls) == 1


def test_concurrent_resumes_have_one_dispatch_owner(tmp_path, policy, proposal, adapter):
    broker = prepare_with_crash(tmp_path, policy, adapter, proposal)
    brokers = [ActionBroker(broker.journal_path, policy, adapter) for _ in range(6)]
    barrier = threading.Barrier(6)

    def resume(instance):
        barrier.wait(timeout=10)
        return instance.resume_prepared(proposal.operation_id)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(resume, brokers))
    assert len(adapter.patch_calls) == 1
    assert broker.lookup(proposal.operation_id)["status"] == "acknowledged"


def test_concurrent_distinct_requests_cannot_overspend_budget(broker, proposal, adapter):
    barrier = threading.Barrier(8)

    def submit(index):
        barrier.wait(timeout=10)
        return broker.propose({**proposal.model_dump(), "operation_id": f"operation-{index}"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(8)))
    assert sum(result["status"] == "acknowledged" for result in results) == 1
    assert sum(result["reason"] == "budget_exhausted" for result in results) == 7
    assert len(adapter.patch_calls) == 1


def test_read_failure_leaves_prepared_intent_resumable(broker, proposal, adapter):
    adapter.read_unavailable = True
    assert broker.propose(proposal)["status"] == "prepared"
    assert adapter.patch_calls == []
    adapter.read_unavailable = False
    assert broker.resume_prepared(proposal.operation_id)["status"] == "acknowledged"


def test_reconcile_unavailable_does_not_invent_recovery(broker, proposal, adapter):
    broker.propose(proposal)
    adapter.read_unavailable = True
    result = broker.reconcile(proposal.operation_id)
    assert result["status"] == "acknowledged"
    assert result["reconciliation"]["observation"] == "unavailable"
    assert result["reconciliation"]["recovery"] == "not_verified"


def test_other_actor_repair_is_observation_without_attribution(tmp_path, policy, adapter, proposal):
    broker = prepare_with_crash(tmp_path, policy, adapter, proposal)
    adapter.service["spec"]["ports"][1]["targetPort"] = 8080
    adapter.service["metadata"]["resourceVersion"] = "11"
    result = broker.reconcile(proposal.operation_id)
    assert result["status"] == "prepared"
    assert result["reconciliation"]["observation"] == "desired_state_observed"
    assert result["reconciliation"]["attribution"] == "not_established"
    assert adapter.patch_calls == []


def test_memory_journal_is_forbidden(policy, adapter):
    with pytest.raises(ValueError, match="durable"):
        ActionBroker(":memory:", policy, adapter)
