"""Read-only inventory service backed by PostgreSQL."""

import os

import psycopg
from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row

app = FastAPI(title="Autonomy Lab Inventory")


def read_product(sku: str) -> dict | None:
    with psycopg.connect(
        os.environ["DATABASE_URL"], connect_timeout=3, row_factory=dict_row
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT sku, unit_price_minor, stock, currency FROM products WHERE sku = %s",
                (sku,),
            )
            return cursor.fetchone()


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def ready() -> dict:
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3) as connection:
            connection.execute("SELECT 1").fetchone()
    except (KeyError, psycopg.Error):
        raise HTTPException(status_code=503, detail="database unavailable") from None
    return {"status": "ok"}


@app.get("/inventory/{sku}")
def inventory(sku: str, quantity: int = Query(default=1, gt=0)) -> dict:
    try:
        product = read_product(sku)
    except (KeyError, psycopg.Error):
        raise HTTPException(status_code=503, detail="database unavailable") from None
    if product is None:
        raise HTTPException(status_code=404, detail="unknown sku")
    return {**product, "available": product["stock"] >= quantity}
