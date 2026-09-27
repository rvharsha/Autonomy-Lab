"""Authored corruptions of copied real evidence, never additional live trials."""

import copy
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from autonomy_lab.campaign import read
from autonomy_lab.durable_contract import LEGACY, binding_for
from autonomy_lab.harness import save
from autonomy_lab.procedures import Refused, require

from .gate import evaluate, plan, select

EXPECTED = {
    "missing_snapshot": "Conditions were replaced across preparation",
    "changed_contract": "Execution contract differs from candidate",
    "changed_program": "Procedure bytes or runtime differ from frozen definition",
    "extra_broker_request": "Replay or missing prepared dispatch",
    "corrupted_effect": "Repair changed more than targetPort",
    "wrong_barrier_phase": "Conflict placed at wrong causal boundary",
    "unverified_recurrence": "Controller schedule slipped",
    "missing_database": "Missing or damaged independent verification evidence",
    "missing_corpus": "Missing or damaged independent verification evidence",
    "altered_verification_summary": "Verification summary does not reproduce",
    "missing_operation_binding": "Missing or extra operation binding",
    "missing_sample": "Incomplete customer measurement calendar",
    "claim_after_request": "Journal timestamps contradict operation/tool evidence",
    "incomplete_case_inventory": "Incomplete or changed comparison",
    "omitted_intermediate": "Declared intervention sequence differs",
    "reordered_intermediate": "Declared intervention sequence differs",
    "altered_intermediate": "Controller effect differs",
    "broken_intermediate_time": "Intermediate intervention sequence differs",
    "invalid_acknowledgement": "Post-ack intervention lacks completed original repair",
    "late_ack_intervention": "Controller schedule slipped",
}


def require_rejection(name, action):
    """A crash or an unrelated refusal does not qualify a corruption control."""
    try:
        action()
    except ValueError as error:
        expected_type = ValueError if name == "changed_program" else Refused
        require(
            type(error) is expected_type and str(error) == EXPECTED[name],
            "Corruption reached an unexpected rejection: " + name + ": " + str(error),
        )
        return str(error)
    raise Refused("Authored evidence corruption passed: " + name)


def challenge(source):
    names = (
        "missing_snapshot",
        "changed_contract",
        "changed_program",
        "extra_broker_request",
        "corrupted_effect",
        "wrong_barrier_phase",
        "unverified_recurrence",
        "missing_database",
        "missing_corpus",
        "altered_verification_summary",
        "missing_operation_binding",
        "missing_sample",
        "claim_after_request",
        "omitted_intermediate",
        "reordered_intermediate",
        "altered_intermediate",
        "broken_intermediate_time",
        "invalid_acknowledgement",
        "late_ack_intervention",
    )
    receipts = []
    for name in names:
        case = (
            "precise-heartbeat_post_ack"
            if name in {"invalid_acknowledgement", "late_ack_intervention"}
            else "legacy-heartbeat_burst"
            if name in {"missing_database", "missing_corpus"}
            else "precise-heartbeat_burst"
        )
        original = next(source.glob("contract-confirmation-shard-*/cases/" + case))
        positive = evaluate(original)
        with tempfile.TemporaryDirectory(prefix="benefit-negative-") as temporary:
            gate = Path(temporary) / case
            shutil.copytree(original, gate)
            directory = gate / "campaign"
            if name in {
                "missing_snapshot",
                "changed_contract",
                "missing_operation_binding",
                "claim_after_request",
            }:
                with sqlite3.connect(directory / "operations.sqlite") as db:
                    op_id, request_raw = db.execute(
                        "SELECT operation_id,request FROM operations WHERE status='acknowledged' ORDER BY created_at LIMIT 1"
                    ).fetchone()
                    if name == "claim_after_request":
                        db.execute(
                            "UPDATE operation_events SET timestamp='2099-01-01T00:00:00Z' WHERE operation_id=? AND event='dispatching'",
                            (op_id,),
                        )
                    elif name == "missing_operation_binding":
                        db.execute("DELETE FROM operation_contracts WHERE operation_id=?", (op_id,))
                    else:
                        binding = json.loads(
                            db.execute(
                                "SELECT binding FROM operation_contracts WHERE operation_id=?",
                                (op_id,),
                            ).fetchone()[0]
                        )
                        value = binding_for(
                            json.loads(request_raw),
                            LEGACY if name == "changed_contract" else binding["contract_id"],
                        )
                        db.execute(
                            "UPDATE operation_contracts SET binding=? WHERE operation_id=?",
                            (json.dumps(value), op_id),
                        )
            elif name == "changed_program":
                path = directory / "program-definition.json"
                value = read(path)
                value["version"] = "authored-wrong-program"
                save(path, value)
            elif name in {"extra_broker_request", "corrupted_effect"}:
                path = gate / "server-audit.json"
                value = read(path)
                event = next(
                    e
                    for e in value["events"]
                    if e.get("verb") == "patch"
                    and e.get("user", {}).get("username")
                    == "system:serviceaccount:autonomy-lab:broker"
                    and e.get("responseStatus", {}).get("code") == 200
                )
                if name == "extra_broker_request":
                    duplicate = copy.deepcopy(event)
                    duplicate["auditID"] += "-authored-duplicate"
                    value["events"].append(duplicate)
                else:
                    event["responseObject"]["metadata"].setdefault("annotations", {})[
                        "authored/undeclared"
                    ] = "changed"
                save(path, value)
            elif name in {"wrong_barrier_phase", "unverified_recurrence"}:
                path = gate / "record.json"
                value = read(path)
                if name == "wrong_barrier_phase":
                    prepared = next(p for p in value["checkpoints"] if p.get("changes"))
                    intent = next(
                        p
                        for p in value["checkpoints"]
                        if p["operation_id"] == prepared["operation_id"] and p["stage"] == "intent"
                    )
                    intent["changes"] = prepared.pop("changes")
                else:
                    value["second_fault"]["requested_at"] = value["fault"]["finished_at"]
                save(path, value)
            elif name in {
                "omitted_intermediate",
                "reordered_intermediate",
                "altered_intermediate",
                "broken_intermediate_time",
                "invalid_acknowledgement",
                "late_ack_intervention",
            }:
                path = gate / "record.json"
                value = read(path)
                if name == "invalid_acknowledgement":
                    value["post_ack_operation"]["status"] = "prepared"
                elif name == "late_ack_intervention":
                    value["post_ack"]["requested_at"] += 10
                else:
                    point = next(p for p in value["checkpoints"] if p.get("changes"))
                    if name == "omitted_intermediate":
                        point["changes"].pop(0)
                    elif name == "reordered_intermediate":
                        point["changes"].reverse()
                    elif name == "altered_intermediate":
                        point["changes"][0]["response"]["metadata"]["labels"]["authored"] = "damage"
                    else:
                        action = point["changes"][0]
                        point["before_at"] = (action["requested_at"] + action["finished_at"]) / 2
                save(path, value)
            elif name == "missing_sample":
                (directory / "samples/0019.json").unlink()
            else:
                paths = sorted((directory / "samples").glob("*.json"))
                path = next(
                    p for p in paths if read(p)["verification"]["verdict"] == "verified_failure"
                )
                value = read(path)
                verification = value["verification"]
                if name == "altered_verification_summary":
                    verification["counts"]["total"] += 1
                else:
                    from collections import Counter

                    from autonomy_lab.verifier import evaluate_snapshot, load_expectations

                    for probe in verification["probes"]:
                        if name == "missing_database":
                            probe["observations"]["database"] = {
                                "kind": "error",
                                "error": "authored_unavailable",
                            }
                        else:
                            probe["observations"]["quotes"].pop()
                        probe.update(evaluate_snapshot(probe["observations"], load_expectations()))
                    # Preserve a correctly recomputed failing summary. Completeness
                    # must still reject the concealed missing evidence.
                    counts = Counter(p["verdict"] for p in verification["probes"])
                    verification["verdict"] = "verified_failure"
                    verification["reasons"] = list(
                        dict.fromkeys(r for p in verification["probes"] for r in p["reasons"])
                    )
                    verification["counts"] = {
                        "total": len(verification["probes"]),
                        **{
                            k: counts[k]
                            for k in ("verified_success", "verified_failure", "indeterminate")
                        },
                    }
                save(path, value)
            reason = require_rejection(name, lambda: evaluate(gate))
        require(evaluate(original) == positive, "Negative control modified original evidence")
        receipts.append(
            {"name": name, "rejected": True, "reason": reason, "original_unchanged": True}
        )
    declared = plan()
    reason = require_rejection("incomplete_case_inventory", lambda: select(declared, {}))
    receipts.append({"name": "incomplete_case_inventory", "rejected": True, "reason": reason})
    require(len(receipts) == len(names) + 1, "Incomplete negative controls")
    return {
        "scope": "authored corruptions of copied evidence, not live trials",
        "status": "passed",
        "checks": receipts,
    }
