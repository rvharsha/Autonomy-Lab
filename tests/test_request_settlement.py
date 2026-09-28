"""Authored adversarial unit cases; real-service receipts are checked separately."""

import copy
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from autonomy_lab.procedures import Refused
from experiments.request_settlement.audit import settled
from experiments.request_settlement.services import Epoch, Gate, factory


def opened():
    gate = Gate()
    gate.open(Epoch(instance=gate.instance, epoch=1))
    headers = {"x-lab-instance": gate.instance, "x-lab-epoch": "1", "x-lab-operation": "0"}
    return gate, headers


def test_close_fences_delayed_admission_and_never_reopens_old_epoch():
    gate, headers = opened()
    gate.close(Epoch(instance=gate.instance, epoch=1))
    for after_advance in (False, True):
        if after_advance:
            gate.open(Epoch(instance=gate.instance, epoch=2))
        with pytest.raises(HTTPException):
            with gate.operation(headers):
                pytest.fail("Late operation executed")
    assert gate.snapshot()["admitted"] == 0
    with pytest.raises(HTTPException):
        gate.open(Epoch(instance=gate.instance, epoch=1))


def test_close_does_not_finish_actual_worker_or_allow_next_epoch():
    gate, headers = opened()
    started, release = threading.Event(), threading.Event()

    def worker():
        with gate.operation(headers):
            started.set()
            assert release.wait(5)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert started.wait(2)
        snapshot = gate.close(Epoch(instance=gate.instance, epoch=1))
        assert snapshot["closed"] and snapshot["finished"] == 0
        with pytest.raises(HTTPException):
            gate.open(Epoch(instance=gate.instance, epoch=2))
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and gate.snapshot()["finished"] == 1
    gate.open(Epoch(instance=gate.instance, epoch=2))


def test_duplicate_identity_and_restarted_instance_cannot_execute():
    gate, headers = opened()
    with gate.operation(headers):
        with pytest.raises(HTTPException):
            with gate.operation(headers):
                pytest.fail("Duplicate executed")
    with pytest.raises(HTTPException):
        with gate.operation(headers):
            pytest.fail("Finished identity replayed")
    new = Gate()
    with pytest.raises(HTTPException):
        new.open(Epoch(instance=gate.instance, epoch=1))
    assert gate.snapshot()["admitted"] == gate.snapshot()["finished"] == 1


@pytest.mark.parametrize("identity", ["-1", "128", "01", "1.0", " 1", "١"])
def test_noncanonical_or_unbounded_operation_ids_rejected(identity):
    gate, headers = opened()
    headers["x-lab-operation"] = identity
    with pytest.raises(HTTPException):
        with gate.operation(headers):
            pytest.fail("Invalid operation executed")


def receipt():
    quote, inventory = Gate(), Gate()
    for service in (inventory, quote):
        service.open(
            Epoch(
                instance=service.instance,
                epoch=1,
                downstream_instance=inventory.instance if service is quote else None,
            )
        )
        with service.operation(
            {"x-lab-instance": service.instance, "x-lab-epoch": "1", "x-lab-operation": "0"}
        ):
            pass
        service.close(Epoch(instance=service.instance, epoch=1))
    return {"quote": quote.snapshot(), "inventory": inventory.snapshot()}


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("open", "Admission remains open"),
        ("active", "Outstanding or missing"),
        ("drop", "Outstanding or missing"),
        ("forged_empty", "Known admission missing"),
        ("restart", "Instance or epoch changed"),
        ("old", "Instance or epoch changed"),
        ("time", "Invalid terminal time"),
        ("downstream", "Downstream identity differs"),
        ("unissued", "Unissued operation"),
        ("missing_service", "Missing service receipt"),
    ],
)
def test_accept_real_unit_ledger_before_rejecting_corruption(mutation, reason):
    original = receipt()
    instances = {k: v["instance"] for k, v in original.items()}
    assert settled(original, instances, 1, {0}, {0})["settled"]
    r = copy.deepcopy(original)
    if mutation == "open":
        r["inventory"]["closed"] = False
    if mutation == "active":
        r["inventory"]["finished"] = 0
    if mutation == "drop":
        r["inventory"]["operations"].clear()
    if mutation == "forged_empty":
        for service in r.values():
            service.update(admitted=0, finished=0, operations={})
    if mutation == "restart":
        r["inventory"]["instance"] = "0" * 32
    if mutation == "old":
        r["quote"]["epoch"] = 2
    if mutation == "time":
        r["inventory"]["operations"]["0"]["finished"] = float("nan")
    if mutation == "downstream":
        r["quote"]["downstream_instance"] = "0" * 32
    if mutation == "unissued":
        r["inventory"]["operations"]["1"] = r["inventory"]["operations"].pop("0")
    if mutation == "missing_service":
        del r["inventory"]
    with pytest.raises(Refused, match=reason):
        settled(r, instances, 1, {0}, {0})


def test_control_requires_authority_and_data_requires_open_epoch(monkeypatch):
    monkeypatch.setenv("EXPERIMENT_CONTROL_TOKEN", "authored-unit-test-control-token-1234")
    app = factory("inventory")
    with TestClient(app) as client:
        assert client.get("/__experiment/state").status_code == 403
        assert client.get("/inventory/bolt").status_code == 409
        state = client.get(
            "/__experiment/state",
            headers={"x-lab-control": "authored-unit-test-control-token-1234"},
        )
        assert state.status_code == 200 and state.json()["admitted"] == 0


def test_ungated_forwarding_is_explicitly_refused_before_network(monkeypatch):
    import asyncio

    monkeypatch.setenv("EXPERIMENT_CONTROL_TOKEN", "authored-unit-test-control-token-1234")
    monkeypatch.setenv("INVENTORY_URL", "http://127.0.0.1:1")
    app = factory("quote")

    async def exercise():
        async with app.router.lifespan_context(app):
            with pytest.raises(HTTPException) as error:
                await app.state.inventory_client.get("inventory/bolt")
            assert error.value.status_code == 409
            assert app.state.gate.snapshot()["admitted"] == 0

    asyncio.run(exercise())


def test_calibration_keeps_late_transport_and_undispatched_in_population():
    import json
    from pathlib import Path

    from experiments.request_settlement.opportunity import classify

    cases = json.loads(Path("fixtures/expectations.json").read_text())["quotes"]
    records = [
        {
            "index": i,
            "case_id": cases[i % len(cases)]["id"],
            "start": None,
            "end": None,
            "status": None,
            "body": None,
        }
        for i in range(128)
    ]
    records[0].update(start=0.0, end=3.1, status=200, body=json.dumps(cases[0]["body"]))
    records[1].update(start=0.1, end=0.2, error_type="ReadTimeout")
    score, dispatched, known = classify(records, cases, 2)
    assert score == {
        "offered": 128,
        "dispatched": 2,
        "timely_correct": 0,
        "correct": 1,
        "server_errors": 0,
        "transport_errors": 1,
    }
    assert dispatched == {0, 1} and known == {0}
    # This score alone does not establish settlement; the separate receipt is mandatory.
    with pytest.raises(Refused, match="Missing service receipt"):
        settled({}, {}, 1, dispatched, known)


def test_calibration_population_is_balanced_and_all_fixed_choices_included():
    from collections import Counter

    from experiments.request_settlement.opportunity import ACTIONS, schedule

    assert ACTIONS == (1, 2, 4, 8, 16)
    assert schedule(0) != schedule(1)
    for block in (0, 1):
        rows = schedule(block)
        assert len(rows) == 90
        cells = Counter((r["capacity"], r["delay"], r["action"]) for r in rows)
        assert len(cells) == 30 and set(cells.values()) == {3}


def test_successful_downstream_response_cannot_lose_inventory_admission():
    r = receipt()
    instances = {k: v["instance"] for k, v in r.items()}
    assert settled(r, instances, 1, {0}, {0}, {0})["settled"]
    r["inventory"].update(admitted=0, finished=0, operations={})
    with pytest.raises(Refused, match="Known downstream admission missing"):
        settled(r, instances, 1, {0}, {0}, {0})


@pytest.mark.parametrize(
    "field,value",
    [
        ("elapsed_seconds", 600.001),
        ("finished_at", 701),
        ("elapsed_seconds", float("nan")),
        ("started_at", True),
    ],
)
def test_calibration_audit_rejects_overrun_or_invalid_block_clock(field, value):
    from experiments.request_settlement.opportunity import verify_budget

    original = {"started_at": 100.0, "finished_at": 700.0, "elapsed_seconds": 600.0}
    verify_budget(original)
    original[field] = value
    with pytest.raises(Refused):
        verify_budget(original)
