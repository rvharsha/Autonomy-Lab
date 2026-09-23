"""Quote API using the Inventory Service network path."""

import os
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import quote as quote_path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class InventoryResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    sku: str = Field(min_length=1)
    unit_price_minor: int = Field(ge=0)
    stock: int = Field(ge=0)
    available: bool
    currency: Literal["USD"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.total_offset = int(os.environ.get("QUOTE_TOTAL_OFFSET", "0"))
    async with httpx.AsyncClient(
        base_url=os.environ.get("INVENTORY_URL", "http://inventory:8000").rstrip("/") + "/",
        timeout=httpx.Timeout(3.0),
        # The lab's routing-fault contract requires each request to open a fresh
        # connection through the Service instead of reusing a pre-fault socket.
        limits=httpx.Limits(max_keepalive_connections=0),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        app.state.inventory_client = client
        yield


app = FastAPI(title="Autonomy Lab Quote", lifespan=lifespan)


@app.get("/healthz")
@app.get("/readyz")
def health() -> dict:
    # Keep the process ready during the Service routing fault being measured.
    return {"status": "ok"}


@app.get("/quote")
async def quote(request: Request, sku: str, quantity: int = Query(default=1, gt=0)) -> dict:
    try:
        response = await request.app.state.inventory_client.get(
            "inventory/" + quote_path(sku, safe=""), params={"quantity": quantity}
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="unknown sku")
        response.raise_for_status()
        product = InventoryResponse.model_validate(response.json())
        if product.sku != sku or product.available != (product.stock >= quantity):
            raise ValueError("inconsistent inventory response")
    except (httpx.HTTPError, ValueError, ValidationError):
        raise HTTPException(status_code=503, detail="inventory unavailable") from None
    return {
        "sku": sku,
        "quantity": quantity,
        "unit_price_minor": product.unit_price_minor,
        "total_minor": product.unit_price_minor * quantity + request.app.state.total_offset,
        "available": product.available,
        "currency": product.currency,
    }
