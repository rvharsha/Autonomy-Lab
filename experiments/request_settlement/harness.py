"""Run the real service handlers in dedicated loopback worker processes."""

import contextlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from autonomy_lab.procedures import require

from .audit import settled

ROOT = Path(__file__).resolve().parents[2]


class Services:
    def __init__(self, database_url, directory):
        self.database_url = database_url
        self.directory = Path(directory)
        self.token = secrets.token_hex(32)
        self.processes, self.logs, self.urls, self.instances = {}, [], {}, {}
        self.epoch = 0
        self.client = httpx.Client(timeout=10, trust_env=False)

    def control(self, service, action="state", body=None):
        url = self.urls[service] + "/__experiment/" + action
        response = self.client.request(
            "GET" if body is None else "POST", url, headers={"x-lab-control": self.token}, json=body
        )
        response.raise_for_status()
        return response.json()

    def start(self, service):
        require(
            service not in self.processes or self.processes[service].poll() is not None,
            "Cannot replace a running service process",
        )
        # Starting a replacement deliberately does not adopt its new identity.
        # The existing controller must refuse it; a new run needs a new harness.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            self.urls[service] = f"http://127.0.0.1:{sock.getsockname()[1]}"
            log = (self.directory / f"{service}-{time.time_ns()}.log").open("wb")
            self.logs.append(log)
            env = {
                **os.environ,
                "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT),
                "EXPERIMENT_CONTROL_TOKEN": self.token,
                "DATABASE_URL": self.database_url,
                "INVENTORY_URL": self.urls.get("inventory", ""),
                "QUOTE_TOTAL_OFFSET": "0",
            }
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    f"experiments.request_settlement.services:{service}_app",
                    "--factory",
                    "--fd",
                    str(sock.fileno()),
                    "--workers",
                    "1",
                    "--no-access-log",
                ],
                env=env,
                pass_fds=(sock.fileno(),),
                stdout=log,
                stderr=log,
            )
            self.processes[service] = process
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            require(process.poll() is None, "Service process failed")
            try:
                return self.control(service)
            except httpx.HTTPError:
                time.sleep(0.05)
        raise RuntimeError("Service startup timeout")

    def stop(self, service):
        process = self.processes[service]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        require(process.poll() is not None, "Service not reaped")

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            for service in ("inventory", "quote"):
                self.instances[service] = self.start(service)["instance"]
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        errors = []
        for service in reversed(self.processes):
            try:
                self.stop(service)
            except Exception as error:
                errors.append(type(error).__name__)
        self.client.close()
        for log in self.logs:
            log.close()
        require(not errors, "Service cleanup failed: " + ",".join(errors))

    def open(self):
        self.epoch += 1
        receipts = {}
        for service in ("inventory", "quote"):
            body = {"instance": self.instances[service], "epoch": self.epoch}
            if service == "quote":
                body["downstream_instance"] = self.instances["inventory"]
            receipts[service] = self.control(service, "open", body)
        return receipts

    def headers(self, identity, service="quote", epoch=None):
        return {
            "x-lab-instance": self.instances[service],
            "x-lab-epoch": str(self.epoch if epoch is None else epoch),
            "x-lab-operation": str(identity),
        }

    def close(self):
        return {
            service: self.control(
                service, "close", {"instance": self.instances[service], "epoch": self.epoch}
            )
            for service in ("quote", "inventory")
        }

    def await_settled(
        self, dispatched, known_admitted, timeout=8, known_downstream=frozenset(), db=None
    ):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            receipts = {service: self.control(service) for service in ("quote", "inventory")}
            # An identity change cannot become acceptable through waiting.
            require(
                all(
                    receipts[k]["instance"] == self.instances[k]
                    and receipts[k]["epoch"] == self.epoch
                    and receipts[k]["closed"] is True
                    for k in receipts
                ),
                "Fence or identity changed",
            )
            if all(r["admitted"] == r["finished"] for r in receipts.values()):
                result = settled(
                    receipts,
                    self.instances,
                    self.epoch,
                    dispatched,
                    known_admitted,
                    known_downstream,
                )
                readers = None
                if db is not None:
                    readers = db.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE usename='inventory_reader'"
                    ).fetchone()[0]
                    if readers != 0:
                        time.sleep(0.02)
                        continue
                require(time.monotonic() - start < timeout, "Settlement budget exhausted")
                return {
                    "receipts": receipts,
                    "audit": result,
                    "wait_seconds": time.monotonic() - start,
                    "database_readers": readers,
                }
            time.sleep(0.02)
        raise RuntimeError("Unresolved downstream work")


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


@contextlib.contextmanager
def empty_database(url):
    """Only a fresh dedicated lab database; never reset an existing one."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    parameters = conninfo_to_dict(url)
    require(
        parameters.get("host", "").startswith("/")
        or parameters.get("host") in ("127.0.0.1", "localhost"),
        "Dedicated local database required",
    )
    require(parameters.get("dbname") == "lab", "Dedicated lab database required")
    with psycopg.connect(url, autocommit=True, connect_timeout=3) as db:
        db.execute("SET statement_timeout=1000")
        count = db.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
        ).fetchone()[0]
        require(count == 0, "Refuse nonempty database")
        db.execute((ROOT / "fixtures/database.sql").read_text())
        yield db
