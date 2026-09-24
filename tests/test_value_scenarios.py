"""Injection contract tests, not measured agent outcomes."""

import errno
import socket
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from autonomy_lab.value_scenarios import (
    backend_observation_outage,
    configure_quote_fault,
    semantic_fault_established,
    verifier_outage_established,
)


def test_quote_fault_changes_only_declared_configuration_and_waits_for_rollout():
    calls = []
    kube = SimpleNamespace(call=lambda *args: calls.append(args))
    configure_quote_fault(kube, "quote_arithmetic")
    assert calls == [("set", "env", "deployment/quote", "QUOTE_TOTAL_OFFSET=1"),
                     ("rollout", "status", "deployment/quote", "--timeout=90s")]
    with pytest.raises(KeyError):
        configure_quote_fault(kube, "arbitrary")
    assert len(calls) == 2


@pytest.mark.parametrize("verdict,status,total,control,established", [
    ("verified_failure", 200, 126, 200, True),
    ("verified_failure", 200, 125, 200, False),
    ("verified_failure", 503, 126, 200, False),
    ("indeterminate", 200, 126, 200, False),
    ("verified_failure", 200, 126, 503, False),
])
def test_semantic_fault_needs_actual_wrong_content(verdict, status, total, control, established):
    verification = {"verdict": verdict, "probes": [{"observations": {
        "quote_control": {"status_code": control}, "inventory_control": {"status_code": 200},
        "quotes": [{"case_id": "available-single", "status_code": status, "body": {"total_minor": total}}],
    }}]}
    assert semantic_fault_established(verification) is established


def test_outage_closes_real_listener_and_reserves_dead_endpoint():
    @contextmanager
    def forward(*args):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            yield listener.getsockname()[1]

    with backend_observation_outage(SimpleNamespace(forward=forward)) as port:
        with socket.socket() as probe:
            probe.settimeout(2)
            assert probe.connect_ex(("127.0.0.1", port)) in {errno.ECONNREFUSED, errno.EAGAIN, errno.ETIMEDOUT}
        with socket.socket() as replacement:
            replacement.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                replacement.bind(("127.0.0.1", port))


@pytest.mark.parametrize("semantic_fault,verdict,accepted", [
    (False, "indeterminate", True), (False, "verified_success", False),
    (False, "verified_failure", False), (True, "verified_failure", True),
    (True, "indeterminate", False), (True, "verified_success", False),
])
def test_verifier_outage_gate_keeps_failure_and_uncertainty_distinct(semantic_fault, verdict, accepted):
    snapshot = {"inventory_control": {"kind": "error"}, "quote_control": {"status_code": 200},
                "database": {"kind": "rows"}, "service": {"kind": "resource"},
                "quotes": [{"case_id": "available-single", "status_code": 200, "body": {"total_minor": 126}}]}
    measurement = {"verdict": verdict, "probes": [{"observations": snapshot}]}
    assert verifier_outage_established(measurement, semantic_fault=semantic_fault) is accepted
    snapshot["quotes"][0]["body"]["total_minor"] = 125
    if semantic_fault:
        assert not verifier_outage_established(measurement, semantic_fault=semantic_fault)
    snapshot["inventory_control"] = {"kind": "response", "status_code": 200}
    assert not verifier_outage_established(measurement, semantic_fault=semantic_fault)
    assert not verifier_outage_established({"verdict": verdict, "probes": []}, semantic_fault=semantic_fault)
