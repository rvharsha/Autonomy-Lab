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
        and isinstance(payload.get("sku"), str) and bool(payload["sku"])
        and type(payload.get("quantity")) is int and payload["quantity"] > 0
        and body.get("sku") == payload["sku"]
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


def _service_scope(service_observation: dict):
    service = service_observation.get("service")
    if not isinstance(service, dict):
        return None
    metadata, spec = service.get("metadata", {}), service.get("spec", {})
    if not isinstance(metadata, dict) or not isinstance(spec, dict):
        return None
    raw_ports = spec.get("ports")
    if not isinstance(raw_ports, list) or not all(isinstance(p, dict) for p in raw_ports):
        return None
    ports = [port for port in raw_ports if port.get("name") == "http"]
    valid = (
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
    return (metadata, ports[0]) if valid else None


def _refresh_proposal(call, evidence, original, operation):
    """One new decision after a received non-applied response, never an effect replay."""
    if not (
        {"result", "reconciliation"} <= operation.keys()
        and operation.get("status") == "rejected"
        and operation.get("reason") in {"api_rejected_409", "api_rejected_422"}
        and operation.get("operation_id") == original["operation_id"]
        and operation.get("run_id") == original["run_id"]
        and operation.get("request") == original
        and operation.get("result") is None
        and operation.get("reconciliation") is None
        and operation.get("journal_status") is None
        and operation.get("budget_reserved") is True
        and type(operation.get("budget_used")) is int
        and type(operation.get("budget_limit")) is int
        and 1 <= operation["budget_used"] < operation["budget_limit"]
    ):
        return None
    evidence_count = len(evidence)
    observed = call("observe_service")
    backend = call("probe_backend")
    application = call("probe_application")
    scope = _service_scope(observed)
    if len(evidence) != evidence_count + 3 or scope is None or not _backend_works(backend):
        return None
    metadata, port = scope
    if not (
        observed.get("run_id") == original["run_id"]
        and metadata["namespace"] == original["namespace"]
        and metadata["name"] == original["service_name"]
        and metadata["uid"] == original["service_uid"]
        and metadata["resourceVersion"] != original["resource_version"]
        and port["targetPort"] == original["expected_target_port"]
        and backend["backend_port"] == original["target_port"]
        and port["targetPort"] != backend["backend_port"]
        and application.get("kind") == "response"
        and type(application.get("status_code")) is int
        and application["status_code"] == 503
        and application.get("body") == {"detail": "inventory unavailable"}
    ):
        return None
    return {**original, "operation_id": str(uuid.uuid4()),
            "resource_version": metadata["resourceVersion"], "evidence_ids": evidence[:]}


def run(toolbox: ObservationTools, *, verification_fallback: bool = False,
        bounded_refresh: bool = False) -> dict:
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
    scope = _service_scope(service_observation)
    scoped_service = scope is not None
    metadata, port = scope if scope else ({}, {})
    if not scoped_service or not _backend_works(backend):
        if verification_fallback and scoped_service and backend.get("kind") == "error":
            verification = call("verify_recovery")
            if verification.get("verdict") == "verified_success":
                return finish(
                    "healthy",
                    "Backend observation was unavailable, but independent verification established health without mutation.",
                )
            return finish(
                "escalated",
                "Backend observation was unavailable and independent verification did not establish health. No repair was attempted.",
            )
        return finish(
            "escalated",
            "Required Service or direct-backend evidence is unavailable or outside the permitted repair scope.",
        )

    correct_application = _application_matches(application, backend)
    target_matches = port["targetPort"] == backend["backend_port"]
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
    proposal = {
        "run_id": service_observation["run_id"],
        "operation_id": operation_id,
        "namespace": metadata["namespace"],
        "service_name": metadata["name"],
        "service_uid": metadata["uid"],
        "resource_version": metadata["resourceVersion"],
        "port_name": port["name"],
        "expected_target_port": port["targetPort"],
        "target_port": backend["backend_port"],
        "evidence_ids": evidence[:],
    }
    operation = call("propose_repair", proposal)
    # Only the original received rejection can enter this path. A later read of
    # an unknown outcome cannot retrospectively authorize another mutation.
    if bounded_refresh:
        refreshed = _refresh_proposal(call, evidence, proposal, operation)
        if refreshed is not None:
            operation_id = refreshed["operation_id"]
            operation = call("propose_repair", refreshed)
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
            "The operation is rejected, unsent, or unresolved. No further mutation was attempted.",
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
