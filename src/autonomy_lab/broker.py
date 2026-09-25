"""Bounded Service repairs with a durable, conservative operation journal.

The SQLite journal belongs to the broker, independently of agent checkpoints.
An operation reserved before a crash can be resumed explicitly; an operation
whose dispatch started can only be observed, never automatically sent again.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1, max_length=253, pattern=r"\S")]
Port = Annotated[int, Field(ge=1, le=65535, strict=True)]


class Proposal(BaseModel):
    """The complete allowed action; arbitrary Kubernetes patches are forbidden."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")

    run_id: Identifier
    operation_id: Identifier
    namespace: Identifier
    service_name: Identifier
    service_uid: Identifier
    resource_version: Identifier
    port_name: Identifier = "http"
    expected_target_port: Port
    target_port: Port
    evidence_ids: Annotated[list[Identifier], Field(min_length=1, max_length=100)]


@dataclass
class BrokerPolicy:
    """Trusted controller policy. Changing ``enabled`` revokes future dispatch."""

    run_id: str
    namespace: str
    service_name: str
    service_uid: str
    allowed_target_ports: frozenset[int] = field(default_factory=lambda: frozenset({8080}))
    max_dispatches: int = 1
    enabled: bool = True
    port_name: str = "http"

    def __post_init__(self) -> None:
        if type(self.max_dispatches) is not int or self.max_dispatches < 0:
            raise ValueError("max_dispatches must be a nonnegative integer")
        if not self.allowed_target_ports or any(
            type(port) is not int or not 1 <= port <= 65535
            for port in self.allowed_target_ports
        ):
            raise ValueError("allowed_target_ports must contain valid integer ports")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.run_id, self.namespace, self.service_name, self.service_uid, self.port_name)
        ):
            raise ValueError("policy identity fields must be nonempty strings")


class KubernetesAdapter(Protocol):
    def get_service(self, namespace: str, name: str) -> dict[str, Any]: ...

    def patch_service(
        self, namespace: str, name: str, patch: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class PatchRejected(Exception):
    """The API definitively rejected the mutation without applying it."""

    def __init__(self, reason: str = "precondition_failed") -> None:
        self.reason = reason
        super().__init__(reason)


class OperationConflict(ValueError):
    """An operation ID was previously bound to different request contents."""


class ActionBroker:
    def __init__(
        self,
        journal_path: str | Path,
        policy: BrokerPolicy,
        adapter: KubernetesAdapter,
        hook: Callable[[str], None] | None = None,
    ) -> None:
        self.journal_path = str(journal_path)
        if self.journal_path == ":memory:":
            raise ValueError("the operation journal must be a durable file")
        self.policy = policy
        self.adapter = adapter
        self.hook = hook
        self.owner = str(uuid.uuid4())
        Path(journal_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    budget_reserved INTEGER NOT NULL,
                    owner TEXT,
                    result TEXT,
                    reconciliation TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS operations_run ON operations(run_id);
                CREATE TABLE IF NOT EXISTS operation_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    details TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.journal_path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=30000")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _event(self, db: sqlite3.Connection, operation_id: str, event: str, **details: Any) -> None:
        db.execute(
            "INSERT INTO operation_events(operation_id,event,details,timestamp) VALUES(?,?,?,?)",
            (operation_id, event, json.dumps(details, sort_keys=True), self._now()),
        )

    def _policy_reason(self, proposal: Proposal) -> str | None:
        policy = self.policy
        if not policy.enabled:
            return "policy_disabled"
        if reason := self._scope_reason(proposal):
            return reason
        if proposal.target_port not in policy.allowed_target_ports:
            return "target_port_not_allowed"
        if proposal.target_port == proposal.expected_target_port:
            return "no_change"
        return None

    def _scope_reason(self, proposal: Proposal) -> str | None:
        for name in ("run_id", "namespace", "service_name", "service_uid", "port_name"):
            if getattr(proposal, name) != getattr(self.policy, name):
                return f"scope_mismatch:{name}"
        return None

    @staticmethod
    def _used(db: sqlite3.Connection, run_id: str) -> int:
        return db.execute(
            "SELECT count(*) FROM operations WHERE run_id=? AND budget_reserved=1", (run_id,)
        ).fetchone()[0]

    def propose(self, proposal: Proposal | Mapping[str, Any]) -> dict[str, Any]:
        proposal = Proposal.model_validate(proposal)
        request = json.dumps(proposal.model_dump(), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(request.encode()).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT digest FROM operations WHERE operation_id=?", (proposal.operation_id,)
            ).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise OperationConflict("operation_id is already bound to a different proposal")
                duplicate = True
            else:
                duplicate = False
                reason = self._policy_reason(proposal)
                if reason is None and self._used(db, proposal.run_id) >= self.policy.max_dispatches:
                    reason = "budget_exhausted"
                status = "rejected" if reason else "prepared"
                timestamp = self._now()
                db.execute(
                    """INSERT INTO operations(
                        operation_id,run_id,digest,request,status,reason,budget_reserved,
                        created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        proposal.operation_id, proposal.run_id, digest, request, status,
                        reason or "intent_recorded", int(reason is None), timestamp, timestamp,
                    ),
                )
                self._event(db, proposal.operation_id, status, reason=reason or "intent_recorded")
        if duplicate or reason:
            return self.lookup(proposal.operation_id)
        self._call_hook("after_intent")
        return self.resume_prepared(proposal.operation_id)

    def lookup(self, operation_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            result = dict(row)
            result.pop("digest")
            owner = result.pop("owner")
            for key in ("request", "result", "reconciliation"):
                result[key] = json.loads(result[key]) if result[key] else None
            result["budget_reserved"] = bool(result["budget_reserved"])
            result["budget_used"] = self._used(db, result["run_id"])
            result["budget_limit"] = self.policy.max_dispatches
            if result["status"] == "dispatching" and owner != self.owner:
                result["journal_status"] = "dispatching"
                result["status"] = "uncertain"
                result["reason"] = "dispatch_outcome_unrecorded"
            return result

    def resume_prepared(self, operation_id: str) -> dict[str, Any]:
        """Explicitly resume unsent intent; an atomic claim prevents double dispatch."""
        operation = self.lookup(operation_id)
        if operation["status"] != "prepared":
            return operation
        proposal = Proposal.model_validate(operation["request"])
        reason = self._policy_reason(proposal)
        if reason:
            return self._reject_prepared(operation_id, reason)
        try:
            service = self.adapter.get_service(proposal.namespace, proposal.service_name)
            patch, reason = self._construct_patch(proposal, service)
        except Exception as error:
            # No send has started; leave the durable intent resumable.
            with self._connect() as db:
                self._event(db, operation_id, "preflight_unavailable", error_type=type(error).__name__)
            return self.lookup(operation_id)
        if reason:
            return self._reject_prepared(operation_id, reason)
        self._call_hook("before_dispatch")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            reason = self._policy_reason(proposal)
            if reason is None and self._used(db, proposal.run_id) > self.policy.max_dispatches:
                reason = "budget_revoked"
            state = "rejected" if reason else "dispatching"
            changed = db.execute(
                """UPDATE operations SET status=?,reason=?,budget_reserved=?,owner=?,updated_at=?
                   WHERE operation_id=? AND status='prepared'""",
                (state, reason or "dispatch_started", int(reason is None), self.owner,
                 self._now(), operation_id),
            ).rowcount
            if changed:
                self._event(db, operation_id, state, reason=reason or "dispatch_started")
                if reason:
                    self._event(db, operation_id, "budget_released", reason=reason)
        if not changed or reason:
            return self.lookup(operation_id)
        try:
            result = self.adapter.patch_service(proposal.namespace, proposal.service_name, patch)
        except Exception as error:
            if isinstance(error, PatchRejected):
                return self._finish(operation_id, "rejected", error.reason)
            code = getattr(error, "status_code", None) or getattr(error, "status", None)
            code = code or getattr(getattr(error, "response", None), "status_code", None)
            if code in (400, 401, 403, 404, 409, 422):
                return self._finish(operation_id, "rejected", f"api_rejected:{code}")
            return self._finish(operation_id, "uncertain", "dispatch_outcome_unknown")
        # Hooks intentionally remain outside the transport exception handler:
        # a simulated crash leaves dispatching durable, as a process death would.
        self._call_hook("after_dispatch")
        self._call_hook("before_record")
        metadata = result.get("metadata") if isinstance(result, dict) else None
        spec = result.get("spec") if isinstance(result, dict) else None
        ports = spec.get("ports") if isinstance(spec, dict) else None
        matching = (
            [port for port in ports if port.get("name") == proposal.port_name]
            if isinstance(ports, list) and all(isinstance(port, dict) for port in ports)
            else []
        )
        if (
            not isinstance(metadata, dict)
            or metadata.get("uid") != proposal.service_uid
            or not isinstance(metadata.get("resourceVersion"), str)
            or not metadata["resourceVersion"]
            or metadata["resourceVersion"] == proposal.resource_version
            or len(matching) != 1
            or type(matching[0].get("targetPort")) is not int
            or matching[0]["targetPort"] != proposal.target_port
        ):
            return self._finish(operation_id, "uncertain", "ack_unparseable")
        return self._finish(
            operation_id, "acknowledged", "api_acknowledged",
            {"service_uid": metadata.get("uid"), "resource_version": metadata.get("resourceVersion")},
        )

    def _construct_patch(
        self, proposal: Proposal, service: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None]:
        metadata = service.get("metadata", {})
        for key, expected, reason in (
            ("uid", proposal.service_uid, "service_uid_changed"),
            ("resourceVersion", proposal.resource_version, "resource_version_changed"),
            ("namespace", proposal.namespace, "service_namespace_changed"),
            ("name", proposal.service_name, "service_name_changed"),
        ):
            if metadata.get(key) != expected:
                return [], reason
        ports = service.get("spec", {}).get("ports", [])
        matching = [(i, p) for i, p in enumerate(ports) if p.get("name") == proposal.port_name]
        if len(matching) != 1:
            return [], "port_name_not_unique"
        index, port = matching[0]
        if type(port.get("targetPort")) is not int or port["targetPort"] != proposal.expected_target_port:
            return [], "target_port_changed"
        path = f"/spec/ports/{index}"
        return [
            {"op": "test", "path": "/metadata/uid", "value": proposal.service_uid},
            {"op": "test", "path": "/metadata/resourceVersion", "value": proposal.resource_version},
            {"op": "test", "path": f"{path}/name", "value": proposal.port_name},
            {"op": "test", "path": f"{path}/targetPort", "value": proposal.expected_target_port},
            {"op": "replace", "path": f"{path}/targetPort", "value": proposal.target_port},
        ], None

    def _reject_prepared(self, operation_id: str, reason: str) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                """UPDATE operations SET status='rejected',reason=?,budget_reserved=0,updated_at=?
                   WHERE operation_id=? AND status='prepared'""",
                (reason, self._now(), operation_id),
            ).rowcount
            if changed:
                self._event(db, operation_id, "rejected", reason=reason)
                self._event(db, operation_id, "budget_released", reason=reason)
        return self.lookup(operation_id)

    def _finish(
        self, operation_id: str, status: str, reason: str, result: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                """UPDATE operations SET status=?,reason=?,result=?,updated_at=?
                   WHERE operation_id=? AND status IN ('dispatching','uncertain') AND owner=?""",
                (status, reason, json.dumps(result), self._now(), operation_id, self.owner),
            ).rowcount
            if changed:
                self._event(db, operation_id, status, reason=reason, result=result)
        return self.lookup(operation_id)

    def reconcile(self, operation_id: str) -> dict[str, Any]:
        """Record present state, without claiming attribution or verified recovery."""
        operation = self.lookup(operation_id)
        proposal = Proposal.model_validate(operation["request"])
        try:
            if self._scope_reason(proposal):
                raise PermissionError("operation is outside current scope")
            service = self.adapter.get_service(proposal.namespace, proposal.service_name)
            metadata = service.get("metadata", {})
            ports = [p for p in service.get("spec", {}).get("ports", []) if p.get("name") == proposal.port_name]
            identity_matches = (
                metadata.get("uid") == proposal.service_uid
                and metadata.get("namespace") == proposal.namespace
                and metadata.get("name") == proposal.service_name
            )
            desired = identity_matches and len(ports) == 1 and ports[0].get("targetPort") == proposal.target_port
            observed = {
                "observation": "desired_state_observed" if desired else "desired_state_not_observed",
                "service_uid": metadata.get("uid"),
                "resource_version": metadata.get("resourceVersion"),
                "identity_matches": identity_matches,
                "target_port": ports[0].get("targetPort") if len(ports) == 1 else None,
                "attribution": "not_established",
                "recovery": "not_verified",
                "observed_at": self._now(),
            }
        except Exception as error:
            observed = {
                "observation": "unavailable", "error_type": type(error).__name__,
                "attribution": "not_established", "recovery": "not_verified",
                "observed_at": self._now(),
            }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE operations SET reconciliation=?,updated_at=?,
                   status=CASE WHEN status='dispatching' THEN 'uncertain' ELSE status END,
                   reason=CASE WHEN status='dispatching' THEN 'dispatch_outcome_unrecorded' ELSE reason END
                   WHERE operation_id=?""",
                (json.dumps(observed, sort_keys=True), self._now(), operation_id),
            )
            self._event(db, operation_id, "reconciled", **observed)
        return self.lookup(operation_id)

    def events(self, operation_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [
                {**dict(row), "details": json.loads(row["details"])}
                for row in db.execute(
                    "SELECT * FROM operation_events WHERE operation_id=? ORDER BY sequence", (operation_id,)
                )
            ]

    def _call_hook(self, stage: str) -> None:
        if self.hook:
            self.hook(stage)
