"""Prospective confirmation evaluator for the unchanged PR23 runtime."""

import hashlib
import random
from collections import Counter

from autonomy_lab.budget_horizon import first_episode_completed_by
from autonomy_lab.campaign import Contract, read
from autonomy_lab.conflict import load_evidence
from autonomy_lab.durable_contract import LEGACY, PRECISE, digest
from autonomy_lab.experiments import release_manifest
from autonomy_lab.harness import client_path_failed
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedure import freeze, verify_bindings
from autonomy_lab.procedures import require, verify_record
from autonomy_lab.recurrence import epoch, routing_only

ARMS = {"legacy": LEGACY, "precise": PRECISE}
CONTEXTS = ("heartbeat_burst", "heartbeat_annotation", "heartbeat_return", "heartbeat_post_ack")
SHARDS = 4


def declaration(arm, context):
    require(arm in ARMS and context in CONTEXTS, "Unknown comparison case")
    raw = (ROOT / "procedures/bounded-refresh.json").read_bytes()
    pin = freeze(raw)
    frozen = read(ROOT / "experiments/contract_confirmation/runtime-pin.json")
    require(pin == frozen["program_pin"], "Selected runtime or program changed")
    contract = Contract.model_validate(
        {
            **read(ROOT / "scenarios/campaign-program-refresh.json"),
            "duration_seconds": 210,
            "max_operator_starts": 3,
            "test_pause_after_intent": True,
            "operation_contract": ARMS[arm],
            "procedure_program": raw.decode(),
        }
    ).model_dump()
    paths = [
        "experiments/__init__.py",
        "scripts/check_campaign.py",
        "scripts/check_recurrence.py",
        "procedures/bounded-refresh.json",
        "scenarios/campaign-program-refresh.json",
        "docs/CONTRACT_CONFIRMATION_GATE.md",
        ".github/workflows/contract-confirmation.yml",
        *[
            str(p.relative_to(ROOT))
            for p in sorted((ROOT / "experiments/contract_confirmation").glob("*.py"))
        ],
        "experiments/contract_confirmation/runtime-pin.json",
    ]
    identity = {"program_version": pin["version"], "operation_contract": ARMS[arm]}
    require(
        {**identity, "version": digest(identity)} == frozen["candidates"][arm],
        "Selected combined candidate changed",
    )
    return {
        "arm": arm,
        "context": context,
        "evidence_use": "prospective_confirmation",
        "contract": contract,
        "program_pin": pin,
        "candidate": {**identity, "version": digest(identity)},
        "release_files": release_manifest({})["files"],
        "gate_sources": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
        "fixture_offset": 15,
        "post_ack_offset": 85,
        "stop_offset": 20,
        "fault_offset": 25,
        "first_start_offset": 45,
        "first_stop_offset": 115,
        "second_fault_offset": 125,
        "second_start_offset": 140,
        "response_deadline_seconds": 20,
        "schedule_lateness_seconds": 3,
    }


def plan():
    cases = {arm + "-" + context: declaration(arm, context) for arm in ARMS for context in CONTEXTS}
    order = list(cases)
    random.Random(2026092602).shuffle(order)
    return {
        "schema_version": 1,
        "evidence_use": "prospective_confirmation",
        "order_seed": 2026092602,
        "order": order,
        "shards": [order[i::SHARDS] for i in range(SHARDS)],
        "cases": cases,
        "attempts_per_case": 1,
        "cost_budget": {
            "campaigns": 8,
            "dispatches_per_campaign": 2,
            "model_requests": 0,
            "shard_timeout_minutes": 25,
            "billed_compute_cost": None,
            "human_active_seconds": None,
        },
        "selection_rule": "Complete eligible evidence for both arms in all four contexts; precise has no fewer healthy slots and no more dispatches anywhere, and strictly more healthy slots in heartbeat_burst. Baseline wins ties. Selection grants no authority.",
        "limits": [
            "Fresh authored combinations for a frozen candidate, not independent designers or production incident frequencies.",
            "Sampled windows, not continuous availability or full economic return.",
            "No model proposal, admission, deployment or automatic learning.",
        ],
    }


def complete_verification(value, window=1):
    verify_record(value, window)
    require(
        epoch(value["finished_at"]) - epoch(value["started_at"]) >= window,
        "Verification wall-clock window is incomplete",
    )
    require(
        all(
            p["verdict"] == "verified_success" or routing_only(p["reasons"])
            for p in value["probes"]
        ),
        "Missing or damaged independent verification evidence",
    )
    return {
        "windows": 1,
        "probes": len(value["probes"]),
        "quote_requests": sum(len(p["observations"]["quotes"]) for p in value["probes"]),
    }


def recovered_before_recurrence(samples, start):
    selected = [s for s in samples if s["scheduled_at"] in {start + x for x in (90, 100, 110)}]
    return len(selected) == 3 and all(
        s["verification"]["verdict"] == "verified_success" for s in selected
    )


def evaluate(gate):
    from .audit import assess_operations

    spec = read(gate / "declaration.json")
    require(
        spec == declaration(spec["arm"], spec["context"]), "Frozen declaration or source changed"
    )
    card, samples, evidence = load_evidence(gate, spec)
    directory, record = gate / "campaign", read(gate / "record.json")
    start, end = card["window"]["start"], card["window"]["end"]
    require(
        len(card["samples"]) == 21 and card["sample_counts"]["unknown"] == 0,
        "Incomplete customer measurement calendar",
    )
    require(
        card["identities_unchanged"] and len(card["identities_before"]) >= 11,
        "Workload identity changed",
    )
    require(
        card["owner_finished"]
        and card["owner_failure"] is None
        and card["cleanup"]["status"] == "deleted",
        "Owner cleanup incomplete",
    )
    require(
        Counter(w["id"].split("-")[0] for w in card["workers"]) == {"operator": 3, "observer": 1}
        and {record[k + "_worker"] for k in ("initial", "first", "second")}
        == {w["id"] for w in card["workers"] if w["id"].startswith("operator-")},
        "Worker population differs",
    )
    cost = Counter()
    for sample in samples:
        cost.update(complete_verification(sample["verification"]))
        require(
            sample["started_at"]
            <= epoch(sample["verification"]["started_at"])
            <= epoch(sample["verification"]["finished_at"])
            <= sample["finished_at"],
            "Verification lies outside its recorded observation",
        )
    observer_cost = dict(cost)
    cost.clear()
    for path in directory.glob("workers/*/episode-*/verification-*.json"):
        cost.update(complete_verification(read(path)))
    timing = [
        ("stop_requested_at", "stop_offset"),
        ("first_requested_at", "first_start_offset"),
        ("first_stop_requested_at", "first_stop_offset"),
        ("second_requested_at", "second_start_offset"),
    ]
    actual = [(record[k], spec[v]) for k, v in timing]
    actual.extend(
        (record[k]["requested_at"], spec[k + "_offset"])
        for k in ("fixture", "fault", "second_fault", "post_ack")
        if k in record
    )
    require(
        all(0 <= t - (start + offset) <= spec["schedule_lateness_seconds"] for t, offset in actual),
        "Controller schedule slipped",
    )
    require(
        record["stop_requested_at"] <= record["stopped_at"] <= record["fault"]["requested_at"]
        and record["first_stop_requested_at"]
        <= record["first_stopped_at"]
        <= record.get("second_fault", {"requested_at": record["second_requested_at"]})[
            "requested_at"
        ],
        "Prior operator did not stop before next phase",
    )
    for name in ("fault", "second_fault"):
        if name in record:
            action = record[name]
            require(
                all(
                    action["finished_at"] < s["started_at"]
                    or s["finished_at"] < action["requested_at"]
                    for s in samples
                ),
                "Controller routing action overlaps customer measurement",
            )
    require(
        any(
            s["started_at"] >= record["fault"]["finished_at"]
            and s["finished_at"] <= record["first_requested_at"]
            and client_path_failed(s["verification"])
            for s in samples
        ),
        "First fault not independently observed",
    )
    recovered = recovered_before_recurrence(samples, start)
    recurrence = True
    expected_opportunity = (
        "realized" if recurrence and recovered else "unrealized" if recurrence else "not_declared"
    )
    require(
        record["recurrence_opportunity"] == expected_opportunity
        and ("second_fault" in record) == (recurrence and recovered),
        "Undeclared or unverified recurrence",
    )
    if recurrence and recovered:
        require(
            any(
                s["started_at"] >= record["second_fault"]["finished_at"]
                and s["finished_at"] <= record["second_requested_at"]
                and client_path_failed(s["verification"])
                for s in samples
            ),
            "Second fault not independently observed",
        )
    detail = assess_operations(
        directory, spec, card, record, evidence, read(gate / "server-audit.json")
    )
    verify_bindings(
        directory,
        spec,
        {**card, "operations": detail["dispatch_rows"]},
        evidence,
        detail["journal"],
        read(gate / "server-audit.json"),
    )
    deadlines = {
        phase: first_episode_completed_by(
            next(w for w in card["workers"] if w["id"] == record[phase + "_worker"]),
            record[phase + "_requested_at"] + spec["response_deadline_seconds"],
        )
        for phase in ("first", "second")
    }
    eligible = (
        all(deadlines.values())
        and all(w["failure"] is None and w["ready"] is not None for w in card["workers"])
        and (not recurrence or recovered)
        and detail["intervention_exposed"]
    )
    failures = [
        {"slot": s["slot"], "started_at": s["started_at"], "finished_at": s["finished_at"]}
        for s in card["samples"]
        if s["verdict"] == "verified_failure"
    ]
    return {
        "measurement_valid": True,
        "authority_conformant": True,
        "eligible": eligible,
        "arm": spec["arm"],
        "context": spec["context"],
        "candidate": spec["candidate"],
        "sample_counts": card["sample_counts"],
        "failed_sampled_intervals": failures,
        "calendar_seconds": end - start,
        "response_deadlines_met": deadlines,
        "recurrence_opportunity": expected_opportunity,
        "intervention_exposed": detail["intervention_exposed"],
        "actual_api_attempts": len(detail["dispatch_rows"]),
        "spent_dispatches": card["dispatch_budget_reserved"],
        "unsent_refusals": detail["unsent_refusals"],
        "conditional_rejections": detail["conditional_rejections"],
        "remaining_after_first": detail["remaining_after_first"],
        "remaining_at_end": 2 - card["dispatch_budget_reserved"],
        "dispatch_timing": detail["dispatch_timing"],
        "observer_verification_work": observer_cost,
        "operator_verification_work": dict(cost),
        "verification_coverage": [
            {
                "worker": w["id"],
                "episode": e["id"],
                "completed_verification_records": len(
                    list((directory / "workers" / w["id"] / e["id"]).glob("verification-*.json"))
                ),
            }
            for w in card["workers"]
            if w["id"].startswith("operator-")
            for e in w["episodes"]
        ],
        "full_operator_request_cost_measured": False,
        "evidence_use": "prospective_confirmation",
    }


def select(declared, evaluations):
    require(
        declared == plan() and set(evaluations) == set(declared["cases"]),
        "Incomplete or changed comparison",
    )
    for name, value in evaluations.items():
        spec = declared["cases"][name]
        require(
            all(value[k] == spec[k] for k in ("arm", "context", "candidate", "evidence_use")),
            "Candidate identity differs",
        )
        require(
            value["measurement_valid"] is True and value["authority_conformant"] is True,
            "Invalid or unsafe evidence",
        )
        counts = value["sample_counts"]
        require(
            set(counts) == {"verified_success", "verified_failure", "unknown"}
            and all(type(n) is int and n >= 0 for n in counts.values())
            and sum(counts.values()) == 21
            and counts["unknown"] == 0,
            "Invalid customer calendar",
        )
        require(
            type(value["spent_dispatches"]) is int
            and 0 <= value["spent_dispatches"] <= 2
            and value["spent_dispatches"] == value["actual_api_attempts"]
            and type(value["eligible"]) is bool,
            "Invalid authority accounting",
        )
    eligible = all(v["eligible"] for v in evaluations.values())
    pairs = [(evaluations["precise-" + c], evaluations["legacy-" + c]) for c in CONTEXTS]
    gain = (
        eligible
        and all(
            a["sample_counts"]["verified_success"] >= b["sample_counts"]["verified_success"]
            and a["spent_dispatches"] <= b["spent_dispatches"]
            for a, b in pairs
        )
        and evaluations["precise-heartbeat_burst"]["sample_counts"]["verified_success"]
        > evaluations["legacy-heartbeat_burst"]["sample_counts"]["verified_success"]
    )
    return {
        "status": "complete",
        "decision": "withhold_selection_ineligible"
        if not eligible
        else "candidate_confirmed_requires_combined_admission"
        if gain
        else "retain_maintained_baseline",
        "selected": None if not eligible else "precise" if gain else "legacy",
        "selection_confers_authority": False,
        "confirmation_run": True,
        "promotion": False,
        "evaluations": evaluations,
        "limits": declared["limits"],
    }
