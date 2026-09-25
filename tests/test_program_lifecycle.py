"""Authored evidence corruption tests; live outcomes come only from Kubernetes."""

import copy
import json

import pytest
from test_conflict import stamp
from test_refresh import authored as refresh_authored

from autonomy_lab import program_lifecycle as p
from autonomy_lab.procedures import Refused


def authored(between):
    fixture = refresh_authored(stable=False)
    card, record, evidence, journal = (
        fixture[k] for k in ["card", "record", "evidence", "journal"]
    )
    fixture["spec"] = p.declaration(
        "between_attempts" if between else "before_first", "experiment-01234567"
    )
    card["contract"] = fixture["spec"]["contract"]
    card["dispatch_budget_reserved"] = int(between)
    op = card["operations"][-1 if between else 0]
    op.update(
        reason="dispatch_authorization_refused",
        budget_reserved=0,
        result=None,
        updated_at=stamp(1051.1 if between else 1049.1),
    )
    card["operations"][0]["updated_at"] = stamp(1049.4 if between else 1049.1)
    if between:
        # Broker._finish stores JSON null in the SQLite result column.
        card["operations"][0]["result"] = "null"
    start = 1050.7 if between else 1048.1
    record["withdrawal"] = {"requested_at": start, "finished_at": start + 0.1}
    if between:
        record["attempts"][1].pop("change")
        record["attempts"][1].pop("changed_service")
        del fixture["captured"]["events"][3:]
        journal[4:] = [
            {
                "event": kind,
                "operation_id": op["operation_id"],
                "timestamp": stamp(1051.1001 + index * 0.0001),
                "details": {},
            }
            for index, kind in enumerate(["rejected", "budget_released"])
        ]
        after = record["changed_service"]
    else:
        del card["operations"][1:]
        del record["attempts"][1:]
        record["attempts"][0].pop("change")
        record["attempts"][0].pop("changed_service")
        del fixture["captured"]["events"][1:]
        journal[1:] = [
            {
                "event": kind,
                "operation_id": op["operation_id"],
                "timestamp": stamp(1049.1001 + index * 0.0001),
                "details": {},
            }
            for index, kind in enumerate(["rejected", "budget_released"])
        ]
        after = record["before_change"]
    record["after_operations"] = copy.deepcopy(after)
    tools = evidence["operator-repair"][0]["records"]
    if not between:
        tools[:] = tools[:4] + tools[-1:]
    for i, operation in enumerate(card["operations"]):
        tools[i * 4 + 3]["payload"].update(operation)
        tools[i * 4 + 3]["payload"].update(
            request=json.loads(operation["request"]),
            budget_used=int(between),
            budget_reserved=bool(operation["budget_reserved"]),
        )
    # Routing changes also produce ordinary Kubernetes controller writes.
    for resource, controller in [("endpoints", "endpoint-controller"),
                                 ("endpointslices", "endpointslice-controller")]:
        event = copy.deepcopy(fixture["captured"]["events"][0])
        event.update(auditID="authored-" + resource, verb="update",
                     user={"username": "system:serviceaccount:kube-system:" + controller})
        event["objectRef"]["resource"] = resource
        fixture["captured"]["events"].insert(1, event)
    return {
        **{k: fixture[k] for k in ["card", "spec", "record", "journal", "captured", "evidence"]},
        "samples": fixture["raw_samples"],
    }


@pytest.mark.parametrize("between", [False, True])
def test_refused_authorization_preserves_customer_failure_and_prior_budget(between):
    assert p.assess_refused(**authored(between)) is True


@pytest.mark.parametrize("between", [False, True])
@pytest.mark.parametrize("damage", ["row_after_event", "row_before_release", "event_after_result"])
def test_refused_journal_timestamps_must_follow_real_write_order(between, damage):
    f = authored(between)
    op = f["card"]["operations"][-1]
    if damage == "row_after_event":
        op["updated_at"] = stamp(1051.2 if between else 1049.2)
    elif damage == "row_before_release":
        op["updated_at"] = stamp(1050 if between else 1048)
    else:
        f["journal"][-1]["timestamp"] = stamp(1060)
    with pytest.raises(Refused):
        p.assess_refused(**f)


@pytest.mark.parametrize("result", ['{"acknowledged":true}', "false", "0", '"null"', ""])
def test_actual_api_rejection_cannot_contain_a_non_null_result(result):
    f = authored(True)
    f["card"]["operations"][0]["result"] = result
    with pytest.raises(ValueError):
        p.assess_refused(**f)


def test_api_rejection_row_cannot_predate_the_actual_response():
    f = authored(True)
    f["card"]["operations"][0]["updated_at"] = stamp(1049.05)
    with pytest.raises(Refused):
        p.assess_refused(**f)


@pytest.mark.parametrize("identity", [
    "system:serviceaccount:autonomy-lab:" + role
    for role in ["broker", "observer", "verifier", "operator-repair", "default"]
] + ["kubernetes-admin", "system:anonymous", "system:serviceaccount:kube-system:unknown"])
def test_actor_mutation_outside_services_cannot_hide_as_controller_work(identity):
    f = authored(True)
    event = next(e for e in f["captured"]["events"] if e["objectRef"]["resource"] == "endpointslices")
    event["user"]["username"] = identity
    with pytest.raises(Refused):
        p.assess_refused(**f)


@pytest.mark.parametrize("damage", ["other_resource", "other_controller", "other_verb"])
def test_native_controller_exception_is_limited_to_its_derived_updates(damage):
    f = authored(True)
    event = next(e for e in f["captured"]["events"] if e["objectRef"]["resource"] == "endpointslices")
    if damage == "other_resource":
        event["objectRef"]["resource"] = "deployments"
    elif damage == "other_controller":
        event["user"]["username"] = "system:serviceaccount:kube-system:endpoint-controller"
    else:
        event["verb"] = "delete"
    with pytest.raises(Refused):
        p.assess_refused(**f)


@pytest.mark.parametrize(
    "damage",
    [
        "api_after_withdrawal",
        "hidden_write",
        "extra_operation",
        "released_prior_budget",
        "spent_refused_budget",
        "late_withdrawal",
        "wrong_refusal",
        "wrong_request",
        "missing_api_rejection",
        "wrong_api_patch",
        "same_resource_version",
        "extra_tools",
        "changed_payload",
        "late_claim",
        "wrong_customer",
        "unknown_sample",
        "missing_sample",
        "new_workload",
        "missing_cleanup",
        "open_audit",
        "corrupt_audit",
        "changed_final_state",
        "late_preparation",
        "changed_fault",
        "early_refresh",
        "no_customer_failure",
        "extra_journal",
    ],
)
def test_corrupt_withdrawal_evidence_cannot_pass(damage):
    f = authored(True)
    card = f["card"]
    record = f["record"]
    events = f["captured"]["events"]
    tools = f["evidence"]["operator-repair"][0]["records"]
    if damage == "api_after_withdrawal":
        events.append(
            {
                **copy.deepcopy(events[-1]),
                "auditID": "extra",
                "userAgent": "autonomy-lab-operation/authored-second",
            }
        )
    elif damage == "hidden_write":
        events.append(
            {**copy.deepcopy(events[-1]), "auditID": "hidden", "responseStatus": {"code": 200}}
        )
    elif damage == "extra_operation":
        card["operations"].append(copy.deepcopy(card["operations"][1]))
    elif damage == "released_prior_budget":
        card["operations"][0]["budget_reserved"] = 0
    elif damage == "spent_refused_budget":
        card["operations"][1]["budget_reserved"] = 1
    elif damage == "late_withdrawal":
        record["withdrawal"]["finished_at"] = 1052
    elif damage == "wrong_refusal":
        card["operations"][1]["reason"] = "precondition_failed"
    elif damage == "wrong_request":
        request = json.loads(card["operations"][1]["request"])
        request["service_uid"] = "different"
        card["operations"][1]["request"] = json.dumps(request)
    elif damage == "missing_api_rejection":
        events.pop()
    elif damage == "wrong_api_patch":
        events[-1]["requestObject"][-1]["value"] = 9000
    elif damage == "same_resource_version":
        request = json.loads(card["operations"][1]["request"])
        request["resource_version"] = "2"
        card["operations"][1]["request"] = json.dumps(request)
    elif damage == "extra_tools":
        tools.insert(-1, copy.deepcopy(tools[7]))
    elif damage == "changed_payload":
        tools[7]["payload"]["budget_used"] = 2
    elif damage == "late_claim":
        card["workers"][2]["episodes"][0]["outcome"]["finished_at"] = 1100
    elif damage == "wrong_customer":
        card["samples"][8]["verdict"] = "verified_success"
        card["sample_counts"]["verified_success"] = 4
    elif damage == "unknown_sample":
        card["sample_counts"]["unknown"] = 1
    elif damage == "missing_sample":
        card["samples"].pop()
    elif damage == "new_workload":
        card["identities_unchanged"] = False
    elif damage == "missing_cleanup":
        card["cleanup"]["status"] = "failed"
    elif damage == "open_audit":
        f["captured"]["collection_closed"] = False
    elif damage == "corrupt_audit":
        f["captured"]["malformed_lines"] = 1
    elif damage == "changed_final_state":
        record["after_operations"]["spec"]["ports"][0]["targetPort"] = 8080
    elif damage == "late_preparation":
        record["attempts"][0]["barrier"]["at"] = 1070
    elif damage == "changed_fault":
        record["fault"]["patch"][-1]["value"] = 9998
    elif damage == "early_refresh":
        tools[4]["timestamp"] = stamp(1049)
    elif damage == "no_customer_failure":
        f["samples"] = []
    else:
        f["journal"].append(copy.deepcopy(f["journal"][-1]))
    with pytest.raises((Refused, KeyError, ValueError, IndexError)):
        p.assess_refused(**f)


def test_declarations_pin_all_cases_before_any_execution():
    specs = [p.declaration(case, "experiment-01234567") for case in p.CASES]
    assert {s["program_lifecycle_case"] for s in specs} == {
        "stable",
        "before_first",
        "between_attempts",
        "uncertain",
    }
    assert all(s["contract"]["admit_program"] is True for s in specs)
    assert len({s["program_pin"]["version"] for s in specs}) == 1
    with pytest.raises(Refused):
        p.declaration("stable", "../experiment-01234567")


def admission_fixture(tmp_path, withdrawn=True):
    from autonomy_lab.harness import save
    from autonomy_lab.procedures import encoded
    from autonomy_lab.program_admission import request_digest

    f = authored(True)
    op = copy.deepcopy(f["card"]["operations"][0])
    episode_id = "episode-admitted"
    receipt = {
        "version": "authored-evaluated",
        "eligible": True,
        "definition": {"program": {"version": "authored-program"}},
    }
    promoted = {"revision": 1, "kind": "promoted", "version": receipt["version"]}
    selected = {"episode": episode_id, "version": receipt["version"], "revision": 1}
    pin = {**selected, "program_version": "authored-program", "at": 1046}
    episode = {
        "id": episode_id,
        "attempt": {"started_at": 1045.9},
        "outcome": {"claim": {"outcome": "escalated"}},
    }
    card = {"operations": [op], "workers": [{"id": "operator-authored", "episodes": [episode]}]}
    evidence = {
        "operator-authored": [
            {
                "id": episode_id,
                "records": [
                    {"observation_id": "o" + str(i), "timestamp": stamp(1046.1 + i * 0.1)}
                    for i in range(3)
                ],
                "uncommitted_bytes": 0,
            }
        ]
    }
    directory = tmp_path / "campaign"
    path = directory / "workers/operator-authored" / episode_id
    path.mkdir(parents=True)
    save(directory / "admission.json", promoted)
    save(path / "procedure.json", pin)
    decisions = [{"revision": 1, "kind": "promoted", "receipt": encoded(receipt).decode()}]
    record = {"admission": promoted}
    if withdrawn:
        decisions.append(
            {
                "revision": 2,
                "kind": "withdrawn",
                "receipt": encoded({"version": receipt["version"]}).decode(),
            }
        )
        record["withdrawal"] = {
            "requested_at": 1050,
            "finished_at": 1050.1,
            "decision": {"revision": 2, "kind": "withdrawn", "version": receipt["version"]},
        }
    admitted = {
        "decisions": decisions,
        "versions": [
            {
                "version": receipt["version"],
                "definition": encoded(receipt["definition"]).decode(),
                "withdrawn": int(withdrawn),
            }
        ],
        "state": [
            {
                "id": 1,
                "revision": 2 if withdrawn else 1,
                "active": None if withdrawn else receipt["version"],
                "active_revision": None if withdrawn else 1,
            }
        ],
        "pins": [selected],
        "refusals": [],
        "authorizations": [
            {
                "operation_id": op["operation_id"],
                "episode": episode_id,
                "version": receipt["version"],
                "activation_revision": 1,
                "decision_revision": 1,
                "program_version": "authored-program",
                "request_sha256": request_digest(json.loads(op["request"])),
                "authorized_at": 1047.5,
            }
        ],
    }
    return {
        "directory": directory,
        "card": card,
        "evidence": evidence,
        "journal": f["journal"][:3],
        "record": record,
        "receipt": receipt,
        "admitted": admitted,
        "withdrawn": withdrawn,
    }


@pytest.mark.parametrize("withdrawn", [True, False])
def test_offline_authorization_uses_activating_revision_and_original_request(tmp_path, withdrawn):
    assert p.verify_admission(**admission_fixture(tmp_path, withdrawn)) == []


@pytest.mark.parametrize(
    "defect",
    [
        "missing_auth",
        "duplicate_auth",
        "late_auth",
        "before_prepare",
        "wrong_request",
        "wrong_program",
        "wrong_episode",
        "post_withdrawal_revision",
        "bool_revision",
        "wrong_activation",
        "changed_decision",
        "changed_definition",
        "active_after_withdrawal",
        "unpinned",
        "late_pin",
        "wrong_pin",
        "false_eligible",
        "extra_refusal",
        "wrong_evidence",
    ],
)
def test_offline_admission_cannot_pass_contradictory_authorization(tmp_path, defect):
    from autonomy_lab.campaign import read
    from autonomy_lab.harness import save

    f = admission_fixture(tmp_path)
    auth = f["admitted"]["authorizations"][0]
    if defect == "missing_auth":
        f["admitted"]["authorizations"] = []
    elif defect == "duplicate_auth":
        f["admitted"]["authorizations"].append(copy.deepcopy(auth))
    elif defect == "late_auth":
        auth["authorized_at"] = 1051
    elif defect == "before_prepare":
        auth["authorized_at"] = 1046.5
    elif defect == "wrong_request":
        auth["request_sha256"] = "changed"
    elif defect == "wrong_program":
        auth["program_version"] = "changed"
    elif defect == "wrong_episode":
        auth["episode"] = "other"
    elif defect == "post_withdrawal_revision":
        auth["decision_revision"] = 2
    elif defect == "bool_revision":
        auth["decision_revision"] = True
    elif defect == "wrong_activation":
        auth["activation_revision"] = 2
    elif defect == "changed_decision":
        f["admitted"]["decisions"][0]["receipt"] = "{}"
    elif defect == "changed_definition":
        f["admitted"]["versions"][0]["definition"] = "{}"
    elif defect == "active_after_withdrawal":
        f["admitted"]["state"][0]["active"] = f["receipt"]["version"]
    elif defect in {"unpinned", "late_pin", "wrong_pin"}:
        path = next(f["directory"].glob("workers/*/*/procedure.json"))
        if defect == "unpinned":
            path.unlink()
        else:
            pin = read(path)
            if defect == "late_pin":
                pin["at"] = 1048
            else:
                pin["program_version"] = "changed"
            save(path, pin)
    elif defect == "false_eligible":
        f["receipt"]["eligible"] = False
    elif defect == "extra_refusal":
        f["admitted"]["refusals"] = [{"action": "start_episode", "details": "{}"}]
    else:
        f["evidence"]["operator-authored"][0]["records"].pop()
    with pytest.raises((Refused, KeyError, ValueError)):
        p.verify_admission(**f)
