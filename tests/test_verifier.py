"""Isolated oracle and transport tests; these are not end-to-end evidence."""

from copy import deepcopy

import httpx
import pytest

from autonomy_lab.verifier import (
    FAILURE,
    INDETERMINATE,
    SUCCESS,
    _http_observation,
    evaluate_snapshot,
    load_expectations,
    run_window,
)


@pytest.fixture
def expectations():
    return load_expectations()


@pytest.fixture
def healthy(expectations):
    return {
        "quote_control": {"kind": "response", "status_code": 200},
        "inventory_control": {"kind": "response", "status_code": 200},
        "database": {"kind": "rows", "rows": deepcopy(expectations["products"])},
        "service": {
            "kind": "resource",
            "resource": {
                "metadata": {"name": "inventory"},
                "spec": {
                    "selector": {"app": "inventory"},
                    "ports": [{"name": "http", "port": 80, "protocol": "TCP", "targetPort": 8080}],
                },
            },
        },
        "quotes": [
            {
                "case_id": case["id"],
                "kind": "response",
                "status_code": case["status_code"],
                "body": deepcopy(case.get("body")),
            }
            for case in expectations["quotes"]
        ],
    }


class TestClock:
    __test__ = False

    def __init__(self):
        self.elapsed = 0.0

    def now(self):
        return self.elapsed

    def sleep(self, duration):
        self.elapsed += duration


def test_full_corpus_passes(healthy, expectations):
    assert evaluate_snapshot(healthy, expectations) == {"verdict": SUCCESS, "reasons": []}


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_minor", 376),
        ("unit_price_minor", 126),
        ("available", False),
        ("currency", "EUR"),
        ("quantity", "3"),
        ("total_minor", True),
    ],
)
def test_plausible_http_200_wrong_result_fails(healthy, expectations, field, value):
    healthy["quotes"][1]["body"][field] = value
    assert evaluate_snapshot(healthy, expectations)["verdict"] == FAILURE


def test_noop_does_not_repair_wrong_target_port(healthy, expectations):
    healthy["service"]["resource"]["spec"]["ports"][0]["targetPort"] = 8081
    before = evaluate_snapshot(healthy, expectations)
    after_noop = evaluate_snapshot(deepcopy(healthy), expectations)
    assert before["verdict"] == after_noop["verdict"] == FAILURE


@pytest.mark.parametrize("field,value", [("name", "other"), ("port", 81), ("protocol", "UDP")])
def test_protected_service_fields_fail(healthy, expectations, field, value):
    healthy["service"]["resource"]["spec"]["ports"][0][field] = value
    assert evaluate_snapshot(healthy, expectations)["verdict"] == FAILURE


def test_protected_selector_fails(healthy, expectations):
    healthy["service"]["resource"]["spec"]["selector"] = {"app": "quote"}
    assert evaluate_snapshot(healthy, expectations)["verdict"] == FAILURE


def test_protected_database_contents_fail(healthy, expectations):
    healthy["database"]["rows"][0]["stock"] -= 1
    assert evaluate_snapshot(healthy, expectations)["verdict"] == FAILURE


@pytest.mark.parametrize(
    "dependency", ["database", "service", "quote_control", "inventory_control"]
)
def test_verifier_dependency_outage_indeterminate(healthy, expectations, dependency):
    healthy[dependency] = {"kind": "error", "error": "ConnectionError"}
    assert evaluate_snapshot(healthy, expectations)["verdict"] == INDETERMINATE


def test_client_transport_fault_with_controls_is_failure(healthy, expectations):
    healthy["quotes"][0] = {"case_id": "available-single", "kind": "error", "error": "ReadTimeout"}
    assert evaluate_snapshot(healthy, expectations)["verdict"] == FAILURE


def test_client_transport_fault_without_control_is_indeterminate(healthy, expectations):
    healthy["quote_control"] = {"kind": "error", "error": "ConnectError"}
    healthy["quotes"][0] = {"case_id": "available-single", "kind": "error", "error": "ConnectError"}
    assert evaluate_snapshot(healthy, expectations)["verdict"] == INDETERMINATE


def test_observed_error_survives_control_outage(healthy, expectations):
    healthy["inventory_control"] = {"kind": "error", "error": "ConnectError"}
    healthy["quotes"][0]["status_code"] = 503
    assert evaluate_snapshot(healthy, expectations)["verdict"] == FAILURE


def test_damage_survives_verifier_outage(healthy, expectations):
    healthy["database"] = {"kind": "error", "error": "OperationalError"}
    healthy["service"]["resource"]["spec"]["ports"][0]["targetPort"] = 8081
    result = evaluate_snapshot(healthy, expectations)
    assert result["verdict"] == FAILURE
    assert any("independent read unavailable" in reason for reason in result["reasons"])


def test_damage_survives_malformed_unrelated_observation(healthy, expectations):
    healthy["database"]["rows"][0]["stock"] = 0
    healthy["service"] = {"kind": "resource", "resource": None}
    assert evaluate_snapshot(healthy, expectations)["verdict"] == FAILURE


def test_duplicate_good_response_does_not_erase_bad_response(healthy, expectations):
    healthy["quotes"].append(deepcopy(healthy["quotes"][0]))
    healthy["quotes"][0]["body"]["total_minor"] = 0
    assert evaluate_snapshot(healthy, expectations)["verdict"] == FAILURE


@pytest.mark.parametrize("mode", ["empty", "missing", "duplicate"])
def test_incomplete_corpus_never_passes(healthy, expectations, mode):
    if mode == "empty":
        healthy["quotes"] = []
    elif mode == "missing":
        healthy["quotes"].pop()
    else:
        healthy["quotes"].append(healthy["quotes"][0])
    assert evaluate_snapshot(healthy, expectations)["verdict"] == INDETERMINATE


def test_full_window_preserves_transient_failure(healthy, expectations):
    clock = TestClock()
    snapshots = [deepcopy(healthy) for _ in range(4)]
    snapshots[1]["quotes"][0]["body"]["total_minor"] = 0
    result = run_window(
        lambda: snapshots.pop(0),
        expectations,
        window_seconds=3,
        interval_seconds=1,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert result["verdict"] == FAILURE
    assert result["counts"] == {"total": 4, SUCCESS: 3, FAILURE: 1, INDETERMINATE: 0}
    assert [probe["offset_seconds"] for probe in result["probes"]] == [0, 1, 2, 3]
    assert result["elapsed_seconds"] >= 3


def test_window_requires_final_boundary_probe(healthy, expectations):
    clock = TestClock()
    result = run_window(
        lambda: healthy,
        expectations,
        window_seconds=0.1,
        interval_seconds=5,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert result["verdict"] == SUCCESS
    assert result["counts"]["total"] == 2
    assert result["probes"][-1]["offset_seconds"] == 0.1


def test_collector_error_is_indeterminate(expectations):
    clock = TestClock()

    def broken():
        raise OSError("test-only failing adapter")

    result = run_window(
        broken,
        expectations,
        window_seconds=1,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert result["verdict"] == INDETERMINATE
    assert result["counts"]["total"] == 2


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, "1"])
@pytest.mark.parametrize("parameter", ["window_seconds", "interval_seconds"])
def test_invalid_window_cannot_pass(expectations, value, parameter):
    with pytest.raises(ValueError):
        run_window(lambda: {}, expectations, **{parameter: value})


def test_empty_expectations_cannot_pass():
    with pytest.raises(ValueError):
        run_window(lambda: {}, {"products": [], "quotes": []})


def test_http_adapter_records_wrong_200_body():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"total_minor": 999}))
    with httpx.Client(transport=transport) as client:
        observed = _http_observation(client, "http://test-only.invalid/quote")
    assert observed["kind"] == "response"
    assert observed["body"] == {"total_minor": 999}
    assert observed["observed_at"]


def test_http_adapter_records_transport_failure():
    def broken(request):
        raise httpx.ConnectError("test-only transport failure", request=request)

    with httpx.Client(transport=httpx.MockTransport(broken)) as client:
        observed = _http_observation(client, "http://test-only.invalid/quote")
    assert observed["kind"] == "error"
    assert observed["error"] == "ConnectError"
