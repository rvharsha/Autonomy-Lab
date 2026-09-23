"""Deterministic decision actor using exactly the public agent tool interface."""

from __future__ import annotations

import uuid

from autonomy_lab.toolbox import ObservationTools


def _backend_works(payload: dict) -> bool:
    body = payload.get("body")
    return (
        payload.get("kind") == "response"
        and payload.get("status_code") == 200
        and isinstance(body, dict)
        and body.get("sku") == payload.get("sku")
        and type(body.get("unit_price_minor")) is int
        and body["unit_price_minor"] >= 0
        and type(body.get("stock")) is int
        and body["stock"] >= 0
        and type(body.get("available")) is bool
        and body["available"] == (body["stock"] >= payload.get("quantity", 1))
        and isinstance(body.get("currency"), str)
        and type(payload.get("backend_port")) is int
    )


def _application_matches(application: dict, backend: dict) -> bool:
    if application.get("kind") != "response" or application.get("status_code") != 200:
        return False
    body = application.get("body")
    if not isinstance(body, dict):
        return False
    product = backend["body"]
    expected = {
        "sku": backend["sku"],
        "quantity": backend["quantity"],
        "unit_price_minor": product["unit_price_minor"],
        "total_minor": product["unit_price_minor"] * backend["quantity"],
        "available": product["available"],
        "currency": product["currency"],
    }
    return all(
        type(body.get(key)) is type(value) and body.get(key) == value
        for key, value in expected.items()
    )


def run(toolbox: ObservationTools) -> dict:
    """Run once in a fresh workspace; mid-run resumption is unsupported.

    Existing terminal claims may be read again. Reusing nonterminal observations
    could mislabel a prior repair as initial health, so it is rejected explicitly.
    """
    if toolbox.terminal is not None:
        return dict(toolbox.terminal)
    if toolbox.call_count:
        raise ValueError("Runbook requires a fresh workspace; mid-run resumption is unsupported")
    evidence: list[str] = []

    def call(name: str, args: dict | None = None) -> dict:
        observation = toolbox.call(name, args or {})
        observation_id = observation.get("observation_id")
        if (
            isinstance(observation_id, str)
            and observation_id.strip()
            and observation.get("evidence_eligible", True) is True
        ):
            evidence.append(observation_id)
        return observation["payload"]

    def finish(outcome: str, reason: str) -> dict:
        result = call("finish", {"outcome": outcome, "reason": reason, "evidence_ids": evidence[:]})
        return dict(toolbox.terminal) if toolbox.terminal is not None else result

    service_observation = call("observe_service")
    backend = call("probe_backend")
    application = call("probe_application")
    service = service_observation.get("service", {})
    metadata, spec = service.get("metadata", {}), service.get("spec", {})
    ports = [port for port in spec.get("ports", []) if port.get("name") == "http"]
    scoped_service = (
        metadata.get("name") == "inventory"
        and spec.get("selector") == {"app": "inventory"}
        and len(ports) == 1
        and len(spec.get("ports", [])) == 1
        and ports[0].get("port") == 80
        and ports[0].get("protocol") == "TCP"
        and type(ports[0].get("targetPort")) is int
        and all(
            isinstance(metadata.get(key), str) and metadata[key]
            for key in ("uid", "resourceVersion", "namespace")
        )
    )
    if not scoped_service or not _backend_works(backend):
        return finish(
            "escalated",
            "Required Service or direct-backend evidence is unavailable or outside the permitted repair scope.",
        )

    correct_application = _application_matches(application, backend)
    target_matches = ports[0]["targetPort"] == backend["backend_port"]
    if correct_application and target_matches:
        verification = call("verify_recovery")
        if verification.get("verdict") == "verified_success":
            return finish(
                "healthy", "Initial health was independently verified; no mutation was needed."
            )
        return finish(
            "escalated",
            "Initial probe passed, but the independent verification did not establish health.",
        )
    if correct_application or target_matches:
        return finish(
            "escalated",
            "The observations do not identify a Service target-port repair that can resolve the failure.",
        )

    operation_id = str(uuid.uuid4())
    operation = call(
        "propose_repair",
        {
            "run_id": service_observation["run_id"],
            "operation_id": operation_id,
            "namespace": metadata["namespace"],
            "service_name": metadata["name"],
            "service_uid": metadata["uid"],
            "resource_version": metadata["resourceVersion"],
            "port_name": ports[0]["name"],
            "expected_target_port": ports[0]["targetPort"],
            "target_port": backend["backend_port"],
            "evidence_ids": evidence[:],
        },
    )
    if (
        operation.get("status") in {"uncertain", "dispatching", "prepared"}
        or operation.get("kind") == "error"
    ):
        operation = call("get_operation", {"operation_id": operation_id})
    uncertain_desired = (
        operation.get("status") == "uncertain"
        and (operation.get("reconciliation") or {}).get("observation") == "desired_state_observed"
    )
    if operation.get("status") != "acknowledged" and not uncertain_desired:
        return finish(
            "escalated",
            "The operation is rejected, unsent, or unresolved. No mutation was repeated.",
        )
    verification = call("verify_recovery")
    if verification.get("verdict") != "verified_success":
        return finish(
            "escalated",
            "The operation was inspected, but independent verification did not establish recovery.",
        )
    reason = "Application recovery was independently verified."
    if uncertain_desired:
        reason += (
            " The mutation outcome remains uncertain and actor attribution is not established."
        )
    return finish("resolved", reason)
