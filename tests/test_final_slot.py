"""Authored checker inputs, never reported as experimental evidence."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from autonomy_lab.procedures import Refused
from experiments.contract_confirmation.audit import require_early_change
from experiments.final_slot import gate, negative


@pytest.fixture(autouse=True)
def historical_selection_inputs(request, monkeypatch):
    """Authored selection tests use the old pin; this never approves current code."""
    if request.node.name == 'test_historical_entry_refuses_current_runtime':
        return
    frozen = json.loads(Path('experiments/contract_confirmation/runtime-pin.json').read_text())
    monkeypatch.setattr(gate.shared, 'freeze', lambda raw: copy.deepcopy(frozen['program_pin']))


def test_historical_entry_refuses_current_runtime():
    with pytest.raises(Refused, match='Selected runtime or program changed'):
        gate.plan()


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


def test_new_contexts_keep_exact_runtime_authority_and_bounded_cohort():
    plan = gate.plan()
    assert len(plan["cases"]) == 6
    assert sorted(sum(plan["shards"], [])) == sorted(plan["cases"])
    for spec in plan["cases"].values():
        assert (
            spec["program_pin"]
            == gate.shared.declaration(spec["arm"], "heartbeat_burst")["program_pin"]
        )
        assert spec["contract"]["duration_seconds"] == 210
        assert spec["contract"]["max_dispatches"] == 2
        assert spec["contract"]["max_operator_starts"] == 3
        assert spec["early_change_offset"] == 135
        assert not spec["contract"]["admit_program"]
        assert spec["contract"]["admitted_procedure"] is None
    workflow = yaml.safe_load(Path(".github/workflows/final-slot.yml").read_text())
    trigger = workflow.get("on", workflow.get(True))
    assert set(trigger) == {"pull_request"}
    assert trigger["pull_request"]["types"] == ["opened"]
    assert "experiments/final_slot/**" in trigger["pull_request"]["paths"]


def test_selection_requires_strict_gain_and_no_regression_without_granting_authority():
    values = measurements()
    assert gate.select(gate.plan(), values)["selected"] == "legacy"
    values["precise-heartbeat_final"]["sample_counts"].update(
        verified_success=11, verified_failure=10
    )
    result = gate.select(gate.plan(), values)
    assert result["decision"] == "confirmed_candidate_requires_separate_admission"
    assert result["selected"] == "precise" and result["confirmation_run"]
    assert not result["promotion"] and not result["selection_confers_authority"]
    values["precise-protected_before"]["sample_counts"].update(
        verified_success=9, verified_failure=12
    )
    assert gate.select(gate.plan(), values)["selected"] == "legacy"


@pytest.mark.parametrize("name", [a + "-" + c for a in gate.shared.ARMS for c in gate.CONTEXTS])
def test_one_ineligible_case_withholds(name):
    values = measurements()
    values[name]["eligible"] = False
    result = gate.select(gate.plan(), values)
    assert result["selected"] is None and result["confirmation_withheld"]


@pytest.mark.parametrize("damage", ["missing", "unknown", "identity", "budget", "unsafe"])
def test_incomplete_or_unsafe_selection_is_rejected(damage):
    values = measurements()
    value = values["precise-heartbeat_final"]
    if damage == "missing":
        values.pop("legacy-protected_final")
    elif damage == "unknown":
        value["sample_counts"].update(unknown=1, verified_failure=10)
    elif damage == "identity":
        value["candidate"] = values["legacy-heartbeat_final"]["candidate"]
    elif damage == "budget":
        value["spent_dispatches"] = value["actual_api_attempts"] = 3
    else:
        value["authority_conformant"] = False
    with pytest.raises(Refused):
        gate.select(gate.plan(), values)


def first_record():
    row = {
        "operation_id": "authored-first",
        "status": "acknowledged",
        "reason": "api_acknowledged",
        "budget_reserved": 1,
        "created_at": "2026-09-26T00:00:46Z",
        "updated_at": "2026-09-26T00:00:47Z",
    }
    from autonomy_lab.recurrence import epoch

    start = epoch("2026-09-26T00:00:00Z")
    record = {
        "first_requested_at": start + 45,
        "first_stop_requested_at": start + 115,
        "operations_first": [copy.deepcopy(row)],
    }
    return record, {"operations": [row]}


@pytest.mark.parametrize("damage", ["prior_budget", "prior_acknowledgement"])
def test_first_capacity_corruptions_reach_the_declared_guard(damage):
    record, card = first_record()
    gate.require_first_capacity(record, card)
    negative.corrupt_record(record, damage)
    assert (
        negative.require_rejection(damage, lambda: gate.require_first_capacity(record, card))
        == negative.EXPECTED[damage]
    )


def early_record():
    return {
        "second_fault": {"finished_at": 125.1},
        "early_change": {"kind": "annotation", "requested_at": 135, "finished_at": 135.1},
        "second_requested_at": 140,
    }


@pytest.mark.parametrize("damage", ["early_change_late", "early_change_missing"])
def test_early_corruptions_reach_the_declared_guard(damage):
    record = early_record()
    require_early_change(record)
    negative.corrupt_record(record, damage)
    assert (
        negative.require_rejection(damage, lambda: require_early_change(record))
        == negative.EXPECTED[damage]
    )


@pytest.mark.parametrize("labels", [None, {}, {"kept": "value"}])
def test_new_record_constructors_accept_inert_optional_metadata(labels):
    first, _ = first_record()
    record = {
        **first,
        **early_record(),
        "checkpoints": [
            {"phase": "first", "stage": "preflight", "operation_id": "authored-first"},
            {
                "phase": "second",
                "stage": "preflight",
                "operation_id": "authored-second",
                "changes": [
                    {
                        "response": {
                            "metadata": {**({"labels": labels} if labels is not None else {})}
                        }
                    }
                ],
            },
        ],
    }
    for damage in [
        "wrong_operation",
        "prior_budget",
        "prior_acknowledgement",
        "early_change_late",
        "early_change_missing",
    ]:
        altered = copy.deepcopy(record)
        negative.corrupt_record(altered, damage)
        assert altered != record


def test_negative_control_crash_or_unrelated_rejection_is_never_success():
    for error in [
        KeyError("labels"),
        Refused("unrelated"),
        ValueError(negative.EXPECTED["prior_budget"]),
    ]:

        def action(error=error):
            raise error

        with pytest.raises((KeyError, Refused)):
            negative.require_rejection("prior_budget", action)
    with pytest.raises(Refused, match="corruption passed"):
        negative.require_rejection("prior_budget", lambda: None)


@pytest.mark.parametrize("damage", ["wrong_operation", "wrong_barrier_phase"])
def test_final_conflict_must_belong_to_the_first_prepared_operation_of_second_response(damage):
    from experiments.contract_confirmation.audit import require_conflict_boundary

    points = [
        {
            "phase": phase,
            "stage": stage,
            "operation_id": "authored-" + phase,
            "barrier": {"at": offset + index},
        }
        for phase, offset in [("first", 45), ("second", 140)]
        for index, stage in enumerate(["intent", "preflight"])
    ]
    points[-1]["changes"] = [{"kind": "tick-1"}, {"kind": "annotation"}]
    require_conflict_boundary(points, "second", ("tick-1", "annotation"))
    record = {"checkpoints": points}
    if damage == "wrong_operation":
        negative.corrupt_record(record, damage)
    else:
        points[-2]["changes"] = points[-1].pop("changes")
    assert (
        negative.require_rejection(
            damage, lambda: require_conflict_boundary(points, "second", ("tick-1", "annotation"))
        )
        == negative.EXPECTED[damage]
    )


def test_missing_second_fault_is_explicitly_refused_by_early_change_guard():
    record = early_record()
    del record["second_fault"]
    with pytest.raises(Refused, match="Early protected change not completed"):
        require_early_change(record)


def test_response_phase_check_rejects_a_mislabeled_operation_even_with_matching_id():
    from experiments.contract_confirmation.audit import require_conflict_boundary

    points = [
        {
            "phase": "second",
            "stage": "intent",
            "operation_id": "authored-second",
            "barrier": {"at": 140},
        },
        {
            "phase": "first",
            "stage": "preflight",
            "operation_id": "authored-second",
            "barrier": {"at": 141},
            "changes": [{"kind": "tick-1"}],
        },
    ]
    with pytest.raises(Refused, match="Conflict placed at wrong causal boundary"):
        require_conflict_boundary(points, "second", ("tick-1",))
