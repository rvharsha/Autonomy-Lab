"""Real-cluster acceptance demonstrations. No generated evaluation outcomes."""

from __future__ import annotations

import json
import os
import selectors
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg

from autonomy_lab.broker import ActionBroker, BrokerPolicy, OperationConflict, Proposal
from autonomy_lab.environment import provision, service_identity, teardown, verifier_identity
from autonomy_lab.kubernetes import ROOT, Kubernetes
from autonomy_lab.verifier import verify


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def save(path: Path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def check(kube: Kubernetes, verifier_kube: Kubernetes, *, window_seconds=30, outage=False) -> dict:
    with ExitStack() as stack:
        quote_port = stack.enter_context(kube.forward("deployment/quote", 8080))
        inventory_port = stack.enter_context(kube.forward("deployment/inventory", 8080))
        db_port = stack.enter_context(kube.forward("deployment/postgres", 5432))
        db_url = f"postgresql://verifier_reader:verifier-test-only@127.0.0.1:{db_port}/lab"
        # A deliberately inaccessible measurement endpoint tests verifier failure.
        if outage:
            db_url = "postgresql://verifier_reader:verifier-test-only@127.0.0.1:1/lab"
        return verify(
            f"http://127.0.0.1:{quote_port}",
            f"http://127.0.0.1:{inventory_port}",
            db_url,
            lambda: verifier_kube.get_service(kube.namespace, "inventory"),
            window_seconds=window_seconds,
            interval_seconds=min(1.0, window_seconds),
            request_timeout=4,
            expectations_path=ROOT / "fixtures/expectations.json",
        )


def client_path_failed(verification: dict) -> bool:
    """Require a current client failure and functioning independent control paths."""
    probes = verification.get("probes", [])
    if not probes:
        return False
    observation = probes[-1]["observations"]
    return (
        observation["quote_control"].get("status_code") == 200
        and observation["inventory_control"].get("status_code") == 200
        and any(
            item.get("case_id") == "available-single" and item.get("status_code") == 503
            for item in observation["quotes"]
        )
    )


def establish_fault(kube: Kubernetes, verifier_kube: Kubernetes, run_dir: Path):
    deadline = time.monotonic() + 30
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        observed = check(kube, verifier_kube, window_seconds=1)
        save(run_dir / f"fault-establishment-{attempt}.json", observed)
        if client_path_failed(observed):
            return
    raise RuntimeError("Fault did not produce an observed client-path failure")


def save_observation(run_dir: Path, *, source: str, **data) -> str:
    """Create a new evidence record; existing observation IDs are never overwritten."""
    observation_id = uuid.uuid4().hex
    directory = run_dir / "observations"
    directory.mkdir(exist_ok=True)
    with (directory / f"{observation_id}.json").open("x") as stream:
        json.dump(
            {"id": observation_id, "observed_at": timestamp(), "source": source, **data},
            stream,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return observation_id


def proposal_for(
    kube: Kubernetes, run_id: str, *, run_dir: Path, operation_id: str | None = None
) -> Proposal:
    service = kube.get_service(kube.namespace, "inventory")
    evidence = [save_observation(run_dir, source="kubernetes:service/inventory", resource=service)]
    deployment = json.loads(kube.call("get", "deployment/inventory", "-o", "json"))
    evidence.append(
        save_observation(run_dir, source="kubernetes:deployment/inventory", resource=deployment)
    )
    ports = [
        port["containerPort"]
        for container in deployment["spec"]["template"]["spec"]["containers"]
        for port in container.get("ports", [])
        if port.get("name") == "http"
    ]
    if len(ports) != 1:
        raise ValueError("Inventory must advertise exactly one named HTTP backend port")
    target_port = ports[0]
    with kube.forward("deployment/inventory", target_port) as forwarded:
        response = httpx.get(f"http://127.0.0.1:{forwarded}/readyz", timeout=4, trust_env=False)
        evidence.append(
            save_observation(
                run_dir,
                source=f"kubernetes-port-forward:deployment/inventory:{target_port}/readyz",
                status_code=response.status_code,
                body=response.text[:2000],
                deployment_uid=deployment["metadata"]["uid"],
                backend_port=target_port,
            )
        )
        response.raise_for_status()
    service_ports = [port for port in service["spec"]["ports"] if port.get("name") == "http"]
    if len(service_ports) != 1:
        raise ValueError("Inventory Service must expose exactly one named HTTP port")
    return Proposal(
        run_id=run_id,
        operation_id=operation_id or uuid.uuid4().hex,
        namespace=kube.namespace,
        service_name="inventory",
        service_uid=service["metadata"]["uid"],
        resource_version=service["metadata"]["resourceVersion"],
        expected_target_port=service_ports[0]["targetPort"],
        target_port=target_port,
        evidence_ids=evidence,
    )


class CountingAdapter:
    """Test instrumentation around real requests, independent of journal records."""

    def __init__(self, adapter):
        self.adapter = adapter
        self.patch_calls = 0

    def get_service(self, namespace, name):
        return self.adapter.get_service(namespace, name)

    def patch_service(self, namespace, name, patch):
        self.patch_calls += 1
        return self.adapter.patch_service(namespace, name, patch)


def broker_transport_dispatches(run_dir: Path) -> int:
    path = run_dir / "api-mutations.jsonl"
    if not path.exists():
        return 0
    return sum(
        record.get("actor") == "broker" and record.get("event") == "dispatch"
        for record in (json.loads(line) for line in path.read_text().splitlines() if line)
    )


def dispatch_events(broker: ActionBroker, operation_id: str) -> int:
    return sum(event["event"] == "dispatching" for event in broker.events(operation_id))


def kill_at_barrier(
    command: list[str], stage: str, operation_id: str, log_path: Path, *, timeout_seconds: float = 60
) -> dict:
    """Kill a real child only after its flushed, deterministic checkpoint message."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), environment.get("PYTHONPATH", "")]
    )
    with log_path.open("w") as errors:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errors,
            env=environment,
        )
        try:
            assert process.stdout is not None
            os.set_blocking(process.stdout.fileno(), False)
            buffered = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    if selector.select(timeout=min(1, max(0, deadline - time.monotonic()))):
                        chunk = os.read(process.stdout.fileno(), 4096)
                        if not chunk:
                            raise RuntimeError(
                                f"Crash worker exited before {stage}; see {log_path.name}"
                            )
                        buffered.extend(chunk)
                        if len(buffered) > 65_536:
                            raise RuntimeError("Crash worker barrier exceeds size limit")
                        if b"\n" not in buffered:
                            continue
                        line = buffered.partition(b"\n")[0]
                        barrier = json.loads(line)
                        if (
                            not isinstance(barrier, dict)
                            or barrier.get("stage") != stage
                            or barrier.get("operation_id") != operation_id
                            or barrier.get("pid") != process.pid
                        ):
                            raise RuntimeError("Crash worker emitted an unexpected barrier")
                        break
                else:
                    raise TimeoutError(
                        f"Crash worker did not reach {stage} within {timeout_seconds:g} seconds"
                    )
            process.kill()
            exit_code = process.wait(timeout=10)
            if exit_code != -signal.SIGKILL:
                raise AssertionError(f"Expected SIGKILL termination, got {exit_code}")
            return {"barrier": barrier, "exit_code": exit_code, "signal": "SIGKILL"}
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            if process.stdout:
                process.stdout.close()


def sigkill_acceptance(kube, broker_kube, run_dir, run_id, record):
    for stage in ("after_intent", "after_dispatch"):
        kube.set_target_port(8081)
        proposal = proposal_for(kube, run_id, run_dir=run_dir, operation_id=f"sigkill-{stage}")
        journal = run_dir / f"broker-sigkill-{stage}.sqlite"
        worker_input = run_dir / f"crash-worker-{stage}.json"
        save(
            worker_input,
            {
                "stage": stage,
                "proposal": proposal.model_dump(),
                "journal_path": str(journal),
                "kubeconfig": str(broker_kube.kubeconfig),
                "cluster_name": broker_kube.cluster_name,
            },
        )
        before = broker_transport_dispatches(run_dir)
        killed = kill_at_barrier(
            [sys.executable, "-m", "autonomy_lab.crash_worker", str(worker_input)],
            stage,
            proposal.operation_id,
            run_dir / f"crash-worker-{stage}.stderr.log",
        )
        with closing(sqlite3.connect(journal)) as db:
            saved_row = db.execute(
                "SELECT status FROM operations WHERE operation_id=?", (proposal.operation_id,)
            ).fetchone()
            persisted_status = saved_row[0] if saved_row else None
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if saved_row is None:
            record(
                f"SIGKILL {stage}: durable recovery without duplicate dispatch",
                False,
                **killed,
                reason="operation_record_missing",
                persisted_status=None,
                saved_operation={"status": None},
                journal_integrity=integrity,
                journal_path=journal.name,
            )
            continue
        policy = BrokerPolicy(
            run_id, kube.namespace, "inventory", proposal.service_uid, max_dispatches=1
        )
        adapter = CountingAdapter(broker_kube)
        reopened = ActionBroker(journal, policy, adapter)
        saved = reopened.lookup(proposal.operation_id)
        service_before = kube.get_service(kube.namespace, "inventory")
        if stage == "after_intent":
            policy.enabled = False
            result = reopened.resume_prepared(proposal.operation_id)
            expected_calls = 0
            accepted = (
                persisted_status == saved["status"] == "prepared"
                and result["status"] == "rejected"
                and result["reason"] == "policy_disabled"
                and not result["budget_reserved"]
                and result["budget_used"] == 0
                and service_before["spec"]["ports"][0]["targetPort"] == 8081
                and service_before["metadata"]["resourceVersion"] == proposal.resource_version
            )
        else:
            result = reopened.reconcile(proposal.operation_id)
            repeated = reopened.propose(proposal)
            resumed = reopened.resume_prepared(proposal.operation_id)
            expected_calls = 1
            accepted = (
                persisted_status == "dispatching"
                and saved["status"]
                == result["status"]
                == repeated["status"]
                == resumed["status"]
                == "uncertain"
                and result["reconciliation"]["observation"] == "desired_state_observed"
                and result["reconciliation"]["attribution"] == "not_established"
                and result["reconciliation"]["recovery"] == "not_verified"
                and service_before["spec"]["ports"][0]["targetPort"] == proposal.target_port
            )
        service_after = kube.get_service(kube.namespace, "inventory")
        transport_calls = broker_transport_dispatches(run_dir) - before
        journal_dispatches = dispatch_events(reopened, proposal.operation_id)
        record(
            f"SIGKILL {stage}: durable recovery without duplicate dispatch",
            accepted
            and integrity == "ok"
            and saved["budget_reserved"]
            and saved["budget_used"] == 1
            and adapter.patch_calls == 0
            and transport_calls == journal_dispatches == expected_calls
            and service_before["metadata"]["resourceVersion"]
            == service_after["metadata"]["resourceVersion"],
            **killed,
            persisted_status=persisted_status,
            journal_integrity=integrity,
            saved_operation=saved,
            recovered_operation=result,
            transport_dispatches=transport_calls,
            journal_dispatches=journal_dispatches,
            resume_patch_calls=adapter.patch_calls,
            resource_version_before=service_before["metadata"]["resourceVersion"],
            resource_version_after=service_after["metadata"]["resourceVersion"],
        )


def broker_acceptance(
    kube: Kubernetes, run_dir: Path, run_id: str, *, results: list[dict] | None = None
) -> list[dict]:
    results = results if results is not None else []
    save(run_dir / "broker-checks.json", results)
    broker_kube = service_identity(kube, run_dir, "broker")

    def record(name, passed, **evidence):
        results.append({"name": name, "passed": bool(passed), **evidence})
        save(run_dir / "broker-checks.json", results)
        if not passed:
            raise AssertionError(f"Broker acceptance failed: {name}")

    def new_broker(label, adapter=None):
        svc = broker_kube.get_service(kube.namespace, "inventory")
        policy = BrokerPolicy(
            run_id, kube.namespace, "inventory", svc["metadata"]["uid"], max_dispatches=2
        )
        return ActionBroker(run_dir / f"broker-{label}.sqlite", policy, adapter or broker_kube)

    def proposal(operation_id=None):
        return proposal_for(kube, run_id, run_dir=run_dir, operation_id=operation_id)

    try:
        kube.set_target_port(8081)
        counted = CountingAdapter(broker_kube)
        broker = new_broker("normal", counted)
        baseline = broker_transport_dispatches(run_dir)
        p = proposal()
        bad = p.model_copy(update={"operation_id": "wrong-scope", "service_name": "quote"})
        rejected = broker.propose(bad)
        record(
            "wrong target rejected",
            rejected["status"] == "rejected"
            and counted.patch_calls == 0
            and kube.get_service(kube.namespace, "inventory")["spec"]["ports"][0]["targetPort"]
            == 8081,
            operation=rejected,
        )
        stale = proposal("stale")
        kube.set_target_port(8082)
        rejected = broker.propose(stale)
        record(
            "stale proposal rejected",
            rejected["status"] == "rejected" and counted.patch_calls == 0,
            operation=rejected,
        )
        p = proposal("repair")
        result = broker.propose(p)
        before = kube.get_service(kube.namespace, "inventory")["metadata"]["resourceVersion"]
        duplicate = broker.propose(p)
        after = kube.get_service(kube.namespace, "inventory")["metadata"]["resourceVersion"]
        calls = broker_transport_dispatches(run_dir) - baseline
        record(
            "duplicate returns saved acknowledgement",
            result["status"] == duplicate["status"] == "acknowledged"
            and before == after
            and counted.patch_calls == calls == dispatch_events(broker, p.operation_id) == 1,
            operation=duplicate,
            patch_calls=counted.patch_calls,
            transport_dispatches=calls,
            resource_version_before=before,
            resource_version_after=after,
        )
        try:
            broker.propose(p.model_copy(update={"target_port": 8082}))
        except OperationConflict:
            record("operation ID binds original request", counted.patch_calls == 1)
        else:
            record("operation ID binds original request", False)

        class LostAcknowledgement:
            def get_service(self, namespace, name):
                return broker_kube.get_service(namespace, name)

            def patch_service(self, namespace, name, patch):
                response = broker_kube.patch_service(namespace, name, patch)
                save(run_dir / "private-applied-before-response-loss.json", response)
                raise TimeoutError("Controlled loss after real API acknowledgement")

        kube.set_target_port(8081)
        counted = CountingAdapter(LostAcknowledgement())
        broker = new_broker("lost-ack", counted)
        p = proposal("lost-ack")
        baseline = broker_transport_dispatches(run_dir)
        uncertain = broker.propose(p)
        record(
            "real mutation with lost acknowledgement is uncertain",
            uncertain["status"] == "uncertain"
            and kube.get_service(kube.namespace, "inventory")["spec"]["ports"][0]["targetPort"]
            == 8080,
            operation=uncertain,
        )
        restarted_counted = CountingAdapter(broker_kube)
        reopened = ActionBroker(broker.journal_path, broker.policy, restarted_counted)
        before = kube.get_service(kube.namespace, "inventory")["metadata"]["resourceVersion"]
        reconciliation = reopened.reconcile(p.operation_id)
        repeated = reopened.propose(p)
        reopened.resume_prepared(p.operation_id)
        after = kube.get_service(kube.namespace, "inventory")["metadata"]["resourceVersion"]
        calls = broker_transport_dispatches(run_dir) - baseline
        record(
            "reopened journal reconciles without redispatch",
            before == after
            and repeated["status"] == "uncertain"
            and reconciliation["reconciliation"]["attribution"] == "not_established"
            and reconciliation["reconciliation"]["recovery"] == "not_verified"
            and restarted_counted.patch_calls == 0
            and counted.patch_calls == calls == dispatch_events(reopened, p.operation_id) == 1,
            operation=reconciliation,
            patch_calls=counted.patch_calls,
            resumed_patch_calls=restarted_counted.patch_calls,
            transport_dispatches=calls,
            resource_version_before=before,
            resource_version_after=after,
        )

        class RacingAdapter:
            def get_service(self, namespace, name):
                return broker_kube.get_service(namespace, name)

            def patch_service(self, namespace, name, patch):
                kube.set_target_port(8082)
                return broker_kube.patch_service(namespace, name, patch)

        kube.set_target_port(8081)
        broker = new_broker("race", RacingAdapter())
        rejected = broker.propose(proposal())
        record(
            "API rejects change after broker read",
            rejected["status"] == "rejected"
            and kube.get_service(kube.namespace, "inventory")["spec"]["ports"][0]["targetPort"]
            == 8082,
            operation=rejected,
        )
        sigkill_acceptance(kube, broker_kube, run_dir, run_id, record)
        kube.set_target_port(8080)
        return results
    finally:
        primary_failure = sys.exc_info()[0] is not None
        export_errors = []
        for path in run_dir.glob("broker-*.sqlite"):
            try:
                with sqlite3.connect(path) as db:
                    db.row_factory = sqlite3.Row
                    save(
                        path.with_suffix(".events.json"),
                        [
                            dict(row)
                            for row in db.execute("SELECT * FROM operation_events ORDER BY sequence")
                        ],
                    )
            except Exception as error:
                export_errors.append({"journal": path.name, "error_type": type(error).__name__})
        if export_errors:
            results.append({"name": "broker journal event export", "passed": False, "errors": export_errors})
            try:
                save(run_dir / "broker-event-export-errors.json", export_errors)
                save(run_dir / "broker-checks.json", results)
            except OSError:
                pass  # Preserve the original failure even if evidence storage also failed.
            if not primary_failure:
                raise RuntimeError("Broker journal event export failed")


def run_demo(*, window_seconds: float = 30, keep: bool = False) -> Path:
    run_id = uuid.uuid4().hex[:8]
    run_dir = ROOT / "artifacts" / f"demo-{run_id}"
    run_dir.mkdir(parents=True, mode=0o700)
    summary = {
        "run_id": run_id,
        "started_at": timestamp(),
        "status": "running",
        "kind": "real-cluster-acceptance",
        "window_seconds": window_seconds,
        "phases": [],
        "broker_checks": [],
        "cleanup": {"status": "pending"},
    }
    save(run_dir / "result.json", summary)
    kube = None
    try:
        print(f"Provisioning {run_id}; evidence: {run_dir}", flush=True)
        kube = provision(run_dir, run_id)
        verifier_kube = verifier_identity(kube, run_dir)
        save(run_dir / "cluster-version.json", json.loads(kube.call("version", "-o", "json")))
        save(run_dir / "pods.json", json.loads(kube.call("get", "pods", "-o", "json")))
        # auth can-i exits 1 on 'no'; use the real forbidden read to prove restriction.
        try:
            verifier_kube.call("get", "secrets")
        except RuntimeError as exc:
            if "Forbidden" not in str(exc):
                raise
            save(run_dir / "verifier-rbac.json", {"secrets_read": "forbidden"})
        else:
            raise AssertionError("Verifier unexpectedly has access to secrets")

        def phase(name, expected, *, short=False, outage=False):
            print(f"Checking {name}: expect {expected}", flush=True)
            result = check(
                kube,
                verifier_kube,
                window_seconds=min(window_seconds, 1) if short else window_seconds,
                outage=outage,
            )
            save(run_dir / f"{name}.json", result)
            entry = {
                "name": name,
                "expected": expected,
                "actual": result["verdict"],
                "passed": result["verdict"] == expected,
            }
            if name in {"routing-fault", "noop-repair"}:
                entry["client_path_failed"] = client_path_failed(result)
                entry["passed"] = entry["passed"] and entry["client_path_failed"]
            summary["phases"].append(entry)
            save(run_dir / "result.json", summary)
            if not entry["passed"]:
                raise AssertionError(f"{name}: expected {expected}, got {result['verdict']}")

        phase("healthy", "verified_success")
        kube.set_target_port(8081)
        establish_fault(kube, verifier_kube, run_dir)
        phase("routing-fault", "verified_failure", short=True)
        kube.set_target_port(8081)
        phase("noop-repair", "verified_failure", short=True)
        kube.set_target_port(8080)
        phase("scripted-recovery", "verified_success")
        kube.call("set", "env", "deployment/quote", "QUOTE_TOTAL_OFFSET=1")
        kube.call("rollout", "status", "deployment/quote", "--timeout=90s")
        phase("wrong-http200-total", "verified_failure", short=True)
        kube.call("set", "env", "deployment/quote", "QUOTE_TOTAL_OFFSET=0")
        kube.call("rollout", "status", "deployment/quote", "--timeout=90s")
        with kube.forward("deployment/postgres", 5432) as port:
            with psycopg.connect(f"postgresql://postgres:lab-test-only@127.0.0.1:{port}/lab") as db:
                db.execute("UPDATE products SET stock=99 WHERE sku='bolt'")
        phase("protected-data-changed", "verified_failure", short=True)
        with kube.forward("deployment/postgres", 5432) as port:
            with psycopg.connect(f"postgresql://postgres:lab-test-only@127.0.0.1:{port}/lab") as db:
                db.execute("UPDATE products SET stock=100 WHERE sku='bolt'")
        phase("verifier-outage", "indeterminate", short=True, outage=True)
        print("Checking broker against actual Kubernetes mutations", flush=True)
        broker_acceptance(kube, run_dir, run_id, results=summary["broker_checks"])
        phase("final-recovery", "verified_success")
        summary["status"] = "passed"
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        if kube:
            for name, args in [
                ("events", ("get", "events", "-o", "json")),
                ("failed-pods", ("get", "pods", "-o", "json")),
            ]:
                try:
                    save(run_dir / f"{name}.json", json.loads(kube.call(*args)))
                except Exception:
                    pass
        raise
    finally:
        if (run_dir / "environment.json").exists():
            if keep:
                summary["cleanup"] = {"status": "kept", "reason": "--keep requested"}
            else:
                print("Removing this run's disposable cluster", flush=True)
                try:
                    teardown(run_dir)
                    summary["cleanup"] = {"status": "deleted"}
                except Exception as exc:
                    summary["cleanup"] = {"status": "failed", "error": str(exc)}
                    summary["cleanup_error"] = str(exc)
                    summary["status"] = "failed"
                    print(f"Cleanup needs attention: {exc}", flush=True)
        else:
            summary["cleanup"] = {"status": "not_created"}
        if summary["status"] == "running":
            summary["status"] = "interrupted"
        summary["finished_at"] = timestamp()
        save(run_dir / "result.json", summary)
        write_report(run_dir, summary)
    if summary["cleanup"]["status"] == "failed":
        raise RuntimeError(f"Acceptance teardown failed; see {run_dir / 'REPORT.md'}")
    return run_dir


def write_report(run_dir: Path, summary: dict):
    lines = [
        "# Autonomy Lab acceptance run",
        "",
        f"Run: `{summary['run_id']}` — **{summary['status']}**",
        "",
        "Completed checks use real HTTP requests, PostgreSQL reads, and Kubernetes mutations.",
        "",
        "| Check | Expected | Observed | Passed |",
        "|---|---|---|---|",
    ]
    for phase in summary["phases"]:
        lines.append(
            f"| {phase['name']} | {phase['expected']} | {phase['actual']} | {phase['passed']} |"
        )
    for item in summary.get("broker_checks", []):
        lines.append(
            f"| {item['name']} | enforced | {'enforced' if item['passed'] else 'failed'} | {item['passed']} |"
        )
    lines.extend(
        ["", f"Environment cleanup: **{summary.get('cleanup', {}).get('status', 'unknown')}**."]
    )
    if summary.get("error"):
        lines.extend(["", f"Failure: {summary['error']}"])
    if summary.get("cleanup_error"):
        lines.extend(["", f"Cleanup failure: {summary['cleanup_error']}"])
    lines.extend(
        [
            "",
            "This is an infrastructure acceptance run, not an agent benchmark or AX lifecycle test.",
            "API dispatch logs are adapter instrumentation, not independent Kubernetes audit logs.",
            "Private local kubeconfigs and operation evidence remain in the ignored artifact directory.",
            "",
        ]
    )
    (run_dir / "REPORT.md").write_text("\n".join(lines))
