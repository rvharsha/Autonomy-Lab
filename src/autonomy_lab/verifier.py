"""Independent M1 verifier; application code never supplies expected answers.

The verifier records a complete corpus per probe and retains every probe in the
window. Unit-test adapters exercise scoring, not real-cluster acceptance gates.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

DEFAULT_EXPECTATIONS = Path(__file__).resolve().parents[2] / "fixtures" / "expectations.json"
SUCCESS = "verified_success"
FAILURE = "verified_failure"
INDETERMINATE = "indeterminate"


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def load_expectations(path: Path = DEFAULT_EXPECTATIONS) -> dict[str, Any]:
    expectations = json.loads(path.read_text())
    if not expectations.get("products") or not expectations.get("quotes"):
        raise ValueError("Verifier expectations must contain products and quote cases")
    ids = [case["id"] for case in expectations["quotes"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Verifier quote case IDs must be unique")
    return expectations


def _strict_equal(actual: Any, expected: Any) -> bool:
    """Avoid accepting True as price 1 or numeric strings as integer amounts."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _strict_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _strict_equal(a, e) for a, e in zip(actual, expected, strict=True)
        )
    return actual == expected


def evaluate_snapshot(
    snapshot: dict[str, Any],
    expectations: dict[str, Any],
    *,
    expected_target_port: int = 8080,
) -> dict[str, Any]:
    """Classify one complete observation, preserving conclusive damage on outage."""
    failures: list[str] = []
    unknowns: list[str] = []
    if not isinstance(snapshot, dict):
        return {"verdict": INDETERMINATE, "reasons": ["verifier snapshot is malformed"]}

    def observation(name: str) -> dict[str, Any]:
        value = snapshot.get(name, {})
        return value if isinstance(value, dict) else {}

    controls_healthy = True
    for name in ("quote_control", "inventory_control"):
        control = observation(name)
        if control.get("kind") != "response" or control.get("status_code") != 200:
            controls_healthy = False
            unknowns.append(f"{name}: measurement health control unavailable")

    database = observation("database")
    if database.get("kind") != "rows":
        unknowns.append("database: independent read unavailable")
    elif not _strict_equal(database.get("rows"), expectations["products"]):
        failures.append("database: protected product rows differ from independent fixture")

    service = observation("service")
    resource = service.get("resource")
    if (
        service.get("kind") != "resource"
        or not isinstance(resource, dict)
        or not isinstance(resource.get("metadata"), dict)
        or not isinstance(resource.get("spec"), dict)
    ):
        unknowns.append("service: independent configuration read unavailable")
    else:
        spec = resource.get("spec", {})
        ports = spec.get("ports", [])
        if resource.get("metadata", {}).get("name") != "inventory":
            failures.append("service: protected name is not inventory")
        if spec.get("selector") != {"app": "inventory"}:
            failures.append("service: protected selector differs")
        if not isinstance(ports, list) or len(ports) != 1 or not isinstance(ports[0], dict):
            failures.append("service: protected port list differs")
        else:
            expected_port = {
                "name": "http",
                "port": 80,
                "protocol": "TCP",
                "targetPort": expected_target_port,
            }
            for key, expected in expected_port.items():
                if not _strict_equal(ports[0].get(key), expected):
                    failures.append(f"service: protected {key} differs (expected {expected})")

    quotes = snapshot.get("quotes", [])
    if not isinstance(quotes, list) or any(not isinstance(quote, dict) for quote in quotes):
        unknowns.append("quotes: malformed corpus observations")
        quotes = (
            [quote for quote in quotes if isinstance(quote, dict)]
            if isinstance(quotes, list)
            else []
        )
    expected_ids = {case["id"] for case in expectations["quotes"]}
    actual_ids = [quote.get("case_id") for quote in quotes if isinstance(quote.get("case_id"), str)]
    if (
        len(actual_ids) != len(quotes)
        or len(actual_ids) != len(set(actual_ids))
        or set(actual_ids) != expected_ids
    ):
        unknowns.append("quotes: corpus is incomplete, duplicated, or contains unknown cases")
    for case in expectations["quotes"]:
        matching = [quote for quote in quotes if quote.get("case_id") == case["id"]]
        prefix = f"quote {case['id']}"
        if not matching:
            unknowns.append(f"{prefix}: response not observed")
        for observed in matching:
            if observed.get("kind") == "error":
                if controls_healthy:
                    failures.append(
                        f"{prefix}: client path failed with healthy measurement controls"
                    )
                else:
                    unknowns.append(
                        f"{prefix}: transport failure with unavailable measurement control"
                    )
            elif observed.get("kind") != "response":
                unknowns.append(f"{prefix}: response not observed")
            elif observed.get("status_code") != case["status_code"]:
                failures.append(
                    f"{prefix}: HTTP {observed.get('status_code')} (expected {case['status_code']})"
                )
            elif "body" in case and not _strict_equal(observed.get("body"), case["body"]):
                failures.append(f"{prefix}: response differs from independent expected result")

    verdict = FAILURE if failures else INDETERMINATE if unknowns else SUCCESS
    return {"verdict": verdict, "reasons": failures + unknowns}


def _positive_finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


def run_window(
    collector: Callable[[], dict[str, Any]],
    expectations: dict[str, Any],
    *,
    window_seconds: float = 30,
    interval_seconds: float = 1,
    expected_target_port: int = 8080,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Observe both window boundaries; a later success cannot erase a failure.

    An interval is measured between completion and the next probe start. The
    final probe starts at/after the deadline; no claim is made about unobserved
    behavior between samples. Blocking collection may extend actual duration.
    """
    _positive_finite("window_seconds", window_seconds)
    _positive_finite("interval_seconds", interval_seconds)
    if type(expected_target_port) is not int or not 1 <= expected_target_port <= 65535:
        raise ValueError("expected_target_port must be an integer TCP port")
    if not expectations.get("products") or not expectations.get("quotes"):
        raise ValueError("Verifier cannot run with an empty expectation corpus")
    started_at = timestamp()
    started = clock()
    probes: list[dict[str, Any]] = []
    while True:
        probe_started = clock()
        probe_timestamp = timestamp()
        try:
            snapshot = collector()
            assessment = evaluate_snapshot(
                snapshot, expectations, expected_target_port=expected_target_port
            )
        except Exception as exc:
            # Infrastructure/adapter failures must never be mislabeled success.
            snapshot = {"collection_error": type(exc).__name__}
            assessment = {
                "verdict": INDETERMINATE,
                "reasons": [f"verifier collection failed: {type(exc).__name__}"],
            }
        probes.append(
            {
                "index": len(probes),
                "started_at": probe_timestamp,
                "finished_at": timestamp(),
                "elapsed_seconds": round(clock() - probe_started, 6),
                "offset_seconds": round(probe_started - started, 6),
                "observations": snapshot,
                **assessment,
            }
        )
        if probe_started - started >= window_seconds and len(probes) >= 2:
            break
        remaining = max(0.0, window_seconds - (clock() - started))
        if remaining:
            sleep(min(interval_seconds, remaining))

    counts = Counter(probe["verdict"] for probe in probes)
    verdict = FAILURE if counts[FAILURE] else INDETERMINATE if counts[INDETERMINATE] else SUCCESS
    reasons = list(dict.fromkeys(reason for probe in probes for reason in probe["reasons"]))
    return {
        "verdict": verdict,
        "reasons": reasons,
        "started_at": started_at,
        "finished_at": timestamp(),
        "window_seconds": window_seconds,
        "interval_seconds": interval_seconds,
        "elapsed_seconds": round(clock() - started, 6),
        "expectation_version": expectations.get("version"),
        "counts": {
            "total": len(probes),
            **{key: counts[key] for key in (SUCCESS, FAILURE, INDETERMINATE)},
        },
        "probes": probes,
    }


def _http_observation(client: httpx.Client, url: str, **kwargs: Any) -> dict[str, Any]:
    started = time.monotonic()
    observation: dict[str, Any] = {"observed_at": timestamp()}
    try:
        response = client.get(url, **kwargs)
        try:
            body = response.json()
        except ValueError:
            body = response.text[:2000]
        observation.update(kind="response", status_code=response.status_code, body=body)
    except httpx.HTTPError as exc:
        observation.update(kind="error", error=type(exc).__name__)
    observation["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return observation


def _database_observation(database_url: str, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    observation: dict[str, Any] = {"observed_at": timestamp()}
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=max(1, math.ceil(timeout)),
            options=f"-c statement_timeout={max(1, math.ceil(timeout * 1000))}",
            row_factory=dict_row,
        ) as connection:
            connection.read_only = True
            rows = connection.execute(
                "SELECT sku, unit_price_minor, stock, currency FROM products ORDER BY sku"
            ).fetchall()
        observation.update(kind="rows", rows=rows)
    except psycopg.Error as exc:
        observation.update(kind="error", error=type(exc).__name__)
    observation["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return observation


def verify(
    quote_url: str,
    inventory_control_url: str,
    database_url: str,
    service_reader: Callable[[], dict[str, Any]],
    *,
    window_seconds: float = 30,
    interval_seconds: float = 1,
    request_timeout: float = 2,
    expected_target_port: int = 8080,
    expectations_path: Path = DEFAULT_EXPECTATIONS,
) -> dict[str, Any]:
    """Collect real HTTP, separate read-only database, and Kubernetes evidence."""
    _positive_finite("request_timeout", request_timeout)
    expectations = load_expectations(expectations_path)
    with httpx.Client(timeout=request_timeout, trust_env=False, follow_redirects=False) as client:

        def collect() -> dict[str, Any]:
            snapshot: dict[str, Any] = {
                "quote_control": _http_observation(client, quote_url.rstrip("/") + "/healthz"),
                "inventory_control": _http_observation(
                    client, inventory_control_url.rstrip("/") + "/healthz"
                ),
                "database": _database_observation(database_url, request_timeout),
            }
            service_started = time.monotonic()
            service_observed = timestamp()
            try:
                snapshot["service"] = {"kind": "resource", "resource": service_reader()}
            except Exception as exc:
                snapshot["service"] = {"kind": "error", "error": type(exc).__name__}
            snapshot["service"].update(
                observed_at=service_observed,
                elapsed_seconds=round(time.monotonic() - service_started, 6),
            )
            snapshot["quotes"] = [
                {
                    "case_id": case["id"],
                    **_http_observation(
                        client, quote_url.rstrip("/") + "/quote", params=case["params"]
                    ),
                }
                for case in expectations["quotes"]
            ]
            return snapshot

        return run_window(
            collect,
            expectations,
            window_seconds=window_seconds,
            interval_seconds=interval_seconds,
            expected_target_port=expected_target_port,
        )
