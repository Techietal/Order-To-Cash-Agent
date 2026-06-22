import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import products
from config import settings
from database.postgres import get_db as postgres_get_db


class FakeRecord(dict):
    pass


class FakeDB:
    def __init__(self, role="admin"):
        self.role = role
        self.rows = [
            FakeRecord({"sku_id": "SKU-U", "product_name": "Urgent", "category": "A", "unit_of_measure": "EA", "base_price_inr": 10, "stock_on_hand": 5, "reserved_stock": 0, "available_stock": 5, "incoming_stock": 0, "reorder_level": 20, "safety_stock": 10, "lead_time_days": 7, "reorder_qty": 50, "is_active": True}),
            FakeRecord({"sku_id": "SKU-R", "product_name": "Reorder", "category": "A", "unit_of_measure": "EA", "base_price_inr": 10, "stock_on_hand": 15, "reserved_stock": 0, "available_stock": 15, "incoming_stock": 0, "reorder_level": 20, "safety_stock": 10, "lead_time_days": 7, "reorder_qty": 50, "is_active": True}),
            FakeRecord({"sku_id": "SKU-O", "product_name": "Ok", "category": "B", "unit_of_measure": "EA", "base_price_inr": 10, "stock_on_hand": 25, "reserved_stock": 0, "available_stock": 25, "incoming_stock": 0, "reorder_level": 20, "safety_stock": 10, "lead_time_days": 7, "reorder_qty": 50, "is_active": True}),
        ]

    def _filter_rows(self, query, args):
        q = query.lower()
        rows = list(self.rows)
        if args:
            for i, arg in enumerate(args):
                if isinstance(arg, str) and arg in ("URGENT", "REORDER", "OK"):
                    avail_key = "available_stock"
                    safety_key = "safety_stock"
                    reorder_key = "reorder_level"
                    if arg == "URGENT":
                        rows = [r for r in rows if (r.get(avail_key) or 0) <= (r.get(safety_key) or 0)]
                    elif arg == "REORDER":
                        rows = [r for r in rows if (r.get(avail_key) or 0) > (r.get(safety_key) or 0) and (r.get(avail_key) or 0) <= (r.get(reorder_key) or 0)]
                    elif arg == "OK":
                        rows = [r for r in rows if (r.get(avail_key) or 0) > (r.get(reorder_key) or 0)]
        return rows

    async def fetchrow(self, query, *args):
        if "staff_users" in query:
            return {"username": args[0], "display_name": "Test", "role": self.role, "is_active": True}
        if "product_stock_summary" in query:
            return self.rows[0]
        return None

    async def fetch(self, query, *args):
        if "inventory_transactions" in query or "purchase_orders" in query:
            return []
        return self._filter_rows(query, args)

    async def fetchval(self, query, *args):
        filtered = self._filter_rows(query, args)
        return len(filtered)

    async def execute(self, query, *args):
        return "OK"


def build_app(db):
    app = FastAPI()
    app.include_router(products.router, prefix="/api/products")

    async def override_db():
        return db

    app.dependency_overrides[postgres_get_db] = override_db
    return app


def headers(role="admin"):
    token = jwt.encode({"sub": f"{role}_user", "role": role}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return {"Authorization": f"Bearer {token}"}


# ── Auth and role tests ──────────────────────────────────────────────────────

def test_products_list_requires_auth():
    response = TestClient(build_app(FakeDB())).get("/api/products")
    assert response.status_code == 401


def test_products_detail_requires_auth():
    response = TestClient(build_app(FakeDB())).get("/api/products/SKU-U")
    assert response.status_code == 401


def test_products_list_allows_admin_and_controller():
    for role in ["admin", "controller"]:
        response = TestClient(build_app(FakeDB(role))).get("/api/products", headers=headers(role))
        assert response.status_code == 200


def test_products_list_rejects_unrelated_roles():
    response = TestClient(build_app(FakeDB("dispute_manager"))).get("/api/products", headers=headers("dispute_manager"))
    assert response.status_code == 403


# ── Reorder status filtering ──────────────────────────────────────────────────

def test_reorder_status_calculation_is_non_overlapping():
    response = TestClient(build_app(FakeDB())).get("/api/products", headers=headers("admin"))
    items = {p["sku_id"]: p["reorder_status"] for p in response.json()["products"]}
    assert items == {"SKU-U": "URGENT", "SKU-R": "REORDER", "SKU-O": "OK"}


def test_reorder_status_urgent_filter():
    response = TestClient(build_app(FakeDB())).get("/api/products?reorder_status=URGENT", headers=headers("admin"))
    assert response.status_code == 200
    data = response.json()
    products = data["products"]
    assert len(products) == 1
    assert products[0]["reorder_status"] == "URGENT"
    assert products[0]["sku_id"] == "SKU-U"
    assert data["total"] == 1


def test_reorder_status_reorder_filter():
    response = TestClient(build_app(FakeDB())).get("/api/products?reorder_status=REORDER", headers=headers("admin"))
    assert response.status_code == 200
    data = response.json()
    products = data["products"]
    assert len(products) == 1
    assert products[0]["reorder_status"] == "REORDER"
    assert products[0]["sku_id"] == "SKU-R"
    assert data["total"] == 1


def test_reorder_status_ok_filter():
    response = TestClient(build_app(FakeDB())).get("/api/products?reorder_status=OK", headers=headers("admin"))
    assert response.status_code == 200
    data = response.json()
    products = data["products"]
    assert len(products) == 1
    assert products[0]["reorder_status"] == "OK"
    assert products[0]["sku_id"] == "SKU-O"
    assert data["total"] == 1


def test_total_reflects_filtered_count():
    db = FakeDB()
    client = TestClient(build_app(db))

    all_resp = client.get("/api/products", headers=headers("admin"))
    urgent_resp = client.get("/api/products?reorder_status=URGENT", headers=headers("admin"))

    assert all_resp.json()["total"] == 3
    assert urgent_resp.json()["total"] == 1


def test_pagination_with_reorder_status():
    db = FakeDB()
    client = TestClient(build_app(db))

    resp = client.get("/api/products?reorder_status=URGENT&limit=10&offset=0", headers=headers("admin"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["limit"] == 10
    assert data["offset"] == 0


def test_invalid_reorder_status_returns_400():
    response = TestClient(build_app(FakeDB())).get("/api/products?reorder_status=INVALID", headers=headers("admin"))
    assert response.status_code == 400
    assert "INVALID" in response.json()["detail"]


def test_reorder_status_case_sensitive_invalid():
    response = TestClient(build_app(FakeDB())).get("/api/products?reorder_status=urgent", headers=headers("admin"))
    assert response.status_code == 400


# ── No direct stock mutation ─────────────────────────────────────────────────

def test_products_api_has_no_direct_stock_mutation():
    source = Path(__file__).resolve().parents[1] / "api" / "products.py"
    text = source.read_text(encoding="utf-8")
    assert "UPDATE products SET stock_on_hand" not in text
    assert "UPDATE products SET reserved_stock" not in text
    assert "UPDATE products SET incoming_stock" not in text