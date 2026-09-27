"""Authored checker/selection counterexamples; never live experiment results."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from autonomy_lab.operation_contract import HEARTBEAT
from autonomy_lab.procedures import Refused
from experiments.contract_confirmation import gate
from experiments.contract_confirmation.audit import controller_patch, verify_sequence
from experiments.contract_confirmation.negative import require_rejection


def test_exact_selected_runtime_and_combined_candidate_are_preserved():
    declared = gate.plan()
    frozen = json.loads(Path("experiments/contract_confirmation/runtime-pin.json").read_text())
    assert len(declared["cases"]) == 8
    assert sorted(sum(declared["shards"], [])) == sorted(declared["cases"])
    for spec in declared["cases"].values():
        assert spec["program_pin"] == frozen["program_pin"]
        assert spec["candidate"] == frozen["candidates"][spec["arm"]]
        assert spec["contract"]["max_dispatches"] == 2
        assert spec["contract"]["max_operator_starts"] == 3
        assert spec["contract"]["duration_seconds"] == 210
        assert spec["evidence_use"] == "prospective_confirmation"
        assert not spec["contract"]["admit_program"]
        assert spec["contract"]["admitted_procedure"] is None
        assert "experiments/contract_confirmation/audit.py" in spec["gate_sources"]


def test_changed_runtime_cannot_be_silently_confirmed(monkeypatch):
    original = gate.freeze

    def changed(raw):
        value = original(raw)
        value["definition"]["runtime_files"]["authored_extra"] = "authored-change"
        return value

    monkeypatch.setattr(gate, "freeze", changed)
    with pytest.raises(Refused, match="Selected runtime or program changed"):
        gate.plan()


def test_recurrence_requires_all_three_exact_healthy_slots():
    samples = [
        {"scheduled_at": 1000 + offset, "verification": {"verdict": "verified_success"}}
        for offset in (90, 100, 110)
    ]
    assert gate.recovered_before_recurrence(samples, 1000)
    assert not gate.recovered_before_recurrence(samples[:-1], 1000)
    for verdict in ("verified_failure", "indeterminate"):
        altered = copy.deepcopy(samples)
        altered[1]["verification"]["verdict"] = verdict
        assert not gate.recovered_before_recurrence(altered, 1000)
    altered = copy.deepcopy(samples)
    altered[1]["scheduled_at"] += 1
    assert not gate.recovered_before_recurrence(altered, 1000)


def test_execution_budget_leaves_separate_ci_retention_time():
    declared = gate.plan()
    workflow = yaml.safe_load(Path(".github/workflows/contract-confirmation.yml").read_text())
    job = workflow["jobs"]["compare"]
    execution = next(s for s in job["steps"] if s.get("name") == "Execute each frozen case once")
    assert execution["timeout-minutes"] == declared["cost_budget"]["shard_timeout_minutes"] == 25
    assert job["timeout-minutes"] == declared["cost_budget"]["ci_job_timeout_minutes"] == 35
    assert all(s["provision_timeout_seconds"] == 180 for s in declared["cases"].values())


def measurements():
    return {
        name: {
            **{k: spec[k] for k in ("arm", "context", "candidate", "evidence_use")},
            "measurement_valid": True,
            "authority_conformant": True,
            "eligible": True,
            "sample_counts": {"verified_success": 10, "verified_failure": 11, "unknown": 0},
            "spent_dispatches": 2,
            "actual_api_attempts": 2,
        }
        for name, spec in gate.plan()["cases"].items()
    }


def test_tie_retains_baseline_and_burst_gain_only_earns_admission_consideration():
    values = measurements()
    assert gate.select(gate.plan(), values)["selected"] == "legacy"
    values["precise-heartbeat_burst"]["sample_counts"].update(
        verified_success=11, verified_failure=10
    )
    result = gate.select(gate.plan(), values)
    assert result["decision"] == "candidate_confirmed_requires_combined_admission"
    assert (
        result["confirmation_run"]
        and not result["promotion"]
        and not result["selection_confers_authority"]
    )
    values["precise-heartbeat_return"]["sample_counts"].update(
        verified_success=9, verified_failure=12
    )
    assert gate.select(gate.plan(), values)["selected"] == "legacy"


@pytest.mark.parametrize("case", list(gate.plan()["cases"]))
def test_any_ineligible_case_withholds(case):
    values = measurements()
    values[case]["eligible"] = False
    assert gate.select(gate.plan(), values)["selected"] is None


@pytest.mark.parametrize("damage", ["missing", "identity", "unknown", "extra_dispatch", "unsafe"])
def test_incomplete_selection_is_rejected(damage):
    values = measurements()
    value = values["precise-heartbeat_burst"]
    if damage == "missing":
        values.pop("legacy-heartbeat_return")
    elif damage == "identity":
        value["candidate"] = values["legacy-heartbeat_return"]["candidate"]
    elif damage == "unknown":
        value["sample_counts"].update(unknown=1, verified_failure=10)
    elif damage == "extra_dispatch":
        value["spent_dispatches"] = value["actual_api_attempts"] = 3
    else:
        value["authority_conformant"] = False
    with pytest.raises(Refused):
        gate.select(gate.plan(), values)


def sequence():
    initial = {
        "metadata": {
            "uid": "authored",
            "resourceVersion": "1",
            "annotations": {HEARTBEAT: "initial"},
        }
    }
    tick1 = copy.deepcopy(initial)
    tick1["metadata"].update(resourceVersion="2")
    tick1["metadata"]["annotations"][HEARTBEAT] = "tick-1"
    tick2 = copy.deepcopy(tick1)
    tick2["metadata"].update(resourceVersion="3")
    tick2["metadata"]["annotations"][HEARTBEAT] = "tick-2"
    return {
        "before": initial,
        "before_at": 1,
        "after": tick2,
        "after_at": 6,
        "changes": [
            {"before": initial, "requested_at": 2, "finished_at": 3, "response": tick1},
            {"before": tick1, "requested_at": 4, "finished_at": 5, "response": tick2},
        ],
    }


@pytest.mark.parametrize("damage", ["omitted", "order", "time", "response", "after_version"])
def test_intermediate_states_cannot_be_collapsed_or_reordered(damage):
    point = sequence()
    verify_sequence(point)
    if damage == "omitted":
        point["changes"].pop(0)
    elif damage == "order":
        point["changes"].reverse()
    elif damage == "time":
        point["changes"][1]["requested_at"] = 2
    elif damage == "response":
        point["changes"][0]["response"] = copy.deepcopy(point["before"])
    else:
        point["after"] = copy.deepcopy(point["after"])
        point["after"]["metadata"]["resourceVersion"] = "4"
    with pytest.raises(Refused):
        verify_sequence(point)


def test_protected_annotation_is_a_separate_conditional_request():
    before = sequence()["before"]
    original = copy.deepcopy(before)
    patch = controller_patch(before, "annotation")
    assert patch[:2] == [
        {"op": "test", "path": "/metadata/uid", "value": "authored"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "1"},
    ]
    assert patch[-1] == {
        "op": "add",
        "path": "/metadata/annotations/autonomy-lab~1confirmation-protected",
        "value": "changed",
    }
    assert before == original
    with pytest.raises(Refused):
        controller_patch(before, "restore_authority")


def test_negative_control_requires_exact_rejection_not_crash_or_unrelated_failure():
    def intended():
        raise Refused("Declared intervention sequence differs")

    assert (
        require_rejection("omitted_intermediate", intended)
        == "Declared intervention sequence differs"
    )
    for error in (
        Refused("unrelated"),
        ValueError("Declared intervention sequence differs"),
        RuntimeError("crash"),
    ):

        def wrong(error=error):
            raise error

        with pytest.raises((Refused, RuntimeError)):
            require_rejection("omitted_intermediate", wrong)
    with pytest.raises(Refused, match="corruption passed"):
        require_rejection("omitted_intermediate", lambda: None)
