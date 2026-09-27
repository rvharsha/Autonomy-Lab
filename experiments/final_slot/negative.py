"""Authored damage to copied real evidence; never live experiment outcomes."""

import hashlib
import shutil
import tempfile
from pathlib import Path

from autonomy_lab.campaign import read
from autonomy_lab.harness import save
from autonomy_lab.procedures import Refused, require
from experiments.contract_confirmation import negative as shared

from .gate import evaluate, plan, select

EXPECTED = {
    **{
        k: v
        for k, v in shared.EXPECTED.items()
        if k not in {"invalid_acknowledgement", "late_ack_intervention"}
    },
    "wrong_operation": "Conflict placed at wrong causal boundary",
    "prior_budget": "First repair did not leave one dispatch slot",
    "prior_acknowledgement": "First repair did not leave one dispatch slot",
    "early_change_late": "Early protected change not completed before second worker",
    "early_change_missing": "Early protected change not completed before second worker",
}


def require_rejection(name, action):
    try:
        action()
    except ValueError as error:
        wanted_type = ValueError if name == "changed_program" else Refused
        require(
            type(error) is wanted_type and str(error) == EXPECTED[name],
            "Corruption reached an unexpected rejection: " + name + ": " + str(error),
        )
        return str(error)
    raise Refused("Authored evidence corruption passed: " + name)


def corrupt_record(value, name):
    if name == "wrong_operation":
        point = next(p for p in value["checkpoints"] if p.get("changes"))
        first = next(
            p for p in value["checkpoints"] if p["phase"] == "first" and p["stage"] == "preflight"
        )
        require(point is not first, "Wrong-operation corruption needs a later original conflict")
        first["changes"] = point.pop("changes")
    elif name == "prior_budget":
        value["operations_first"][0]["budget_reserved"] = 0
    elif name == "prior_acknowledgement":
        value["operations_first"][0]["status"] = "prepared"
    elif name == "early_change_late":
        value["early_change"]["finished_at"] = value["second_requested_at"] + 1
    elif name == "early_change_missing":
        del value["early_change"]
    else:
        raise ValueError("Unknown final-slot record corruption")


def apply_corruption(gate, name):
    if name in shared.EXPECTED:
        require(
            name
            not in {
                "invalid_acknowledgement",
                "late_ack_intervention",
                "incomplete_case_inventory",
            },
            "Control is outside final-slot evidence",
        )
        shared.apply_corruption(gate, name)
    else:
        value = read(gate / "record.json")
        corrupt_record(value, name)
        save(gate / "record.json", value)


def manifest(path):
    return {
        str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def challenge(source):
    names = [name for name in EXPECTED if name != "incomplete_case_inventory"]
    receipts = []
    for name in names:
        case = (
            "precise-protected_before"
            if name.startswith("early_change_")
            else "precise-protected_final"
        )
        paths = list(source.glob("final-slot-shard-*/cases/" + case))
        require(len(paths) == 1, "Missing or duplicate control source case")
        original = paths[0]
        positive, before = evaluate(original), manifest(original)
        with tempfile.TemporaryDirectory(prefix="final-slot-negative-") as temporary:
            gate = Path(temporary) / case
            shutil.copytree(original, gate)
            apply_corruption(gate, name)
            reason = require_rejection(name, lambda: evaluate(gate))
        require(
            manifest(original) == before and evaluate(original) == positive,
            "Negative control modified original evidence",
        )
        receipts.append(
            {"name": name, "rejected": True, "reason": reason, "original_unchanged": True}
        )
    declared = plan()
    reason = require_rejection("incomplete_case_inventory", lambda: select(declared, {}))
    receipts.append({"name": "incomplete_case_inventory", "rejected": True, "reason": reason})
    require(len(receipts) == len(EXPECTED), "Incomplete negative controls")
    return {
        "scope": "authored corruptions of copied evidence, not live trials",
        "status": "passed",
        "checks": receipts,
    }
