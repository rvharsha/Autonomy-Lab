"""Isolated application and HTTP protocol tests; not live-cluster evidence."""

from contextlib import contextmanager

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from autonomy_lab import inventory, quote


@contextmanager
def quote_client(handler):
    with TestClient(quote.app) as client:
        with client.portal.wrap_async_context_manager(
            httpx.AsyncClient(
                base_url="http://inventory:8000/", transport=httpx.MockTransport(handler)
            )
        ) as backend:
            quote.app.state.inventory_client = backend
            yield client


@pytest.mark.parametrize(
    "sku,quantity,unit_price,stock,total,available",
    [
        ("bolt", 1, 125, 100, 125, True),
        ("bolt", 4, 125, 100, 500, True),
        ("motor", 3, 2499, 3, 7497, True),
        ("motor", 4, 2499, 3, 9996, False),
        ("washer", 1, 25, 0, 25, False),
    ],
)
def test_quote_calculation_and_backend_request(sku, quantity, unit_price, stock, total, available):
    def respond(request):
        assert request.url.path == f"/inventory/{sku}"
        assert request.url.params["quantity"] == str(quantity)
        return httpx.Response(
            200,
            json={
                "sku": sku,
                "unit_price_minor": unit_price,
                "stock": stock,
                "available": available,
                "currency": "USD",
            },
        )

    with quote_client(respond) as client:
        response = client.get("/quote", params={"sku": sku, "quantity": quantity})
    assert response.status_code == 200
    assert response.json() == {
        "sku": sku,
        "quantity": quantity,
        "unit_price_minor": unit_price,
        "total_minor": total,
        "available": available,
        "currency": "USD",
    }


@pytest.mark.parametrize("quantity", [0, -1, "1.5", "banana"])
def test_quote_rejects_invalid_quantity_without_backend_request(quantity):
    def unexpected(request):
        pytest.fail("invalid input must not reach Inventory")

    with quote_client(unexpected) as client:
        assert client.get("/quote", params={"sku": "bolt", "quantity": quantity}).status_code == 422


@pytest.mark.parametrize("status,expected", [(404, 404), (500, 503), (503, 503), (302, 503)])
def test_quote_backend_status(status, expected):
    with quote_client(lambda request: httpx.Response(status)) as client:
        response = client.get("/quote", params={"sku": "missing"})
    assert response.status_code == expected
    assert response.json() == {
        "detail": "unknown sku" if expected == 404 else "inventory unavailable"
    }


def test_quote_timeout_and_health_independence():
    def timeout(request):
        raise httpx.ReadTimeout("test transport timeout", request=request)

    with quote_client(timeout) as client:
        assert client.get("/quote", params={"sku": "bolt"}).status_code == 503
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "changes",
    [
        {"unit_price_minor": "125"},
        {"unit_price_minor": True},
        {"unit_price_minor": -1},
        {"stock": -1},
        {"available": "true"},
        {"available": False},
        {"currency": "EUR"},
        {"sku": "motor"},
        {"unexpected": "field"},
    ],
)
def test_quote_rejects_invalid_backend_data(changes):
    data = {"sku": "bolt", "unit_price_minor": 125, "stock": 100, "available": True, "currency": "USD"}
    data.update(changes)
    with quote_client(lambda request: httpx.Response(200, json=data)) as client:
        assert client.get("/quote", params={"sku": "bolt"}).status_code == 503


@pytest.mark.parametrize("body", [b"not json", b"{}", b"null", b"[]"])
def test_quote_rejects_unusable_backend_body(body):
    with quote_client(lambda request: httpx.Response(200, content=body)) as client:
        assert client.get("/quote", params={"sku": "bolt"}).status_code == 503


def test_declared_wrong_total_fault(monkeypatch):
    monkeypatch.setenv("QUOTE_TOTAL_OFFSET", "1")
    data = {"sku": "bolt", "unit_price_minor": 125, "stock": 100, "available": True, "currency": "USD"}
    with quote_client(lambda request: httpx.Response(200, json=data)) as client:
        response = client.get("/quote", params={"sku": "bolt", "quantity": 4})
    assert response.status_code == 200
    assert response.json()["total_minor"] == 501


@pytest.mark.parametrize("quantity,available", [(3, True), (4, False)])
def test_inventory_availability(monkeypatch, quantity, available):
    def product(sku):
        assert sku == "motor"
        return {"sku": "motor", "unit_price_minor": 2499, "stock": 3, "currency": "USD"}

    monkeypatch.setattr(inventory, "read_product", product)
    with TestClient(inventory.app) as client:
        response = client.get("/inventory/motor", params={"quantity": quantity})
    assert response.status_code == 200
    assert response.json() == {
        "sku": "motor", "unit_price_minor": 2499, "stock": 3,
        "available": available, "currency": "USD",
    }


def test_inventory_unknown_sku(monkeypatch):
    monkeypatch.setattr(inventory, "read_product", lambda sku: None)
    with TestClient(inventory.app) as client:
        response = client.get("/inventory/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "unknown sku"}


def test_inventory_database_outage_preserves_liveness(monkeypatch):
    def unavailable(*args, **kwargs):
        raise psycopg.OperationalError("test database unavailable")

    monkeypatch.setattr(inventory.psycopg, "connect", unavailable)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test-only")
    with TestClient(inventory.app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        assert client.get("/inventory/bolt").status_code == 503


@pytest.mark.parametrize("quantity", [0, -1, "2.1"])
def test_inventory_rejects_invalid_quantity(monkeypatch, quantity):
    def unexpected(sku):
        pytest.fail("invalid input must not query PostgreSQL")

    monkeypatch.setattr(inventory, "read_product", unexpected)
    with TestClient(inventory.app) as client:
        assert client.get("/inventory/bolt", params={"quantity": quantity}).status_code == 422
