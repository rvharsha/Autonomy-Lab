"""Real timeout, late admission, cancellation and restart engineering evidence."""

import argparse
import copy
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from autonomy_lab.procedures import Refused, require

from .audit import settled
from .harness import Services, empty_database, save


def delay(db, seconds):
    require(seconds in (0, 4), "Undeclared engineering delay")
    db.execute(
        f"CREATE OR REPLACE VIEW products AS SELECT p.* FROM products_data p CROSS JOIN (SELECT pg_sleep({seconds})) latency"
    )


def request(services, identity, *, timeout=6):
    start = time.monotonic()
    try:
        response = httpx.get(
            services.urls["quote"] + "/quote",
            params={"sku": "bolt", "quantity": 1},
            headers=services.headers(identity),
            timeout=timeout,
            trust_env=False,
        )
        return {
            "identity": identity,
            "status": response.status_code,
            "body": response.text,
            "seconds": time.monotonic() - start,
        }
    except httpx.HTTPError as error:
        return {
            "identity": identity,
            "status": None,
            "error_type": type(error).__name__,
            "seconds": time.monotonic() - start,
        }


def refuse(call, phrase):
    try:
        call()
    except Refused as error:
        require(phrase in str(error), "Unexpected audit rejection")
        return {"rejected": True, "reason": str(error)}
    raise RuntimeError("Invalid evidence accepted")


def run(destination):
    destination.mkdir(parents=True, exist_ok=False)
    record = {
        "kind": "real_service_engineering_probe_not_learning_evidence",
        "status": "started",
        "cases": {},
    }
    save(destination / "result.json", record)
    try:
        admin = os.environ["SETTLEMENT_DATABASE_ADMIN_URL"]
        parameters = conninfo_to_dict(admin)
        parameters.update(user="inventory_reader", password="inventory-test-only")
        with (
            empty_database(admin) as db,
            Services(make_conninfo(**parameters), destination / "private-logs") as services,
        ):
            record["database_version"] = db.execute("SHOW server_version").fetchone()[0]
            record["instances"] = services.instances.copy()
            db.execute("ALTER TABLE products RENAME TO products_data")
            delay(db, 4)
            db.execute("GRANT SELECT ON products TO inventory_reader, verifier_reader")
            services.open()
            response = request(services, 0)
            require(
                response["status"] == 503 and response["seconds"] >= 2.5,
                "Real upstream timeout not observed",
            )
            closed = services.close()
            require(
                closed["inventory"]["operations"]["0"]["state"] == "active",
                "Downstream did not outlive timeout",
            )
            rejection = refuse(
                lambda: settled(closed, services.instances, services.epoch, {0}, {0}), "Outstanding"
            )
            final = services.await_settled({0}, {0}, db=db)
            record["cases"]["upstream_timeout"] = {
                "response": response,
                "closed": closed,
                "early_rejection": rejection,
                "final": final,
            }
            save(destination / "result.json", record)

            # A closed batch has no active work, but a delayed old request must
            # still be refused after the next epoch has opened.
            old = services.epoch
            services.open()
            late = httpx.get(
                services.urls["inventory"] + "/inventory/bolt",
                headers=services.headers(1, "inventory", old),
                timeout=3,
                trust_env=False,
            )
            require(
                late.status_code == 409 and services.control("inventory")["admitted"] == 0,
                "Late request admitted",
            )
            services.close()
            record["cases"]["late_admission"] = {
                "old_epoch": old,
                "new_epoch": services.epoch,
                "status": late.status_code,
                "final": services.await_settled(set(), set(), db=db),
            }

            services.open()
            # Cancel the real HTTP wait only after observing SQL worker admission.
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(request, services, 0, timeout=0.8)
                deadline = time.monotonic() + 0.7
                while not services.control("inventory")["operations"]:
                    require(time.monotonic() < deadline, "Cancellation probe not admitted in time")
                    time.sleep(0.01)
                response = future.result()
            require(
                response["status"] is None and response["error_type"] == "ReadTimeout",
                "Client did not time out",
            )
            closed = services.close()
            require(closed["inventory"]["finished"] == 0, "Cancellation manufactured completion")
            final = services.await_settled({0}, set(), db=db)
            record["cases"]["client_timeout"] = {
                "response": response,
                "closed": closed,
                "final": final,
            }
            save(destination / "result.json", record)

            delay(db, 0)
            services.open()
            response = request(services, 0)
            require(
                response["status"] == 200 and '"total_minor":125' in response["body"],
                "Healthy semantics changed",
            )
            duplicate = request(services, 0)
            require(duplicate["status"] == 409, "Duplicate executed")
            services.close()
            final = services.await_settled({0}, {0}, db=db)
            record["cases"]["healthy_and_duplicate"] = {
                "response": response,
                "duplicate": duplicate,
                "final": final,
            }

            # Corrupt an accepted original receipt, preserving the actual original.
            accepted = final["receipts"]
            mutations = {}
            changed = copy.deepcopy(accepted)
            changed["inventory"]["closed"] = False
            mutations["open_fence"] = (changed, "Admission remains open")
            changed = copy.deepcopy(accepted)
            changed["inventory"]["operations"].clear()
            mutations["missing_terminal"] = (changed, "Outstanding or missing")
            changed = copy.deepcopy(accepted)
            changed["inventory"]["operations"]["1"] = changed["inventory"]["operations"].pop("0")
            mutations["unissued_identity"] = (changed, "Unissued operation")
            changed = copy.deepcopy(accepted)
            changed["inventory"]["finished"] += 1
            mutations["duplicate_terminal"] = (changed, "Outstanding or missing")
            changed = copy.deepcopy(accepted)
            for item in changed.values():
                item.update(admitted=0, finished=0, operations={})
            mutations["forged_quiescence"] = (changed, "Known admission missing")
            changed = copy.deepcopy(accepted)
            changed["inventory"].update(admitted=0, finished=0, operations={})
            mutations["missing_successful_downstream"] = (
                changed,
                "Known downstream admission missing",
            )
            record["negative_controls"] = {
                name: refuse(
                    lambda r=r: settled(r, services.instances, services.epoch, {0}, {0}, {0}),
                    reason,
                )
                for name, (r, reason) in mutations.items()
            }

            services.stop("inventory")
            restarted = services.start("inventory")
            require(
                restarted["instance"] != services.instances["inventory"],
                "Instance reused after restart",
            )
            try:
                services.open()
            except httpx.HTTPStatusError as error:
                require(error.response.status_code == 409, "Unexpected restart refusal")
                record["restart_open_status"] = error.response.status_code
            else:
                raise RuntimeError("Controller adopted restarted service")
            changed = {**accepted, "inventory": restarted}
            record["cases"]["restart"] = {
                "observed": restarted,
                "rejection": refuse(
                    lambda: settled(
                        changed, services.instances, accepted["quote"]["epoch"], {0}, {0}
                    ),
                    "Instance or epoch changed",
                ),
            }
        record.update(status="complete", cleanup="service_processes_reaped")
    except BaseException as error:
        record.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        save(destination / "result.json", record)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    run(parser.parse_args().destination)
