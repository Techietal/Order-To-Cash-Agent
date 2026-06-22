"""
Tests for api/inventory.py

Uses the same FakeDB / TestClient pattern as test_auth.py.
No real PostgreSQL connection required.

Key design:
  staff_deps.get_db and inventory.get_db both resolve to the same
  database.postgres.get_db function object.  We install a single
  dependency_overrides entry that returns one UnifiedFakeDB — an
  object that can satisfy both the auth lookup (fetchrow returning
  a staff user record) and inventory queries (fetch / fetchval returning
  whatever the test configured).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from api import inventory, staff_deps
from database.postgres import get_db as postgres_get_db
from passwords import hash_password


# ── FakeRecord & unified FakeDB ───────────────────────────────────────────────

class FakeRecord(dict):
    """asyncpg Record substitute — a dict with key-based access."""
    pass


class UnifiedFakeDB:
    """
    Single fake that serves both staff_deps (fetchrow auth lookups) and
    inventory endpoints (fetch / fetchval / execute).

    Auth detection: staff_deps always calls
        fetchrow("SELECT username … FROM staff_users WHERE username = $1", username)
    We sniff for 'staff_users' in the SQL to return the staff user row.
    All other fetchrow calls return self._row.
    """

    def __init__(self, staff_user: dict):
        self._staff_user = staff_user
        self._row = None           # default fetchrow return for non-auth queries
        self._rows: list = []      # default fetch return
        self._fetchval_return = 0
        self.executed: list = []

    async def fetchrow(self, query, *args):
        if "staff_users" in query:
            return self._staff_user
        return self._row

    async def fetch(self, query, *args):
        return self._rows

    async def fetchval(self, query, *args):
        return self._fetchval_return

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "OK"


def _staff(role="admin"):
    return {
        "username": f"{role}_user",
        "password_hash": hash_password("pass"),
        "role": role,
        "display_name": "Test User",
        "is_active": True,
    }


def _auth_header(role="admin"):
    from jose import jwt
    from config import settings
    token = jwt.encode(
        {"sub": f"{role}_user", "role": role},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


# ── App builder ───────────────────────────────────────────────────────────────

def build_app(db: UnifiedFakeDB) -> FastAPI:
    """Minimal FastAPI with inventory router; single DB override."""
    app = FastAPI()
    app.include_router(inventory.router, prefix="/api/inventory")

    async def override_db():
        return db

    app.dependency_overrides[postgres_get_db] = override_db
    return app


# ── GET /transactions — auth guards ──────────────────────────────────────────

def test_transactions_requires_auth():
    """GET /transactions returns 401 with no token."""
    db = UnifiedFakeDB(_staff("admin"))
    client = TestClient(build_app(db))
    response = client.get("/api/inventory/transactions")
    assert response.status_code == 401


def test_transactions_requires_correct_role():
    """GET /transactions returns 403 for collections_analyst (not in INVENTORY_READ_ROLES)."""
    db = UnifiedFakeDB(_staff("collections_analyst"))
    client = TestClient(build_app(db))
    response = client.get(
        "/api/inventory/transactions",
        headers=_auth_header("collections_analyst"),
    )
    assert response.status_code == 403


def test_transactions_returns_200_for_inventory_manager():
    """GET /transactions returns 200 and correct shape for inventory_manager role."""
    db = UnifiedFakeDB(_staff("inventory_manager"))
    db._rows = [
        FakeRecord({
            "txn_id": "TXN-001", "sku_id": "SKU-001",
            "txn_type": "STOCK_ADJUSTMENT", "quantity_delta": 50,
            "field_affected": "stock_on_hand", "balance_after": 150,
            "order_id": None, "purchase_order_id": None,
            "reason": "opening stock", "performed_by": "system",
            "actor_type": "system", "created_at": "2025-01-01T00:00:00+00:00",
        })
    ]
    db._fetchval_return = 1

    client = TestClient(build_app(db))
    response = client.get(
        "/api/inventory/transactions",
        headers=_auth_header("inventory_manager"),
    )

    assert response.status_code == 200
    data = response.json()
    assert "transactions" in data
    assert data["total"] == 1
    assert data["transactions"][0]["txn_type"] == "STOCK_ADJUSTMENT"


# ── POST /adjust — auth and role guards ──────────────────────────────────────

def test_adjust_requires_auth():
    """POST /adjust returns 401 with no token."""
    db = UnifiedFakeDB(_staff("admin"))
    client = TestClient(build_app(db))
    response = client.post("/api/inventory/adjust", json={
        "sku_id": "SKU-001", "quantity_delta": 10,
        "txn_type": "STOCK_ADJUSTMENT", "reason": "test",
    })
    assert response.status_code == 401


def test_adjust_requires_correct_role():
    """POST /adjust returns 403 for dispute_manager role."""
    db = UnifiedFakeDB(_staff("dispute_manager"))
    client = TestClient(build_app(db))
    response = client.post(
        "/api/inventory/adjust",
        headers=_auth_header("dispute_manager"),
        json={
            "sku_id": "SKU-001", "quantity_delta": 10,
            "txn_type": "STOCK_ADJUSTMENT", "reason": "test reason",
        },
    )
    assert response.status_code == 403


def test_adjust_calls_inventory_service_and_returns_txn_id():
    """POST /adjust returns txn_id when inventory_service succeeds."""
    db = UnifiedFakeDB(_staff("admin"))
    db._row = FakeRecord({
        "sku_id": "SKU-001", "product_name": "Test", "category": "Test",
        "stock_on_hand": 110, "reserved_stock": 5,
        "available_stock": 105, "incoming_stock": 0,
        "reorder_level": 20, "safety_stock": 10,
    })

    mock_result = {
        "sku_id": "SKU-001",
        "new_stock_on_hand": 110,
        "txn_id": "TXN-MOCK001",
        "warning": None,
    }

    with patch(
        "api.inventory.record_adjustment",
        new=AsyncMock(return_value=mock_result),
    ):
        client = TestClient(build_app(db))
        response = client.post(
            "/api/inventory/adjust",
            headers=_auth_header("admin"),
            json={
                "sku_id": "SKU-001", "quantity_delta": 10,
                "txn_type": "STOCK_ADJUSTMENT", "reason": "physical count",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["txn_id"] == "TXN-MOCK001"
    assert data["new_stock_on_hand"] == 110


def test_adjust_returns_400_on_invalid_txn_type():
    """POST /adjust returns 400 when inventory_service raises ValueError."""
    db = UnifiedFakeDB(_staff("admin"))

    with patch(
        "api.inventory.record_adjustment",
        new=AsyncMock(side_effect=ValueError("not a valid adjustment type")),
    ):
        client = TestClient(build_app(db))
        response = client.post(
            "/api/inventory/adjust",
            headers=_auth_header("admin"),
            json={
                "sku_id": "SKU-001", "quantity_delta": 10,
                "txn_type": "ORDER_RESERVATION",   # invalid for adjust endpoint
                "reason": "wrong type",
            },
        )

    assert response.status_code == 400
    assert "not a valid adjustment type" in response.json()["detail"]


# ── GET /stock-summary ────────────────────────────────────────────────────────

def test_stock_summary_requires_auth():
    """GET /stock-summary returns 401 with no token."""
    db = UnifiedFakeDB(_staff("admin"))
    client = TestClient(build_app(db))
    response = client.get("/api/inventory/stock-summary")
    assert response.status_code == 401


def test_stock_summary_returns_reorder_status():
    """GET /stock-summary annotates each SKU with the correct reorder_status."""
    db = UnifiedFakeDB(_staff("admin"))
    db._rows = [
        FakeRecord({
            "sku_id": "SKU-001", "product_name": "Motor",
            "category": "Machinery", "unit_of_measure": "Units",
            "base_price_inr": 15000, "stock_on_hand": 100,
            "reserved_stock": 10, "available_stock": 90,
            "incoming_stock": 0, "reorder_level": 80,
            "safety_stock": 30, "lead_time_days": 14,
            "reorder_qty": 100, "is_active": True,
        }),
        FakeRecord({
            "sku_id": "SKU-002", "product_name": "Wire",
            "category": "Electricals", "unit_of_measure": "Rolls",
            "base_price_inr": 4500, "stock_on_hand": 25,
            "reserved_stock": 0, "available_stock": 25,
            "incoming_stock": 0, "reorder_level": 200,
            "safety_stock": 80, "lead_time_days": 7,
            "reorder_qty": 500, "is_active": True,
        }),
        FakeRecord({
            "sku_id": "SKU-003", "product_name": "Bearings",
            "category": "Components", "unit_of_measure": "Pack",
            "base_price_inr": 8000, "stock_on_hand": 5,
            "reserved_stock": 0, "available_stock": 5,
            "incoming_stock": 0, "reorder_level": 120,
            "safety_stock": 50, "lead_time_days": 10,
            "reorder_qty": 250, "is_active": True,
        }),
    ]

    client = TestClient(build_app(db))
    response = client.get(
        "/api/inventory/stock-summary",
        headers=_auth_header("admin"),
    )

    assert response.status_code == 200
    data = response.json()
    items = {i["sku_id"]: i for i in data["items"]}

    # SKU-001: available=90 > reorder_level=80 > safety_stock=30 → OK
    assert items["SKU-001"]["reorder_status"] == "OK"

    # SKU-002: available=25 <= safety_stock=80 → URGENT
    assert items["SKU-002"]["reorder_status"] == "URGENT"

    # SKU-003: available=5 <= safety_stock=50 → URGENT
    assert items["SKU-003"]["reorder_status"] == "URGENT"

    summary = data["summary"]
    assert summary["total_skus"] == 3
    assert summary["urgent_count"] == 2
    assert summary["ok_count"] == 1


# ── No bare stock mutations in API code ──────────────────────────────────────

def test_inventory_api_has_no_bare_stock_mutation():
    """
    Guard: api/inventory.py must not contain raw UPDATE products SET
    stock_on_hand/reserved_stock/incoming_stock strings.
    All stock mutations must go through inventory_service.py.
    """
    api_path = os.path.join(
        os.path.dirname(__file__), "..", "api", "inventory.py"
    )
    with open(api_path) as f:
        source = f.read()

    banned_patterns = [
        "UPDATE products SET stock_on_hand",
        "UPDATE products SET reserved_stock",
        "UPDATE products SET incoming_stock",
    ]
    for pattern in banned_patterns:
        assert pattern not in source, (
            f"api/inventory.py contains a direct bare stock mutation: '{pattern}'. "
            "All stock mutations must go through inventory_service.py."
        )


# ── Forecast/dashboard endpoint guards ───────────────────────────────────────

def test_forecast_refresh_requires_admin_or_controller():
    db = UnifiedFakeDB(_staff("dispute_manager"))
    client = TestClient(build_app(db))

    response = client.post(
        "/api/inventory/forecast/refresh",
        headers=_auth_header("dispute_manager"),
        json={"days": 30},
    )

    assert response.status_code == 403


def test_forecast_refresh_calls_service_for_admin():
    db = UnifiedFakeDB(_staff("admin"))
    client = TestClient(build_app(db))

    with patch(
        "api.inventory.generate_forecast_snapshot",
        new=AsyncMock(return_value={
            "sku_id": "SKU-001",
            "days": 7,
            "model_version": "placeholder_mock",
            "total_demand": 10,
            "generated_count": 7,
            "forecast": [],
        }),
    ) as mock_generate:
        response = client.post(
            "/api/inventory/forecast/refresh",
            headers=_auth_header("admin"),
            json={"days": 7, "sku_id": "SKU-001"},
        )

    assert response.status_code == 200
    assert response.json()["generated_count"] == 7
    mock_generate.assert_awaited_once()


def test_dashboard_summary_requires_auth():
    db = UnifiedFakeDB(_staff("admin"))
    client = TestClient(build_app(db))

    response = client.get("/api/inventory/dashboard-summary")

    assert response.status_code == 401


def test_incoming_requires_auth():
    db = UnifiedFakeDB(_staff("admin"))
    client = TestClient(build_app(db))

    response = client.get("/api/inventory/incoming")

    assert response.status_code == 401


# ── Forecast endpoint auth and role guards ────────────────────────────────────

def test_forecast_for_sku_requires_auth():
    db = UnifiedFakeDB(_staff("admin"))
    client = TestClient(build_app(db))

    response = client.get("/api/inventory/forecast/SKU-001")

    assert response.status_code == 401


def test_forecast_for_sku_calls_service_for_admin():
    db = UnifiedFakeDB(_staff("admin"))
    db._row = FakeRecord({
        "sku_id": "SKU-001",
        "product_name": "Widget",
        "stock_on_hand": 20,
        "reserved_stock": 5,
        "incoming_stock": 0,
        "safety_stock": 10,
        "reorder_level": 15,
        "reorder_qty": 50,
    })
    db._rows = [
        FakeRecord({
            "forecast_date": "2026-01-01",
            "predicted_daily_demand": 5,
            "predicted_demand_lower": 3,
            "predicted_demand_upper": 7,
            "model_version": "test",
            "generated_at": "2026-06-01T00:00:00+00:00",
        }),
    ]

    mock_result = {
        "sku_id": "SKU-001",
        "days": 7,
        "forecast": [],
        "stock_position": {"sku_id": "SKU-001", "product_name": "Widget"},
        "projected_demand": 35,
        "projected_30d_demand": 35,
        "average_daily_demand": 5,
        "available_stock": 15,
        "days_until_stockout": 3.0,
        "depletion_date": "2026-01-04",
        "recommended_reorder_qty": 30,
        "reorder_needed": True,
        "model_version": "test",
        "snapshot_refreshed": False,
        "snapshot_row_count": 7,
    }

    with patch(
        "api.inventory.get_inventory_forecast",
        new=AsyncMock(return_value=mock_result),
    ) as mock_forecast:
        client = TestClient(build_app(db))
        response = client.get(
            "/api/inventory/forecast/SKU-001?days=7",
            headers=_auth_header("admin"),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["sku_id"] == "SKU-001"
    assert data["projected_demand"] == 35
    mock_forecast.assert_awaited_once()


def test_forecast_for_sku_allows_controller():
    db = UnifiedFakeDB(_staff("controller"))
    db._row = FakeRecord({
        "sku_id": "SKU-001",
        "product_name": "Widget",
        "stock_on_hand": 20,
        "reserved_stock": 5,
        "incoming_stock": 0,
        "safety_stock": 10,
        "reorder_level": 15,
        "reorder_qty": 50,
    })

    mock_result = {
        "sku_id": "SKU-001", "days": 30, "forecast": [],
        "stock_position": {}, "projected_demand": 100,
        "projected_30d_demand": 100, "average_daily_demand": 3.33,
        "available_stock": 15, "days_until_stockout": 4.5,
        "depletion_date": None, "recommended_reorder_qty": 95,
        "reorder_needed": True, "model_version": "mock",
        "snapshot_refreshed": False, "snapshot_row_count": 30,
    }

    with patch(
        "api.inventory.get_inventory_forecast",
        new=AsyncMock(return_value=mock_result),
    ):
        client = TestClient(build_app(db))
        response = client.get(
            "/api/inventory/forecast/SKU-001",
            headers=_auth_header("controller"),
        )

    assert response.status_code == 200


def test_forecast_for_sku_rejects_unauthorized_role():
    db = UnifiedFakeDB(_staff("collections_analyst"))
    client = TestClient(build_app(db))
    response = client.get(
        "/api/inventory/forecast/SKU-001",
        headers=_auth_header("collections_analyst"),
    )
    assert response.status_code == 403


# ── Dashboard summary: non-overlapping counts ─────────────────────────────────

def test_dashboard_summary_non_overlapping_counts():
    db = UnifiedFakeDB(_staff("admin"))
    db._rows = [
        FakeRecord({
            "sku_id": "SKU-URG", "product_name": "Urgent",
            "stock_on_hand": 5, "reserved_stock": 0, "available_stock": 5,
            "incoming_stock": 0, "reorder_level": 50, "safety_stock": 10,
        }),
        FakeRecord({
            "sku_id": "SKU-REO", "product_name": "Reorder",
            "stock_on_hand": 30, "reserved_stock": 0, "available_stock": 30,
            "incoming_stock": 0, "reorder_level": 50, "safety_stock": 10,
        }),
        FakeRecord({
            "sku_id": "SKU-OK1", "product_name": "OK1",
            "stock_on_hand": 80, "reserved_stock": 0, "available_stock": 80,
            "incoming_stock": 0, "reorder_level": 50, "safety_stock": 10,
        }),
        FakeRecord({
            "sku_id": "SKU-OK2", "product_name": "OK2",
            "stock_on_hand": 200, "reserved_stock": 10, "available_stock": 190,
            "incoming_stock": 50, "reorder_level": 50, "safety_stock": 10,
        }),
    ]
    db._fetchval_return = 0

    client = TestClient(build_app(db))
    response = client.get(
        "/api/inventory/dashboard-summary",
        headers=_auth_header("admin"),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["urgent_count"] == 1
    assert data["reorder_count"] == 1
    assert data["ok_count"] == 2
    assert data["total_skus"] == 4
    assert data["urgent_count"] + data["reorder_count"] + data["ok_count"] == data["total_skus"]


def test_dashboard_summary_returns_ok_count():
    db = UnifiedFakeDB(_staff("admin"))
    db._rows = [
        FakeRecord({
            "sku_id": "SKU-001", "product_name": "OK Item",
            "stock_on_hand": 500, "reserved_stock": 10, "available_stock": 490,
            "incoming_stock": 0, "reorder_level": 100, "safety_stock": 50,
        }),
    ]
    db._fetchval_return = 0

    client = TestClient(build_app(db))
    response = client.get(
        "/api/inventory/dashboard-summary",
        headers=_auth_header("admin"),
    )

    assert response.status_code == 200
    data = response.json()
    assert "ok_count" in data
    assert data["ok_count"] == 1
    assert data["urgent_count"] == 0
    assert data["reorder_count"] == 0


# ── Incoming endpoint still requires auth ──────────────────────────────────────

def test_incoming_returns_200_for_admin():
    db = UnifiedFakeDB(_staff("admin"))
    db._rows = []

    client = TestClient(build_app(db))
    response = client.get(
        "/api/inventory/incoming",
        headers=_auth_header("admin"),
    )

    assert response.status_code == 200
