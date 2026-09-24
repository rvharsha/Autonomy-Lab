"""Trusted, real-system injections for the prospective automation/agent comparison."""

import errno
import socket
from contextlib import contextmanager

OBSERVER_SCENARIOS = {"observer_outage", "observer_routing", "observer_quote",
                      "observer_verifier", "observer_quote_verifier"}
VERIFIER_OUTAGE_SCENARIOS = {"observer_verifier", "observer_quote_verifier"}


def verifier_outage_established(verification, *, semantic_fault):
    """Require actual failed measurement control without erasing observed corruption."""
    probes = verification.get("probes", [])
    expected = "verified_failure" if semantic_fault else "indeterminate"
    return bool(probes) and verification.get("verdict") == expected and all(
        probe["observations"]["inventory_control"].get("kind") == "error"
        and probe["observations"]["quote_control"].get("status_code") == 200
        and probe["observations"]["database"].get("kind") == "rows"
        and probe["observations"]["service"].get("kind") == "resource"
        and (not semantic_fault or any(
            quote.get("case_id") == "available-single" and quote.get("status_code") == 200
            and isinstance(quote.get("body"), dict) and quote["body"].get("total_minor") == 126
            for quote in probe["observations"].get("quotes", [])
        ))
        for probe in probes
    )


def configure_quote_fault(kube, scenario):
    assignments = {
        "quote_arithmetic": "QUOTE_TOTAL_OFFSET=1",
        "quote_upstream": "INVENTORY_URL=http://inventory:81",
    }
    kube.call("set", "env", "deployment/quote", assignments[scenario])
    kube.call("rollout", "status", "deployment/quote", "--timeout=90s")


def semantic_fault_established(verification):
    """Require actual wrong HTTP-200 content, not just a failed configuration check."""
    probes = verification.get("probes", [])
    if verification.get("verdict") != "verified_failure" or not probes:
        return False
    observation = probes[-1]["observations"]
    return (
        observation["quote_control"].get("status_code") == 200
        and observation["inventory_control"].get("status_code") == 200
        and any(item.get("case_id") == "available-single" and item.get("status_code") == 200
                and isinstance(item.get("body"), dict) and item["body"].get("total_minor") == 126
                for item in observation["quotes"])
    )


@contextmanager
def backend_observation_outage(kube):
    """Close a real observer port-forward; reserve its dead endpoint for the trial.

    The non-listening reservation prevents reuse by another process. The trusted
    verifier keeps its separate, live Inventory port-forward. No response is mocked.
    """
    with kube.forward("deployment/inventory", 8080) as port:
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", port))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(2)
            # A bound non-listening socket refuses on Linux, but times out on macOS.
            if probe.connect_ex(("127.0.0.1", port)) not in {errno.ECONNREFUSED, errno.EAGAIN, errno.ETIMEDOUT}:
                raise RuntimeError("Observer outage was not established")
        yield port
