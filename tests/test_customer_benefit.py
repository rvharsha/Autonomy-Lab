"""Authored policy/measurement counterexamples, not real experiment outcomes."""

import copy
import json
from pathlib import Path

import pytest

from autonomy_lab.customer_benefit import (
    CONTEXTS,
    declaration,
    plan,
    recovered_before_recurrence,
    select,
)
from autonomy_lab.durable_contract import digest
from autonomy_lab.procedures import Refused


def test_frozen_cases_share_program_budget_calendar_and_combined_identity():
    declared = plan()
    assert len(declared["cases"]) == 8
    assert sorted(sum(declared["shards"], [])) == sorted(declared["cases"])
    assert {c["contract"]["max_dispatches"] for c in declared["cases"].values()} == {2}
    assert {c["contract"]["max_operator_starts"] for c in declared["cases"].values()} == {3}
    assert {c["contract"]["duration_seconds"] for c in declared["cases"].values()} == {210}
    assert len({c["program_pin"]["version"] for c in declared["cases"].values()}) == 1
    assert len({c["candidate"]["version"] for c in declared["cases"].values()}) == 2
    for case in declared["cases"].values():
        assert (
            not case["contract"]["admit_program"] and case["contract"]["admitted_procedure"] is None
        )
        identity = {k: case["candidate"][k] for k in ("program_version", "operation_contract")}
        assert case["candidate"]["version"] == digest(identity)


def authored_evaluations():
    """Decision arithmetic only. These numbers are not live observations."""
    result = {}
    for name, spec in plan()["cases"].items():
        result[name] = {
            **{k: spec[k] for k in ("arm", "context", "candidate", "evidence_use")},
            "measurement_valid": True,
            "authority_conformant": True,
            "eligible": True,
            "sample_counts": {"verified_success": 10, "verified_failure": 11, "unknown": 0},
            "spent_dispatches": 2,
            "actual_api_attempts": 2,
        }
    return result


def test_baseline_wins_tie_and_only_declared_strict_gain_advances_without_authority():
    values = authored_evaluations()
    assert select(plan(), values)["selected"] == "legacy"
    values["precise-heartbeat_after"]["sample_counts"].update(
        verified_success=11, verified_failure=10
    )
    result = select(plan(), values)
    assert (
        result["selected"] == "precise"
        and not result["selection_confers_authority"]
        and not result["promotion"]
    )
    values["precise-quiet"]["sample_counts"].update(verified_success=9, verified_failure=12)
    assert select(plan(), values)["selected"] == "legacy"


@pytest.mark.parametrize(
    "case", ["legacy-quiet", "precise-heartbeat_after", "legacy-heartbeat_before"]
)
def test_any_ineligible_required_opportunity_withholds_selection(case):
    values = authored_evaluations()
    values[case]["eligible"] = False
    assert select(plan(), values)["selected"] is None


@pytest.mark.parametrize(
    "fault", ["missing_case", "wrong_contract", "unknown_measurement", "extra_budget", "unsafe"]
)
def test_incomplete_or_forged_selection_inputs_fail_closed(fault):
    values = authored_evaluations()
    value = values["precise-heartbeat_after"]
    if fault == "missing_case":
        values.pop("legacy-quiet")
    elif fault == "wrong_contract":
        value["candidate"] = copy.deepcopy(values["legacy-quiet"]["candidate"])
    elif fault == "unknown_measurement":
        value["sample_counts"].update(verified_failure=10, unknown=1)
    elif fault == "extra_budget":
        value.update(spent_dispatches=3, actual_api_attempts=3)
    else:
        value["authority_conformant"] = False
    with pytest.raises(Refused):
        select(plan(), values)


def test_early_change_control_is_not_a_recurrence_and_requires_real_recovery_samples():
    assert "heartbeat_before" in CONTEXTS
    rows = [
        {"scheduled_at": 1000 + offset, "verification": {"verdict": "verified_success"}}
        for offset in (90, 100, 110)
    ]
    assert recovered_before_recurrence(rows, 1000)
    assert not recovered_before_recurrence(rows[:-1], 1000)
    rows[-1]["verification"]["verdict"] = "verified_failure"
    assert not recovered_before_recurrence(rows, 1000)
    assert declaration("legacy", "heartbeat_before")["contract"]["test_pause_after_intent"]


def test_workflow_runs_changed_dependencies_and_keeps_intent_and_database_evidence():
    import yaml

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/customer-benefit.yml").read_text())
    assert {"src/autonomy_lab/**", "scripts/**", "infra/**", "fixtures/**", "procedures/**"} <= set(
        workflow[True]["pull_request"]["paths"]
    )
    upload = next(
        s for s in workflow["jobs"]["compare"]["steps"] if s.get("name", "").startswith("Retain")
    )
    paths = upload["with"]["path"]
    assert (
        "/intent/*/*.json" in paths
        and "/preflight/*/*.json" in paths
        and "operations.sqlite-wal" in paths
    )
    assert workflow["jobs"]["compare"]["strategy"]["fail-fast"] is False
    assert workflow["jobs"]["reproduce-and-select"]["if"] == "always()"
    assert (
        json.loads((root / "procedures/bounded-refresh.json").read_text())["conditional_rejection"]
        == "refresh"
    )
