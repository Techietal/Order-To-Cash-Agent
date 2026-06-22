import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import customer_portal, orders
from api import staff_deps
from config import settings
from database.postgres import get_db as postgres_get_db
from policy.policy_engine import PolicyAction
from services.inventory_service import FULLY_RESERVED, PARTIALLY_RESERVED, FULL_BACKORDER


class FakeRecord(dict):
    pass


class FakeDB:
    def __init__(self):
        self.executed = []
        self.executemany_calls = []
        self.fetchrow_overrides = []
        self.fetchval_return = 0
        self.order_exists = True
        self.order_status = "approved"
        self.active_reservation_exists = True
        self.reservation_row = None

    def push_fetchrow(self, row):
        self.fetchrow_overrides.append(row)

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, query, *args):
        if "staff_users" in query:
            return FakeRecord({
                "username": args[0],
                "display_name": "Test Staff",
                "role": "admin" if args[0] == "admin_user" else "controller",
                "is_active": True,
            })
        if "SELECT order_id, status FROM orders" in query:
            if not self.order_exists:
                return None
            return FakeRecord({"order_id": args[0], "status": self.order_status})
        if "SELECT * FROM orders WHERE order_id = $1" in query and "customer_id" not in query:
            if not self.order_exists:
                return None
            return FakeRecord({
                "order_id": args[0],
                "customer_id": "CUST-001",
                "sku_id": "SKU-001",
                "quantity": 5,
                "status": self.order_status,
            })
        if "FROM inventory_reservations" in query and "ORDER BY reserved_at" in query:
            return self.reservation_row
        if "FROM inventory_reservations" in query and "status = 'active'" in query:
            if self.active_reservation_exists:
                return FakeRecord({"reservation_id": "RES-001"})
            return None
        if "customers WHERE customer_id" in query:
            return FakeRecord({
                "customer_id": args[0],
                "company_name": "Acme Manufacturing",
                "contact_name": "Asha",
                "email": "buyer@example.com",
                "credit_limit_inr": 1000000,
                "open_ar_balance_inr": 0,
                "avg_dso_days": 30,
                "missed_payments_12m": 0,
                "account_age_months": 24,
                "credit_tier": "A",
                "portal_active": True,
                "shipping_address": "Pune",
            })
        if "customers WHERE LOWER(email)" in query:
            return FakeRecord({"customer_id": "CUST-001"})
        if "FROM customers WHERE customer_id = $1" in query:
            return FakeRecord({
                "customer_id": args[0],
                "company_name": "Acme Manufacturing",
                "contact_name": "Asha",
                "email": "buyer@example.com",
                "credit_limit_inr": 1000000,
                "open_ar_balance_inr": 0,
                "avg_dso_days": 30,
                "missed_payments_12m": 0,
                "account_age_months": 24,
                "credit_tier": "A",
            })
        if "FROM products" in query and "sku_id" in query:
            row = {
                "sku_id": "SKU-001",
                "product_name": "Widget",
                "base_price_inr": 1000,
                "gst_rate_pct": 18,
                "is_active": True,
            }
            if "unit_price_inr" in query:
                row["unit_price_inr"] = 1000
            return FakeRecord(row)
        if self.fetchrow_overrides:
            return self.fetchrow_overrides.pop(0)
        return None

    async def fetch(self, query, *args):
        if "product_stock_summary" in query:
            return [FakeRecord({
                "sku_id": "SKU-001",
                "product_name": "Widget",
                "base_price_inr": 1000,
                "unit_of_measure": "EA",
                "category": "Parts",
                "available_stock": 42,
            })]
        return []

    async def fetchval(self, query, *args):
        return self.fetchval_return

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "UPDATE 1" if query.strip().upper().startswith("UPDATE") else "OK"

    async def executemany(self, query, args):
        self.executemany_calls.append((query, args))
        return "OK"


def build_app(db):
    app = FastAPI()
    app.include_router(orders.router, prefix="/api/orders")
    app.include_router(customer_portal.router, prefix="/api/customer-portal")

    async def override_db():
        return db

    app.dependency_overrides[postgres_get_db] = override_db
    return app


def staff_headers(role="admin"):
    token = jwt.encode(
        {"sub": f"{role}_user", "role": role},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def customer_headers():
    token = customer_portal.create_customer_token("CUST-001", "buyer@example.com", "Acme")
    return {"Authorization": f"Bearer {token}"}


def full_reservation():
    return {
        "verdict": FULLY_RESERVED,
        "quantity_reserved": 5,
        "quantity_backordered": 0,
        "reservation_id": "RES-001",
        "expected_availability_date": None,
        "eta_reliability": "not_needed",
        "warning": None,
    }


def partial_reservation():
    return {
        "verdict": PARTIALLY_RESERVED,
        "quantity_reserved": 2,
        "quantity_backordered": 3,
        "reservation_id": "RES-002",
        "expected_availability_date": "2026-07-01T00:00:00+00:00",
        "eta_reliability": "estimated_lead_time",
        "warning": None,
    }


def backorder_reservation(reliability="estimated_lead_time"):
    return {
        "verdict": FULL_BACKORDER,
        "quantity_reserved": 0,
        "quantity_backordered": 5,
        "reservation_id": "RES-003",
        "expected_availability_date": None,
        "eta_reliability": reliability,
        "warning": None,
    }


def allow_policy():
    return {"action": PolicyAction.PROCEED, "flags": []}


def hitl_policy():
    return {"action": PolicyAction.REQUIRE_HITL, "flags": ["RULE-008_FULL_BACKORDER"], "hitl_reason": "BACKORDER_NO_ETA"}


def patch_order_models():
    return patch.multiple(
        orders,
        score_order=lambda ctx: {"anomaly_score": 0.1, "anomaly_flag": False, "interpretation": "normal"},
        predict_fraud=lambda ctx: {"fraud_probability": 0.01, "fraud_verdict": "LEGIT"},
    )


def test_internal_post_orders_fully_reserves_stock():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch_order_models(), \
         patch.object(orders.policy_engine, "evaluate", new=AsyncMock(side_effect=[allow_policy(), allow_policy()])), \
         patch.object(orders, "check_and_reserve", new=AsyncMock(return_value=full_reservation())) as reserve:
        response = client.post(
            "/api/orders",
            headers=staff_headers(),
            json={"customer_id": "CUST-001", "sku_id": "SKU-001", "quantity": 5, "unit_price_inr": 1000},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["inventory_verdict"] == FULLY_RESERVED
    reserve.assert_awaited_once()


def test_internal_post_orders_partial_reservation_sets_partial_status():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch_order_models(), \
         patch.object(orders.policy_engine, "evaluate", new=AsyncMock(side_effect=[allow_policy(), allow_policy()])), \
         patch.object(orders, "check_and_reserve", new=AsyncMock(return_value=partial_reservation())):
        response = client.post(
            "/api/orders",
            headers=staff_headers(),
            json={"customer_id": "CUST-001", "sku_id": "SKU-001", "quantity": 5, "unit_price_inr": 1000},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "partially_reserved"
    assert response.json()["quantity_backordered"] == 3


def test_email_ingest_path_reserves_stock():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch.object(orders, "extract_order_entities_with_llm_backup", return_value={
            "item_code": {"value": "SKU-001"},
            "quantity": {"value": "5"},
            "_ner_confidence": "HIGH",
            "_groq_corrections": [],
        }), \
         patch_order_models(), \
         patch.object(orders, "predict_credit_risk", return_value={"credit_risk_class": "LOW", "pd_score": 0.01}), \
         patch.object(orders.policy_engine, "evaluate", new=AsyncMock(side_effect=[allow_policy(), allow_policy()])), \
         patch.object(orders, "check_and_reserve", new=AsyncMock(return_value=full_reservation())) as reserve:
        response = client.post(
            "/api/orders/ingest-email",
            headers=staff_headers(),
            json={"email_text": "Order 5 SKU-001", "email_from": "buyer@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["inventory_verdict"] == FULLY_RESERVED
    reserve.assert_awaited_once()


def test_customer_portal_order_reserves_stock():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch("ml.isolation_forest.score_order", return_value={"anomaly_score": 0.1, "anomaly_flag": False, "interpretation": "normal"}), \
         patch("ml.model_placeholders.predict_fraud", return_value={"fraud_probability": 0.01, "fraud_verdict": "LEGIT"}), \
         patch("ml.model_placeholders.predict_credit_risk", return_value={"credit_risk_class": "LOW", "pd_score": 0.01, "model": "test"}), \
         patch.object(orders.policy_engine, "evaluate", new=AsyncMock(side_effect=[allow_policy(), allow_policy()])), \
         patch.object(orders, "check_and_reserve", new=AsyncMock(return_value=full_reservation())) as reserve:
        response = client.post(
            "/api/customer-portal/orders",
            headers=customer_headers(),
            json={"sku_id": "SKU-001", "quantity": 5},
        )

    assert response.status_code == 200
    assert response.json()["inventory_verdict"] == FULLY_RESERVED
    reserve.assert_awaited_once()


def test_repeat_order_reserves_stock():
    db = FakeDB()
    db.push_fetchrow(FakeRecord({
        "order_id": "ORD-OLD",
        "customer_id": "CUST-001",
        "sku_id": "SKU-001",
        "quantity": 5,
        "delivery_address": "Pune",
        "po_reference": "PO-1",
    }))
    client = TestClient(build_app(db))
    with patch.object(orders.policy_engine, "evaluate", new=AsyncMock(return_value=allow_policy())), \
         patch.object(orders, "check_and_reserve", new=AsyncMock(return_value=full_reservation())) as reserve:
        response = client.post(
            "/api/customer-portal/orders/ORD-OLD/repeat",
            headers=customer_headers(),
            json={"quantity": 5},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["inventory_verdict"] == FULLY_RESERVED
    reserve.assert_awaited_once()


def test_repeat_order_full_backorder_does_not_create_invoice():
    db = FakeDB()
    db.push_fetchrow(FakeRecord({
        "order_id": "ORD-OLD",
        "customer_id": "CUST-001",
        "sku_id": "SKU-001",
        "quantity": 5,
        "delivery_address": "Pune",
        "po_reference": "PO-1",
    }))
    client = TestClient(build_app(db))
    with patch.object(orders.policy_engine, "evaluate", new=AsyncMock(return_value=allow_policy())), \
         patch.object(orders, "check_and_reserve", new=AsyncMock(return_value=backorder_reservation())):
        response = client.post(
            "/api/customer-portal/orders/ORD-OLD/repeat",
            headers=customer_headers(),
            json={"quantity": 5},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "backordered"
    assert not any("INSERT INTO invoices" in sql for sql, _ in db.executed)


def test_full_backorder_does_not_create_invoice():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch_order_models(), \
         patch.object(orders.policy_engine, "evaluate", new=AsyncMock(side_effect=[allow_policy(), allow_policy()])), \
         patch.object(orders, "check_and_reserve", new=AsyncMock(return_value=backorder_reservation())):
        response = client.post(
            "/api/orders",
            headers=staff_headers(),
            json={"customer_id": "CUST-001", "sku_id": "SKU-001", "quantity": 5, "unit_price_inr": 1000},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "backordered"
    assert not any("INSERT INTO invoices" in sql for sql, _ in db.executed)


def test_unknown_eta_routes_to_hitl():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch_order_models(), \
         patch.object(orders.policy_engine, "evaluate", new=AsyncMock(side_effect=[allow_policy(), hitl_policy()])), \
         patch.object(orders, "check_and_reserve", new=AsyncMock(return_value=backorder_reservation("unknown"))):
        response = client.post(
            "/api/orders",
            headers=staff_headers(),
            json={"customer_id": "CUST-001", "sku_id": "SKU-001", "quantity": 5, "unit_price_inr": 1000},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "hitl_required"
    assert response.json()["hitl_required"] is True
    assert any("INVENTORY_HITL" in str(args) for _, args in db.executed)


def test_fulfill_endpoint_calls_inventory_service():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch.object(orders, "fulfill_reservation", new=AsyncMock(return_value={
        "fulfilled": True,
        "quantity_fulfilled": 5,
        "reservation_id": "RES-001",
        "warning": None,
    })) as fulfill:
        response = client.post(
            "/api/orders/ORD-001/fulfill",
            headers=staff_headers("controller"),
            json={"quantity_to_fulfill": 5, "idempotency_key": "fulfill-1"},
        )

    assert response.status_code == 200
    fulfill.assert_awaited_once()


def test_patch_status_fulfilled_returns_400():
    db = FakeDB()
    client = TestClient(build_app(db))

    response = client.patch(
        "/api/orders/ORD-001/status",
        headers=staff_headers("controller"),
        params={"status": "fulfilled"},
    )

    assert response.status_code == 400
    assert "/api/orders/ORD-001/fulfill" in response.json()["detail"]


def test_patch_status_cancelled_returns_400():
    db = FakeDB()
    client = TestClient(build_app(db))

    response = client.patch(
        "/api/orders/ORD-001/status",
        headers=staff_headers("controller"),
        params={"status": "cancelled"},
    )

    assert response.status_code == 400
    assert "/api/orders/ORD-001/cancel" in response.json()["detail"]


def test_get_order_includes_reservation_object():
    db = FakeDB()
    db.reservation_row = FakeRecord({
        "reservation_id": "RES-001",
        "sku_id": "SKU-001",
        "quantity_requested": 5,
        "quantity_reserved": 2,
        "quantity_backordered": 3,
        "status": "active",
        "expected_availability_date": None,
        "reserved_at": None,
        "released_at": None,
        "fulfilled_at": None,
    })
    client = TestClient(build_app(db))

    response = client.get("/api/orders/ORD-001", headers=staff_headers("controller"))

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == "ORD-001"
    assert body["reservation"]["reservation_id"] == "RES-001"
    assert body["reservation"]["quantity_backordered"] == 3


def test_cancel_endpoint_calls_inventory_service():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch.object(orders, "release_reservation", new=AsyncMock(return_value={
        "released": True,
        "quantity_released": 5,
        "reservation_id": "RES-001",
        "warning": None,
    })) as release:
        response = client.post("/api/orders/ORD-001/cancel", headers=staff_headers("controller"))

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    release.assert_awaited_once()


def test_cancel_missing_order_does_not_call_release_reservation():
    db = FakeDB()
    db.order_exists = False
    client = TestClient(build_app(db))
    with patch.object(orders, "release_reservation", new=AsyncMock()) as release:
        response = client.post("/api/orders/ORD-MISSING/cancel", headers=staff_headers("controller"))

    assert response.status_code == 404
    release.assert_not_awaited()


def test_portal_products_include_available_stock():
    db = FakeDB()
    client = TestClient(build_app(db))
    response = client.get("/api/customer-portal/products", headers=customer_headers())

    assert response.status_code == 200
    assert response.json()["products"][0]["available_stock"] == 42


def test_no_direct_stock_update_exists_in_order_hitl_paths():
    root = Path(__file__).resolve().parents[1]
    for relative in ["api/orders.py", "api/customer_portal.py", "api/hitl.py"]:
        text = (root / relative).read_text(encoding="utf-8")
        assert "UPDATE products SET stock_on_hand" not in text
        assert "UPDATE products SET reserved_stock" not in text
        assert "UPDATE products SET incoming_stock" not in text
