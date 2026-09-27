"""One frozen six-case confirmation; selection never grants execution authority."""

import hashlib
import random

from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require
from autonomy_lab.recurrence import epoch
from experiments.contract_confirmation import audit as shared_audit
from experiments.contract_confirmation import gate as shared

CONTEXTS = ("heartbeat_final", "protected_final", "protected_before")
SEQUENCES = {
    "heartbeat_final": ("tick-1",),
    "protected_final": ("tick-1", "annotation"),
    "protected_before": (),
}
SHARDS = 3
EVIDENCE_USE = "prospective_final_slot_confirmation"


def declaration(arm, context):
    require(context in CONTEXTS, "Unknown final-slot context")
    # The shared template checks the exact PR23 runtime and both combined pins.
    value = shared.declaration(arm, "heartbeat_burst")
    paths = [
        "docs/FINAL_SLOT_CONFIRMATION_GATE.md",
        "docs/validation/final-slot-novelty.json",
        ".github/workflows/final-slot.yml",
        *[str(p.relative_to(ROOT)) for p in sorted((ROOT / "experiments/final_slot").glob("*.py"))],
    ]
    value.update(context=context, evidence_use=EVIDENCE_USE, early_change_offset=135)
    value["gate_sources"].update(
        {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    )
    return value


def plan():
    cases = {
        arm + "-" + context: declaration(arm, context)
        for arm in shared.ARMS
        for context in CONTEXTS
    }
    order = list(cases)
    random.Random(2026092603).shuffle(order)
    return {
        "schema_version": 1,
        "evidence_use": EVIDENCE_USE,
        "order_seed": 2026092603,
        "order": order,
        "shards": [order[i::SHARDS] for i in range(SHARDS)],
        "cases": cases,
        "attempts_per_case": 1,
        "cost_budget": {
            "campaigns": 6,
            "dispatches_per_campaign": 2,
            "model_requests": 0,
            "shard_timeout_minutes": 25,
            "ci_job_timeout_minutes": 35,
            "billed_compute_cost": None,
            "human_active_seconds": None,
        },
        "selection_rule": "All six cases eligible and authority-conformant; precise has no fewer healthy samples or more dispatches anywhere, and strictly more healthy samples in heartbeat_final. Baseline wins ties. Selection grants no authority.",
        "limits": [
            "Authored prospective combinations; not independent designers or production incident frequencies.",
            "Sampled customer windows, not continuous availability or full economic return.",
            "No model discovery, admission, deployment or autonomous learning.",
        ],
    }


def require_first_capacity(record, card):
    first = [
        o for o in card["operations"] if epoch(o["created_at"]) < record["first_stop_requested_at"]
    ]
    require(
        record["operations_first"] == first
        and len(first) == 1
        and first[0]["status"] == "acknowledged"
        and first[0]["reason"] == "api_acknowledged"
        and first[0]["budget_reserved"] == 1
        and record["first_requested_at"]
        <= epoch(first[0]["created_at"])
        <= epoch(first[0]["updated_at"])
        <= record["first_stop_requested_at"],
        "First repair did not leave one dispatch slot",
    )


def assess_operations(directory, spec, card, record, evidence, captured):
    require_first_capacity(record, card)
    return shared_audit.assess_operations(
        directory,
        spec,
        card,
        record,
        evidence,
        captured,
        conflict_phase="second",
        expected_sequence=SEQUENCES[spec["context"]],
        early_change=spec["context"] == "protected_before",
    )


def evaluate(gate):
    value = shared.evaluate(gate, declaration_fn=declaration, operation_auditor=assess_operations)
    require(value["remaining_after_first"] == 1, "First repair did not leave one dispatch slot")
    return value


def select(declared, evaluations):
    eligible, gain = shared.compare(
        declared,
        evaluations,
        expected_plan=plan(),
        contexts=CONTEXTS,
        gain_context="heartbeat_final",
    )
    return {
        "status": "complete",
        "decision": "withhold_selection_ineligible"
        if not eligible
        else "confirmed_candidate_requires_separate_admission"
        if gain
        else "retain_maintained_baseline",
        "selected": None if not eligible else "precise" if gain else "legacy",
        "confirmation_run": True,
        "confirmation_withheld": not eligible,
        "selection_confers_authority": False,
        "promotion": False,
        "evaluations": evaluations,
        "limits": declared["limits"],
    }
