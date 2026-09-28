"""Frozen development calibration, never a learning-benefit evaluation."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import time
from pathlib import Path

import httpx
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from autonomy_lab.experiments import release_manifest
from autonomy_lab.procedures import require

from .audit import settled
from .harness import ROOT, Services, empty_database, save

ACTIONS = (1, 2, 4, 8, 16)
CONDITIONS = [(capacity, delay) for capacity in (1, 2, 16) for delay in (0.05, 0.1)]


def schedule(block):
    rng = random.Random(202609286100 + block)
    rows = []
    for repeat in range(3):
        group = [
            {
                "context": f"context-{c}",
                "capacity": capacity,
                "delay": delay,
                "action": action,
                "repeat": repeat,
            }
            for c, (capacity, delay) in enumerate(CONDITIONS)
            for action in ACTIONS
        ]
        rng.shuffle(group)
        rows.extend(group)
    return rows


def plan():
    files = [
        *sorted((ROOT / "experiments/request_settlement").glob("*.py")),
        ROOT / "src/autonomy_lab/quote.py",
        ROOT / "src/autonomy_lab/inventory.py",
        ROOT / "src/autonomy_lab/procedures.py",
        ROOT / "fixtures/database.sql",
        ROOT / "fixtures/expectations.json",
        ROOT / "uv.lock",
        ROOT / "infra/toolchain.json",
        ROOT / ".github/workflows/learning-settlement.yml",
        ROOT / "docs/LEARNING_SETTLEMENT.md",
        ROOT / "tests/test_request_settlement.py",
        ROOT / "experiments/__init__.py",
        ROOT / "pyproject.toml",
    ]
    manifest = release_manifest({})["files"]
    explicit = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    require(
        all(manifest[k] == explicit[k] for k in manifest.keys() & explicit.keys()),
        "Source changed while building manifest",
    )
    return {
        "kind": "development_opportunity_not_learning_proof",
        "blocks": [schedule(b) for b in range(2)],
        "batch_size": 128,
        "queue_inclusive_deadline_seconds": 1,
        "settlement_timeout_seconds": 8,
        "block_seconds_max": 600,
        "attempts_per_block": 1,
        "model_calls": 0,
        "candidate_selection": "post-outcome best measured fixed action per condition; optimistic descriptive diagnostic",
        "go_for_fresh_learning_study": "pooled selector gain >=5pp and each of two blocks >=3pp above its strongest fixed action; no guarantee about learning cost or generalization",
        "files": {
            **manifest,
            **explicit,
        },
    }


def verify_view(definition, delay):
    expected = f"""SELECT p.sku, p.unit_price_minor, p.stock, p.currency
    FROM products_data p CROSS JOIN (SELECT pg_sleep({delay}::double precision) AS pg_sleep) latency;"""

    def normalize(value):
        return "".join(value.split()).replace("(", "").replace(")", "")

    require(normalize(definition) == normalize(expected), "Read delay differs")


def classify(records, cases, action):
    require(
        len(records) == 128 and type(action) is int and action in ACTIONS,
        "Population or action differs",
    )
    counts = {
        "offered": 128,
        "dispatched": 0,
        "timely_correct": 0,
        "correct": 0,
        "server_errors": 0,
        "transport_errors": 0,
    }
    events, dispatched, known = [], set(), set()
    for i, r in enumerate(records):
        case = cases[i % len(cases)]
        require(r["index"] == i and r["case_id"] == case["id"], "Request identity differs")
        if r["start"] is None:
            require(
                r
                == {
                    "index": i,
                    "case_id": case["id"],
                    "start": None,
                    "end": None,
                    "status": None,
                    "body": None,
                },
                "Undispatched output",
            )
            continue
        require(
            all(type(r[k]) in (int, float) and math.isfinite(r[k]) for k in ("start", "end"))
            and 0 <= r["start"] < 1
            and r["start"] <= r["end"],
            "Invalid response timing",
        )
        dispatched.add(i)
        counts["dispatched"] += 1
        events.extend([(r["start"], 1), (r["end"], -1)])
        if r["status"] is None:
            require(
                set(r) == {"index", "case_id", "start", "end", "status", "body", "error_type"}
                and r["body"] is None
                and type(r["error_type"]) is str
                and bool(r["error_type"]),
                "Unexplained missing response",
            )
            counts["transport_errors"] += 1
            continue
        require(
            type(r["status"]) is int
            and 100 <= r["status"] <= 599
            and type(r["body"]) is str
            and set(r) == {"index", "case_id", "start", "end", "status", "body"},
            "Invalid response",
        )
        # These statuses are produced after entering the original Quote handler.
        if r["status"] in (200, 404, 503):
            known.add(i)
        counts["server_errors"] += r["status"] >= 500
        try:
            body = json.loads(r["body"])
        except ValueError:
            body = None
        ok = r["status"] == case["status_code"] and (
            "body" not in case
            or json.dumps(body, sort_keys=True) == json.dumps(case["body"], sort_keys=True)
        )
        counts["correct"] += ok
        counts["timely_correct"] += ok and r["end"] <= 1
    active = 0
    for _, change in sorted(events):
        active += change
        require(0 <= active <= action, "Concurrency exceeded")
    require(active == 0, "Client work outstanding")
    return counts, dispatched, known


async def batch(services, cases, action):
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
    async with httpx.AsyncClient(
        timeout=6,
        trust_env=False,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=16, max_keepalive_connections=0),
    ) as client:
        started = time.monotonic()
        pending = iter(records)

        async def worker():
            for r in pending:
                now = time.monotonic() - started
                if now >= 1:
                    continue
                r["start"] = now
                try:
                    response = await client.get(
                        services.urls["quote"] + "/quote",
                        params=cases[r["index"] % len(cases)]["params"],
                        headers=services.headers(r["index"]),
                    )
                    r.update(status=response.status_code, body=response.text)
                except httpx.HTTPError as error:
                    r["error_type"] = type(error).__name__
                finally:
                    r["end"] = time.monotonic() - started

        await asyncio.gather(*(worker() for _ in range(action)))
        return {"requests": records, "batch_seconds": time.monotonic() - started}


def run(bundle, block, destination):
    declared = json.loads(bundle.read_text())
    require(
        block in (0, 1) and declared["plan"] == plan() and declared["frozen_at"] < time.time(),
        "Declaration differs",
    )
    destination.mkdir(parents=True, exist_ok=False)
    save(destination / "declaration.json", declared)
    result = {"status": "failed", "block": block, "completed": 0, "started_at": time.time()}
    save(destination / "result.json", result)
    clock_start = time.monotonic()
    deadline = clock_start + 600
    try:
        admin = os.environ["SETTLEMENT_DATABASE_ADMIN_URL"]
        parameters = conninfo_to_dict(admin)
        parameters.update(user="inventory_reader", password="inventory-test-only")
        expected = json.loads((ROOT / "fixtures/expectations.json").read_text())
        save(destination / "expectations.json", expected)
        with (
            empty_database(admin) as db,
            Services(make_conninfo(**parameters), destination / "private-logs") as services,
        ):
            result["database_version"] = db.execute("SHOW server_version").fetchone()[0]
            result["instances"] = services.instances.copy()
            db.execute("ALTER TABLE products RENAME TO products_data")
            for i, identity in enumerate(schedule(block)):
                require(time.monotonic() + 20 < deadline, "Development budget exhausted")
                current = {"identity": identity, "status": "started"}
                path = destination / f"batch-{i:03}.json"
                save(path, current)
                try:
                    db.execute(
                        f"ALTER ROLE inventory_reader CONNECTION LIMIT {identity['capacity']}"
                    )
                    db.execute(
                        f"CREATE OR REPLACE VIEW products AS SELECT p.* FROM products_data p CROSS JOIN (SELECT pg_sleep({identity['delay']})) latency"
                    )
                    db.execute("GRANT SELECT ON products TO inventory_reader, verifier_reader")
                    capacity = db.execute(
                        "SELECT rolconnlimit FROM pg_roles WHERE rolname='inventory_reader'"
                    ).fetchone()[0]
                    require(capacity == identity["capacity"], "Capacity not established")
                    definition = db.execute(
                        "SELECT pg_get_viewdef('products'::regclass,true)"
                    ).fetchone()[0]
                    verify_view(definition, identity["delay"])
                    current.update(capacity=capacity, view=definition)
                    started = time.monotonic()
                    current["opened"] = services.open()
                    current.update(
                        asyncio.run(batch(services, expected["quotes"], identity["action"]))
                    )
                    score, dispatched, known = classify(
                        current["requests"], expected["quotes"], identity["action"]
                    )
                    current["closed"] = services.close()
                    known_downstream = {
                        r["index"] for r in current["requests"] if r["status"] in (200, 404)
                    }
                    current["settlement"] = services.await_settled(
                        dispatched, known, known_downstream=known_downstream, db=db
                    )
                    current.update(
                        score=score,
                        seconds_including_settlement=time.monotonic() - started,
                        status="complete",
                    )
                except BaseException as error:
                    current["error_type"] = type(error).__name__
                    raise
                finally:
                    save(path, current)
                result["completed"] = i + 1
                save(destination / "result.json", result)
            products = db.execute(
                "SELECT sku,unit_price_minor,stock,currency FROM products_data ORDER BY sku"
            ).fetchall()
            require(
                [
                    dict(zip(("sku", "unit_price_minor", "stock", "currency"), r, strict=True))
                    for r in products
                ]
                == expected["products"],
                "Product semantics changed",
            )
        result.update(status="complete", cleanup="service_processes_reaped")
    except BaseException as error:
        result["error_type"] = type(error).__name__
        raise
    finally:
        result["finished_at"] = time.time()
        result["elapsed_seconds"] = time.monotonic() - clock_start
        if result["elapsed_seconds"] > 600 or result["finished_at"] - result["started_at"] > 600:
            result.update(status="failed", error_type="BlockBudgetExceeded")
        result["files"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(destination.glob("batch-*.json"))
        }
        save(destination / "result.json", result)
    require(result["status"] == "complete", "Block budget exceeded")


def verify_budget(result):
    require(
        all(
            type(result[k]) in (int, float) and math.isfinite(result[k]) and result[k] >= 0
            for k in ("started_at", "finished_at", "elapsed_seconds")
        ),
        "Invalid block timing",
    )
    require(
        0 < result["elapsed_seconds"] <= 600
        and 0 <= result["finished_at"] - result["started_at"] <= 600,
        "Block budget exceeded",
    )


def audit(bundle, source, destination):
    declared = json.loads(bundle.read_text())
    require(declared["plan"] == plan(), "Frozen source differs")
    output = {
        "status": "incomplete",
        "rows": [],
        "errors": {},
        "decision": None,
        "autonomous_learning_proved": False,
    }
    for block in (0, 1):
        try:
            folder = source / f"opportunity-{block}"
            result = json.loads((folder / "result.json").read_text())
            verify_budget(result)
            expected = json.loads((folder / "expectations.json").read_text())
            require(
                expected == json.loads((ROOT / "fixtures/expectations.json").read_text()),
                "Oracle differs",
            )
            require(
                result["status"] == "complete"
                and result["completed"] == 90
                and result["cleanup"] == "service_processes_reaped",
                "Original block incomplete",
            )
            require(
                declared["frozen_at"] < result["started_at"] <= result["finished_at"],
                "Execution predates freeze",
            )
            require(
                json.loads((folder / "declaration.json").read_text()) == declared,
                "Declaration differs",
            )
            require(
                result["files"]
                == {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(folder.glob("batch-*.json"))
                },
                "Raw evidence changed",
            )
            require(
                set(result["files"]) == {f"batch-{i:03}.json" for i in range(90)},
                "Batch population differs",
            )
            for i, identity in enumerate(schedule(block)):
                b = json.loads((folder / f"batch-{i:03}.json").read_text())
                require(
                    b["identity"] == identity
                    and b["status"] == "complete"
                    and b["capacity"] == identity["capacity"],
                    "Identity or control differs",
                )
                verify_view(b["view"], identity["delay"])
                score, dispatched, known = classify(
                    b["requests"], expected["quotes"], identity["action"]
                )
                require(score == b["score"], "Score differs")
                require(
                    b["settlement"]["database_readers"] == 0
                    and 0 <= b["settlement"]["wait_seconds"] < 8,
                    "Database settlement not confirmed",
                )
                require(
                    settled(
                        b["settlement"]["receipts"],
                        result["instances"],
                        i + 1,
                        dispatched,
                        known,
                        {r["index"] for r in b["requests"] if r["status"] in (200, 404)},
                    )
                    == b["settlement"]["audit"],
                    "Settlement differs",
                )
                require(
                    type(b["seconds_including_settlement"]) in (int, float)
                    and math.isfinite(b["seconds_including_settlement"])
                    and b["seconds_including_settlement"] >= b["batch_seconds"] > 0,
                    "Invalid cost",
                )
                require(
                    all(r["end"] is None or r["end"] <= b["batch_seconds"] for r in b["requests"]),
                    "Response outside batch",
                )
                for service in ("quote", "inventory"):
                    initial = b["opened"][service]
                    require(
                        initial["instance"] == result["instances"][service]
                        and initial["epoch"] == i + 1
                        and initial["closed"] is False
                        and initial["admitted"] == initial["finished"] == 0
                        and initial["operations"] == {},
                        "Invalid opening receipt",
                    )
                    closed, final = b["closed"][service], b["settlement"]["receipts"][service]
                    require(
                        closed["instance"] == final["instance"]
                        and closed["epoch"] == final["epoch"]
                        and closed["closed"] is True
                        and closed["admitted"] == final["admitted"]
                        and set(closed["operations"]) == set(final["operations"])
                        and closed["finished"] <= final["finished"],
                        "Admission changed after fence",
                    )
                output["rows"].append(
                    {
                        "block": block,
                        **identity,
                        **score,
                        "seconds": b["seconds_including_settlement"],
                    }
                )
        except Exception as error:
            output["errors"][str(block)] = {"type": type(error).__name__, "reason": str(error)}
    if not output["errors"]:

        def diagnostic(blocks):
            cells = {}
            for context in [f"context-{c}" for c in range(6)]:
                cells[context] = {}
                for a in ACTIONS:
                    rows = [
                        r
                        for r in output["rows"]
                        if r["block"] in blocks and r["context"] == context and r["action"] == a
                    ]
                    cells[context][str(a)] = {
                        k: sum(r[k] for r in rows) for k in ("offered", "timely_correct", "seconds")
                    }

            def rate(cell):
                return cell["timely_correct"] / cell["offered"]

            fixed = {str(a): sum(rate(v[str(a)]) for v in cells.values()) / 6 for a in ACTIONS}
            choices = {c: max(v, key=lambda a: rate(v[a])) for c, v in cells.items()}
            selector = sum(rate(cells[c][a]) for c, a in choices.items()) / 6
            return {
                "cells": cells,
                "fixed_rates": fixed,
                "posthoc_choices": choices,
                "posthoc_selector_rate": selector,
                "descriptive_gain": selector - max(fixed.values()),
            }

        pooled, blocks = diagnostic([0, 1]), [diagnostic([b]) for b in (0, 1)]
        output.update(
            status="complete",
            decision={
                "pooled": pooled,
                "blocks": blocks,
                "enough_descriptive_room_for_fresh_test": pooled["descriptive_gain"] >= 0.05
                and all(b["descriptive_gain"] >= 0.03 for b in blocks),
                "learning_or_generalization_proved": False,
            },
        )
    save(destination, output)
    require(output["status"] == "complete", "Incomplete development evidence; decision withheld")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("destination", type=Path)
    execute = sub.add_parser("run")
    execute.add_argument("bundle", type=Path)
    execute.add_argument("block", type=int)
    execute.add_argument("destination", type=Path)
    replay = sub.add_parser("audit")
    replay.add_argument("bundle", type=Path)
    replay.add_argument("source", type=Path)
    replay.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        require(not args.destination.exists(), "Cannot overwrite declaration")
        save(args.destination, {"frozen_at": time.time(), "plan": plan()})
    elif args.command == "run":
        run(args.bundle, args.block, args.destination)
    else:
        audit(args.bundle, args.source, args.destination)
