"""Experimental wrappers around the real services; one process per service.

Closing an epoch prevents future admission before observing active work. Terminal
Inventory receipts are written by the SQL worker after its connection has closed,
not by the HTTP client that may have already timed out. Restart loses evidence and
changes the instance identity; callers must refuse that change.
"""

import copy
import hmac
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from autonomy_lab import inventory, quote

FORWARD = ContextVar("settlement_forward_headers")


class Epoch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instance: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    epoch: StrictInt = Field(ge=1, le=1_000_000_000)
    downstream_instance: str | None = Field(
        default=None, min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"
    )


class Gate:
    def __init__(self):
        self.instance = uuid.uuid4().hex
        self.epoch = 0
        self.closed = True
        self.downstream = None
        self.operations = {}
        self.admitted = self.finished = 0
        self.lock = threading.Lock()

    def _identity(self, instance, epoch):
        if instance != self.instance or epoch != self.epoch:
            raise HTTPException(409, "instance or epoch differs")

    def snapshot(self):
        with self.lock:
            return self._snapshot()

    def _snapshot(self):
        return {
            "instance": self.instance,
            "epoch": self.epoch,
            "closed": self.closed,
            "downstream_instance": self.downstream,
            "admitted": self.admitted,
            "finished": self.finished,
            "operations": copy.deepcopy(self.operations),
        }

    def open(self, request):
        with self.lock:
            if request.instance != self.instance or request.epoch != self.epoch + 1:
                raise HTTPException(409, "instance changed or epoch not next")
            if not self.closed or any(r["state"] != "finished" for r in self.operations.values()):
                raise HTTPException(409, "previous epoch not settled")
            self.epoch, self.closed, self.operations = request.epoch, False, {}
            self.admitted = self.finished = 0
            self.downstream = request.downstream_instance
            return self._snapshot()

    def close(self, request):
        with self.lock:
            self._identity(request.instance, request.epoch)
            self.closed = True
            return self._snapshot()

    @contextmanager
    def operation(self, headers):
        instance = headers.get("x-lab-instance")
        try:
            epoch = int(headers["x-lab-epoch"])
            identity = int(headers["x-lab-operation"])
            if str(epoch) != headers["x-lab-epoch"] or str(identity) != headers["x-lab-operation"]:
                raise ValueError
            if not 0 <= identity < 128:
                raise ValueError
        except (KeyError, ValueError):
            raise HTTPException(409, "invalid operation identity") from None
        with self.lock:
            self._identity(instance, epoch)
            if self.closed or str(identity) in self.operations:
                raise HTTPException(409, "closed epoch or duplicate operation")
            record = {"state": "active", "started": time.monotonic(), "finished": None}
            self.operations[str(identity)] = record
            self.admitted += 1
            downstream = self.downstream
        try:
            yield {
                "x-lab-instance": downstream,
                "x-lab-epoch": str(epoch),
                "x-lab-operation": str(identity),
            }
        finally:
            # A synchronous Inventory handler reaches this only after read_product
            # has returned/raised and its connection context has closed.
            with self.lock:
                record.update(state="finished", finished=time.monotonic())
                self.finished += 1


def factory(kind):
    if kind not in ("quote", "inventory"):
        raise ValueError("Unknown service")
    token = os.environ["EXPERIMENT_CONTROL_TOKEN"]
    if len(token) < 32:
        raise ValueError("A dedicated control token is required")
    gate = Gate()

    async def propagate(request):
        headers = FORWARD.get(None)
        if headers is None or headers["x-lab-instance"] is None:
            raise HTTPException(409, "downstream call outside admitted operation")
        request.headers.update(headers)

    @asynccontextmanager
    async def lifespan(app):
        if kind == "quote":
            async with quote.lifespan(app):
                app.state.inventory_client.event_hooks["request"] = [propagate]
                yield
        else:
            yield

    app = FastAPI(lifespan=lifespan)
    app.state.gate = gate

    def authorize(request):
        if not hmac.compare_digest(request.headers.get("x-lab-control", ""), token):
            raise HTTPException(403, "control authority required")

    @app.get("/__experiment/state")
    async def state(request: Request):
        authorize(request)
        return gate.snapshot()

    @app.post("/__experiment/open")
    async def open_epoch(request: Request, body: Epoch):
        authorize(request)
        if (body.downstream_instance is not None) != (kind == "quote"):
            raise HTTPException(409, "downstream identity differs")
        return gate.open(body)

    @app.post("/__experiment/close")
    async def close_epoch(request: Request, body: Epoch):
        authorize(request)
        return gate.close(body)

    if kind == "quote":

        @app.get("/quote")
        async def handle_quote(request: Request, sku: str, quantity: int = Query(1, gt=0)):
            with gate.operation(request.headers) as headers:
                binding = FORWARD.set(headers)
                try:
                    return await quote.quote(request, sku, quantity)
                finally:
                    FORWARD.reset(binding)
    else:

        @app.get("/inventory/{sku}")
        def handle_inventory(request: Request, sku: str, quantity: int = Query(1, gt=0)):
            with gate.operation(request.headers):
                return inventory.inventory(sku, quantity)

    return app


def quote_app():
    return factory("quote")


def inventory_app():
    return factory("inventory")
