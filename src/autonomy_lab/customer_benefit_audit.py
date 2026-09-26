"""Bind customer-benefit measurements to exact real requests and durable intent."""

import copy
import json
import sqlite3
from contextlib import closing

from autonomy_lab.ambiguity import journal_events
from autonomy_lab.campaign import read
from autonomy_lab.conflict import repair_patch
from autonomy_lab.durable_contract import PRECISE, binding_for, patch_for_binding, validate_binding
from autonomy_lab.durable_contract_gate import without_managed
from autonomy_lab.operation_contract import AUTHORITY, HEARTBEAT, SCRATCH, pointer, visible_resource
from autonomy_lab.procedures import require
from autonomy_lab.recurrence import epoch

BROKER = "system:serviceaccount:autonomy-lab:broker"
MUTATIONS = {"create", "patch", "update", "delete", "deletecollection"}
LABEL = "autonomy-lab/benefit-protected"


def controller_patch(before, kind):
    base = [
        {"op": "test", "path": "/metadata/uid", "value": before["metadata"]["uid"]},
        {
            "op": "test",
            "path": "/metadata/resourceVersion",
            "value": before["metadata"]["resourceVersion"],
        },
    ]
    if kind == "fixture":
        return base + [
            {
                "op": "add",
                "path": "/metadata/annotations",
                "value": {
                    **before["metadata"].get("annotations", {}),
                    HEARTBEAT: "initial",
                    AUTHORITY: "enabled",
                },
            }
        ]
    if kind == "heartbeat":
        return base + [
            {
                "op": "replace",
                "path": "/metadata/annotations/" + pointer(HEARTBEAT),
                "value": "later",
            }
        ]
    if kind == "protected":
        return base + [
            {
                "op": "add",
                "path": "/metadata/labels",
                "value": {**before["metadata"].get("labels", {}), LABEL: "changed"},
            }
        ]
    require(kind in {"fault", "second_fault"}, "Undeclared controller mutation")
    return repair_patch(
        {
            "service_uid": before["metadata"]["uid"],
            "resource_version": before["metadata"]["resourceVersion"],
            "port_name": "http",
            "expected_target_port": 8080,
            "target_port": 9999,
        }
    )


def expected_effect(before, kind):
    wanted = copy.deepcopy(before)
    if kind == "fixture":
        wanted["metadata"].setdefault("annotations", {}).update(
            {HEARTBEAT: "initial", AUTHORITY: "enabled"}
        )
    elif kind == "heartbeat":
        wanted["metadata"]["annotations"][HEARTBEAT] = "later"
    elif kind == "protected":
        wanted["metadata"].setdefault("labels", {})[LABEL] = "changed"
    else:
        wanted["spec"]["ports"][0]["targetPort"] = 8080 if kind == "repair" else 9999
    return visible_resource(wanted)


def bindings(directory):
    with closing(
        sqlite3.connect((directory / "operations.sqlite").as_uri() + "?mode=ro", uri=True)
    ) as db:
        return {
            op: json.loads(value)
            for op, value in db.execute("SELECT operation_id,binding FROM operation_contracts")
        }


def assess_operations(directory, spec, card, record, evidence, captured):
    require(
        captured["collection_closed"] is True and captured["malformed_lines"] == 0,
        "Incomplete audit",
    )
    start, end = card["window"]["start"], card["window"]["end"]
    events = [
        e
        for e in captured["events"]
        if e.get("objectRef", {}).get("namespace") == "autonomy-lab"
        and start <= epoch(e["requestReceivedTimestamp"]) <= end
    ]
    service_writes = [
        e
        for e in events
        if e.get("verb") in MUTATIONS and e.get("objectRef", {}).get("resource") == "services"
    ]
    actor_writes = [
        e
        for e in events
        if e.get("verb") in MUTATIONS
        and e.get("user", {}).get("username")
        in {BROKER, BROKER.replace("broker", "observer"), BROKER.replace("broker", "verifier")}
    ]
    all_bindings, journal = bindings(directory), journal_events(directory)
    operations = card["operations"]
    require(
        {e["operation_id"] for e in journal} == {o["operation_id"] for o in operations},
        "Journal events reference missing operations",
    )
    require(
        set(all_bindings) == {o["operation_id"] for o in operations},
        "Missing or extra operation binding",
    )
    checkpoints = record["checkpoints"]
    require(
        len({(p["stage"], p["operation_id"]) for p in checkpoints}) == len(checkpoints),
        "Duplicate controller barrier",
    )
    seen, dispatches, timing, unsent = set(), [], [], []

    def scoped(event, actor, verb):
        return (
            event.get("stage") == "ResponseComplete"
            and event.get("verb") == verb
            and event.get("user", {}).get("username") == actor
            and event.get("objectRef", {}).get("resource") == "services"
            and event.get("objectRef", {}).get("name") == "inventory"
        )

    def observed(value, lower, upper, actor="kubernetes-admin"):
        require(
            any(
                scoped(e, actor, "get")
                and e["responseStatus"]["code"] == 200
                and lower
                <= epoch(e["requestReceivedTimestamp"])
                <= epoch(e["stageTimestamp"])
                <= upper
                and without_managed(e["responseObject"]) == without_managed(value)
                for e in events
            ),
            "Observation lacks its actual scoped API read",
        )

    controls = [record[name] for name in ("fixture", "fault", "second_fault") if name in record]
    controls.extend(p["change"] for p in checkpoints if "change" in p)
    require(
        {c["kind"] for c in controls}
        <= {"fixture", "fault", "second_fault", "heartbeat", "protected"},
        "Unknown intervention",
    )
    require(
        sum(c["kind"] == "fixture" for c in controls)
        == sum(c["kind"] == "fault" for c in controls)
        == 1,
        "Initial setup/fault missing",
    )
    for action in controls:
        require(
            action["patch"] == controller_patch(action["before"], action["kind"]),
            "Controller action changed scope",
        )
        observed(action["before"], start, action["requested_at"])
        matches = [
            e
            for e in service_writes
            if scoped(e, "kubernetes-admin", "patch")
            and e.get("userAgent") == "autonomy-lab-operation/" + action["tag"]
            and e.get("requestObject") == action["patch"]
            and e["responseStatus"]["code"] == 200
            and action["requested_at"]
            <= epoch(e["requestReceivedTimestamp"])
            <= epoch(e["stageTimestamp"])
            <= action["finished_at"]
        ]
        require(
            len(matches) == 1 and matches[0]["auditID"] not in seen,
            "Controller request not uniquely attributed",
        )
        event = matches[0]
        seen.add(event["auditID"])
        require(
            event["responseObject"] == action["response"]
            and visible_resource(event["responseObject"])
            == expected_effect(action["before"], action["kind"]),
            "Controller effect differs",
        )
    require(
        record["fixture"]["finished_at"] <= record["fault"]["requested_at"],
        "Fixture applied after fault",
    )
    first_intents = [p for p in checkpoints if p["phase"] == "first" and p["stage"] == "intent"]
    first = min(first_intents, key=lambda p: p["barrier"]["at"]) if first_intents else None
    expected_change = "intent" if spec["context"] == "heartbeat_before" else "preflight"
    changes = [p for p in checkpoints if "change" in p]
    if spec["context"] == "quiet":
        require(not changes, "Undeclared quiet-context conflict")
        exposed = first is not None
    else:
        require(len(changes) <= 1, "Multiple injected conflicts")
        exposed = bool(changes)
        if changes:
            point = changes[0]
            require(
                first is not None
                and point["operation_id"] == first["operation_id"]
                and point["phase"] == "first"
                and point["stage"] == expected_change
                and point["change"]["kind"]
                == ("protected" if spec["context"] == "protected_after" else "heartbeat"),
                "Conflict placed at wrong causal boundary",
            )
    all_proposals = []
    for worker, episodes in evidence.items():
        for episode in episodes:
            records = episode["records"]
            for i, tool in enumerate(records):
                if tool["source"] != "propose_repair":
                    continue
                result = tool["payload"]
                ids = {r["observation_id"] for r in records[:i]}
                require(
                    result["request"]["evidence_ids"]
                    and set(result["request"]["evidence_ids"]) <= ids,
                    "Proposal lacks earlier episode observations",
                )
                all_proposals.append((worker, episode["id"], tool))
    require(
        len(all_proposals) == len(operations)
        and {r[2]["payload"]["operation_id"] for r in all_proposals}
        == {o["operation_id"] for o in operations},
        "Submitted proposals and journal differ",
    )
    for op in operations:
        op_id, request = op["operation_id"], json.loads(op["request"])
        binding = all_bindings[op_id]
        validate_binding(request, binding)
        require(
            binding["contract_id"] == spec["contract"]["operation_contract"],
            "Execution contract differs from candidate",
        )
        require(
            request["run_id"] == record["run_id"]
            and request["namespace"] == "autonomy-lab"
            and request["service_name"] == "inventory"
            and request["service_uid"] == card["identities_before"]["Service/inventory"]
            and request["port_name"] == "http"
            and request["expected_target_port"] == 9999
            and request["target_port"] == 8080,
            "Operation authority differs",
        )
        owner, episode_id, tool = next(
            t for t in all_proposals if t[2]["payload"]["operation_id"] == op_id
        )
        phase = next((p for p in ("first", "second") if record[p + "_worker"] == owner), None)
        require(phase is not None, "Unexpected initial operator mutation")
        payload = tool["payload"]
        require(
            all(payload[k] == op[k] for k in ("operation_id", "run_id", "status", "reason"))
            and payload["request"] == request
            and payload["result"] == json.loads(op["result"] or "null"),
            "Tool result differs from journal",
        )
        pin = read(directory / "workers" / owner / episode_id / "program.json")
        require(
            pin["pin"] == spec["program_pin"]
            and pin["at"] <= epoch(op["created_at"]) <= epoch(tool["timestamp"]),
            "Proposal lacks prior program identity",
        )
        prior_observations = [
            t
            for e in evidence[owner]
            if e["id"] == episode_id
            for t in e["records"]
            if t["observation_id"] in request["evidence_ids"] and t["source"] == "observe_service"
        ]
        require(
            any(
                t["payload"].get("service", {}).get("metadata", {}).get("resourceVersion")
                == request["resource_version"]
                for t in prior_observations
            ),
            "Proposal version has no episode observation",
        )
        actual = [
            e for e in service_writes if e.get("userAgent") == "autonomy-lab-operation/" + op_id
        ]
        points = [p for p in checkpoints if p["operation_id"] == op_id]
        events_for_op = [e for e in journal if e["operation_id"] == op_id]
        intents = [p for p in points if p["stage"] == "intent"]
        preflights = [p for p in points if p["stage"] == "preflight"]
        is_budget = op["reason"] == "budget_exhausted"
        require(
            len(intents) == (0 if is_budget else 1) and len(preflights) <= 1,
            "Missing or extra causal barrier",
        )
        require(
            bool(events_for_op)
            and epoch(op["created_at"]) <= epoch(events_for_op[0]["timestamp"])
            and epoch(op["updated_at"])
            <= epoch(events_for_op[-1]["timestamp"])
            <= epoch(tool["timestamp"])
            and [epoch(e["timestamp"]) for e in events_for_op]
            == sorted(epoch(e["timestamp"]) for e in events_for_op),
            "Journal timestamps contradict operation/tool evidence",
        )
        if intents:
            require(
                epoch(events_for_op[0]["timestamp"]) <= intents[0]["barrier"]["at"],
                "Intent barrier preceded durable intent",
            )
        for point in points:
            require(
                point["stage"] in {"intent", "preflight"}
                and point["phase"] == phase
                and point["barrier"]["operation_id"] == op_id
                and record[phase + "_requested_at"]
                <= point["barrier"]["at"]
                <= point["before_at"]
                <= point["after_at"]
                <= point["release_requested_at"]
                <= (start + spec["first_stop_offset"] if phase == "first" else end),
                "Barrier timing differs",
            )
            folder = directory / "workers" / owner / point["stage"] / op_id
            require(
                read(folder / (point["stage"] + "-barrier.json")) == point["barrier"]
                and read(folder / (point["stage"] + "-release.json")) == {"operation_id": op_id},
                "Barrier receipt differs",
            )
            require(
                point["operation"]["operation_id"] == op_id
                and point["operation"]["status"] == "prepared"
                and json.loads(point["operation"]["request"]) == request
                and point["operation"]["budget_reserved"] == 1,
                "Barrier did not hold original reserved intent",
            )
            require(
                point["binding"]
                == (
                    binding_for(request, binding["contract_id"])
                    if point["stage"] == "intent"
                    else binding
                ),
                "Conditions were replaced across preparation",
            )
            observed(point["before"], point["barrier"]["at"], point["before_at"])
            observed(point["after"], point["before_at"], point["after_at"])
            require(
                visible_resource(point["after"])
                == (
                    expected_effect(point["before"], point["change"]["kind"])
                    if "change" in point
                    else visible_resource(point["before"])
                ),
                "Unexpected barrier effect",
            )
            if "change" in point:
                require(
                    point["before_at"]
                    <= point["change"]["requested_at"]
                    <= point["change"]["finished_at"]
                    <= point["after_at"]
                    and point["change"]["before"] == point["before"],
                    "Intervention outside barrier",
                )
        require(op["reconciliation"] is None, "Unexpected reconciliation in completed comparison")
        require(
            op["status"] in {"acknowledged", "rejected"},
            "Unresolved operation cannot qualify this comparison",
        )
        if actual:
            require(
                len(actual) == 1 and len(preflights) == 1 and op["budget_reserved"] == 1,
                "Replay or missing prepared dispatch",
            )
            event, prepared, intent = actual[0], preflights[0], intents[0]
            require(
                intent["release_requested_at"] <= prepared["barrier"]["at"],
                "Preflight preceded intent release",
            )
            patch = (
                patch_for_binding(request, binding)
                if binding["contract_id"] == PRECISE
                else repair_patch(request)
            )
            require(
                scoped(event, BROKER, "patch") and event.get("requestObject") == patch,
                "API request differs from complete versioned guard",
            )
            require(
                prepared["release_requested_at"]
                <= epoch(event["requestReceivedTimestamp"])
                <= epoch(event["stageTimestamp"])
                <= epoch(op["updated_at"]),
                "API dispatch outside durable sequence",
            )
            claims = [e for e in events_for_op if e["event"] == "dispatching"]
            require(
                len(claims) == 1
                and prepared["release_requested_at"]
                <= epoch(claims[0]["timestamp"])
                <= epoch(event["requestReceivedTimestamp"]),
                "API request preceded durable dispatch claim",
            )
            code = event["responseStatus"]["code"]
            require(
                code in {200, 409, 422}
                and op["status"] == ("acknowledged" if code == 200 else "rejected")
                and op["reason"]
                == ("api_acknowledged" if code == 200 else "api_rejected_" + str(code)),
                "API outcome differs",
            )
            if "change" in prepared and (
                prepared["change"]["kind"] == "protected" or binding["contract_id"] != PRECISE
            ):
                require(code != 200, "Protected or legacy version conflict was applied")
            if code != 200:
                require(
                    json.loads(op["result"] or "null") is None,
                    "Refused request has an acknowledgement",
                )
            if code == 200:
                require(
                    visible_resource(event["responseObject"])
                    == expected_effect(prepared["after"], "repair")
                    and SCRATCH not in event["responseObject"],
                    "Repair changed more than targetPort",
                )
                metadata = event["responseObject"]["metadata"]
                require(
                    json.loads(op["result"])
                    == {
                        "service_uid": metadata["uid"],
                        "resource_version": metadata["resourceVersion"],
                    },
                    "Acknowledgement differs from API response",
                )
            if binding["contract_id"] == PRECISE:
                require(binding["snapshot"] is not None, "Missing trusted precise snapshot")
                observed(
                    binding["snapshot"],
                    intent["release_requested_at"],
                    prepared["barrier"]["at"],
                    BROKER,
                )
            require(event["auditID"] not in seen, "Duplicate audit identity")
            seen.add(event["auditID"])
            dispatches.append(op)
            timing.append(
                {
                    "operation_id": op_id,
                    "api_seconds": epoch(event["stageTimestamp"])
                    - epoch(event["requestReceivedTimestamp"]),
                    "intent_to_request_seconds": epoch(event["requestReceivedTimestamp"])
                    - epoch(op["created_at"]),
                }
            )
            expected_events = (
                ["prepared"]
                + (["conditions_recorded"] if binding["contract_id"] == PRECISE else [])
                + ["dispatching", op["status"]]
            )
        else:
            require(
                op["status"] == "rejected"
                and op["budget_reserved"] == 0
                and not preflights
                and op["reason"] in {"budget_exhausted", "resource_version_changed"},
                "Invalid unsent refusal",
            )
            require(
                binding["snapshot"] is None and json.loads(op["result"] or "null") is None,
                "Unsent refusal has conditions or result",
            )
            unsent.append({"operation_id": op_id, "reason": op["reason"], "phase": phase})
            if not is_budget:
                require(
                    spec["context"] == "heartbeat_before"
                    and phase == "first"
                    and len(changes) == 1
                    and changes[0]["operation_id"] == op_id,
                    "Unsent conflict lacks early intervention",
                )
                point = intents[0]
                observed(
                    point["after"], point["release_requested_at"], epoch(op["updated_at"]), BROKER
                )
            expected_events = (
                ["rejected"] if is_budget else ["prepared", "rejected", "budget_released"]
            )
        require(
            [e["event"] for e in events_for_op] == expected_events,
            "Journal transition sequence differs",
        )
        recorded_conditions = [e for e in events_for_op if e["event"] == "conditions_recorded"]
        if recorded_conditions:
            require(
                intents[0]["release_requested_at"]
                <= epoch(recorded_conditions[0]["timestamp"])
                <= preflights[0]["barrier"]["at"],
                "Snapshot was not durable before prepared dispatch",
            )
            require(
                recorded_conditions[0]["details"] == {"binding_sha256": binding["binding_sha256"]},
                "Snapshot receipt differs",
            )
    require(
        {p["operation_id"] for p in checkpoints}
        == {o["operation_id"] for o in operations if o["reason"] != "budget_exhausted"},
        "Checkpoint lacks its actual operation",
    )
    require(
        len(service_writes) == len(seen) and {e["auditID"] for e in service_writes} == seen,
        "Undeclared Service write or replay",
    )
    require(
        {e["auditID"] for e in actor_writes}
        == {e["auditID"] for e in service_writes if e.get("user", {}).get("username") == BROKER}
        and len(actor_writes) == len(dispatches),
        "Undeclared actor mutation",
    )
    require(
        card["dispatch_budget_reserved"] == len(dispatches) <= 2,
        "Cumulative dispatch budget differs",
    )
    first_ops = [
        o for o in operations if epoch(o["created_at"]) < record["first_stop_requested_at"]
    ]
    require(record["operations_first"] == first_ops, "First-phase journal changed after restart")
    spent_first = sum(o["budget_reserved"] for o in first_ops)
    for op in operations:
        if op["reason"] == "budget_exhausted":
            require(
                sum(epoch(d["updated_at"]) <= epoch(op["created_at"]) for d in dispatches) == 2,
                "Budget refusal without prior spent capacity",
            )
    # Every later scoped read must equal the last acknowledged mutation's state.
    # This also catches partial effects after definitive API refusal.
    successful = sorted(
        [e for e in service_writes if e["responseStatus"]["code"] == 200],
        key=lambda e: epoch(e["stageTimestamp"]),
    )
    for event in events:
        if not (
            event.get("verb") == "get"
            and event.get("objectRef", {}).get("resource") == "services"
            and event.get("objectRef", {}).get("name") == "inventory"
            and event.get("responseStatus", {}).get("code") == 200
        ):
            continue
        preceding = [
            w
            for w in successful
            if epoch(w["stageTimestamp"]) <= epoch(event["requestReceivedTimestamp"])
        ]
        overlapping = [
            w
            for w in service_writes
            if epoch(w["requestReceivedTimestamp"]) < epoch(event["stageTimestamp"])
            and epoch(event["requestReceivedTimestamp"]) < epoch(w["stageTimestamp"])
        ]
        if preceding and not overlapping:
            require(
                visible_resource(event["responseObject"])
                == visible_resource(preceding[-1]["responseObject"]),
                "Persisted state differs after last acknowledged mutation",
            )
    return {
        "dispatch_rows": dispatches,
        "journal": journal,
        "intervention_exposed": exposed,
        "unsent_refusals": unsent,
        "conditional_rejections": sum(o["status"] == "rejected" for o in dispatches),
        "remaining_after_first": 2 - spent_first,
        "dispatch_timing": timing,
    }
