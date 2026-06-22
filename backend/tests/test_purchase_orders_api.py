import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import purchase_orders
from config import settings
from database.postgres import get_db as postgres_get_db


class FakeRecord(dict):
    pass


class FakeDB:
    def __init__(self, staff_role="admin"):
        self.staff_role = staff_role
        self.executed = []
        self.po_id = "PO-TEST"
        self.items = []
        self.total = 3

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, query, *args):
        if "staff_users" in query:
            return FakeRecord({
                "username": args[0],
                "display_name": "Test Staff",
                "role": self.staff_role,
                "is_active": True,
            })
        if "FROM products" in query:
            return FakeRecord({"sku_id": args[0], "is_active": True})
        if "FROM purchase_orders" in query:
            return FakeRecord({
                "po_id": args[0],
                "supplier_id": "SUP-001",
                "status": "draft",
                "expected_arrival_date": None,
                "created_by": "admin_user",
            })
        return None

    async def fetch(self, query, *args):
        if "purchase_order_items" in query:
            return self.items
        if "purchase_orders" in query:
            return [FakeRecord({
                "po_id": self.po_id,
                "supplier_id": "SUP-001",
                "status": "draft",
                "expected_arrival_date": None,
                "created_by": "admin_user",
            })]
        return []

    async def fetchval(self, query, *args):
        return self.total

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if "INSERT INTO purchase_orders" in query:
            self.po_id = args[0]
        if "INSERT INTO purchase_order_items" in query:
            self.items.append(FakeRecord({
                "po_item_id": args[0],
                "po_id": args[1],
                "sku_id": args[2],
                "quantity_ordered": args[3],
                "quantity_received": 0,
                "unit_cost_inr": args[4],
                "line_status": "open",
            }))
        return "OK"


def build_app(db):
    app = FastAPI()
    app.include_router(purchase_orders.router, prefix="/api/purchase-orders")

    async def override_db():
        return db

    app.dependency_overrides[postgres_get_db] = override_db
    return app


def auth_headers(role="admin"):
    token = jwt.encode(
        {"sub": f"{role}_user", "role": role},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def test_create_po_does_not_mutate_stock():
    db = FakeDB()
    client = TestClient(build_app(db))

    response = client.post(
        "/api/purchase-orders",
        headers=auth_headers("admin"),
        json={
            "supplier_id": "SUP-001",
            "items": [{"sku_id": "SKU-001", "quantity_ordered": 25, "unit_cost_inr": 100}],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert not any("UPDATE products" in sql for sql, _ in db.executed)


def test_confirm_endpoint_calls_inventory_service():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch.object(purchase_orders, "confirm_purchase_order", new=AsyncMock(return_value={
        "po_id": "PO-001",
        "status": "confirmed",
        "movements": [{"sku_id": "SKU-001", "quantity_incoming": 10}],
    })) as confirm:
        response = client.post("/api/purchase-orders/PO-001/confirm", headers=auth_headers("controller"))

    assert response.status_code == 200
    confirm.assert_awaited_once()


def test_receive_endpoint_calls_inventory_service():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch.object(purchase_orders, "receive_purchase_order", new=AsyncMock(return_value={
        "po_id": "PO-001",
        "status": "received",
        "movements": [],
        "backorders_cleared": [],
        "idempotent": False,
    })) as receive:
        response = client.post(
            "/api/purchase-orders/PO-001/receive",
            headers=auth_headers("admin"),
            json={"items": [{"sku_id": "SKU-001", "quantity_received": 5}], "idempotency_key": "recv-1"},
        )

    assert response.status_code == 200
    receive.assert_awaited_once()


def test_list_endpoint_returns_actual_total_not_page_length():
    db = FakeDB()
    db.total = 25
    client = TestClient(build_app(db))

    response = client.get("/api/purchase-orders?limit=1&offset=0", headers=auth_headers("admin"))

    assert response.status_code == 200
    assert response.json()["total"] == 25
    assert len(response.json()["purchase_orders"]) == 1


def test_receive_po_serializes_pydantic_v1_and_v2_styles():
    class V1Line:
        def dict(self):
            return {"sku_id": "SKU-V1", "quantity_received": 1}

    class V2Line:
        def model_dump(self):
            return {"sku_id": "SKU-V2", "quantity_received": 2}

        def dict(self):
            raise AssertionError("model_dump should be preferred when available")

    assert purchase_orders._pydantic_to_dict(V1Line()) == {"sku_id": "SKU-V1", "quantity_received": 1}
    assert purchase_orders._pydantic_to_dict(V2Line()) == {"sku_id": "SKU-V2", "quantity_received": 2}


def test_purchase_order_endpoints_require_auth():
    db = FakeDB()
    client = TestClient(build_app(db))

    assert client.get("/api/purchase-orders").status_code == 401
    assert client.get("/api/purchase-orders/PO-001").status_code == 401
    assert client.post("/api/purchase-orders", json={"items": []}).status_code == 401
    assert client.post("/api/purchase-orders/PO-001/confirm").status_code == 401
    assert client.post("/api/purchase-orders/PO-001/receive", json={"items": []}).status_code == 401


def test_purchase_order_write_endpoints_require_admin_or_controller():
    db = FakeDB(staff_role="dispute_manager")
    client = TestClient(build_app(db))
    headers = auth_headers("dispute_manager")

    assert client.post("/api/purchase-orders", headers=headers, json={"items": []}).status_code == 403
    assert client.post("/api/purchase-orders/PO-001/confirm", headers=headers).status_code == 403
    assert client.post("/api/purchase-orders/PO-001/receive", headers=headers, json={"items": []}).status_code == 403


def test_no_direct_product_stock_mutation_outside_inventory_service_except_seed():
    root = Path(__file__).resolve().parents[1]
    allowed = {root / "services" / "inventory_service.py", root / "seed_data" / "rich_seed.py"}
    patterns = [
        "UPDATE products SET stock_on_hand",
        "UPDATE products SET reserved_stock",
        "UPDATE products SET incoming_stock",
    ]
    offenders = []
    for path in root.rglob("*.py"):
        if path in allowed or "__pycache__" in path.parts or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            if pattern in text:
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


# ── Regression tests: PO receive idempotency & draft blocking ─────────────

class ReceiveFakeDB:
    """Minimal async fake that supports the receive_purchase_order code path."""

    def __init__(self, po_status="confirmed", idempotency_hit=False):
        self.po_status = po_status
        self.idempotency_hit = idempotency_hit
        self.updated_rows = []
        self.previous_result = {
            "po_id": "PO-1",
            "status": "partially_received",
            "movements": [{"sku_id": "SKU-001", "quantity_received": 5}],
            "backorders_cleared": [],
            "idempotent": False,
        }

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, query, *args):
        q = query.lower()
        if "idempotency_key" in q and self.idempotency_hit:
            return FakeRecord({"result": self.previous_result})
        if "idempotency_key" in q:
            return None
        if "purchase_orders" in q and "for update" in q:
            return FakeRecord({
                "po_id": args[0] if args else "PO-1",
                "status": self.po_status,
            })
        if "purchase_order_items" in q and "for update" in q:
            return FakeRecord({
                "po_item_id": "POI-1",
                "po_id": args[0] if args else "PO-1",
                "sku_id": args[1] if len(args) > 1 else "SKU-001",
                "quantity_ordered": 10,
                "quantity_received": 0,
                "unit_cost_inr": 100,
                "line_status": "open",
            })
        if "products" in q and "for update" in q:
            return FakeRecord({
                "sku_id": "SKU-001",
                "stock_on_hand": 50,
                "incoming_stock": 10,
                "reserved_stock": 0,
            })
        if "quantity_ordered" in q and "po_id" in q:
            return [FakeRecord({"quantity_ordered": 10, "quantity_received": 5})]
        return None

    async def fetch(self, query, *args):
        q = query.lower()
        if "quantity_ordered" in q and "quantity_received" in q:
            return [FakeRecord({"quantity_ordered": 10, "quantity_received": 5})]
        if "inventory_reservations" in q:
            return []
        return []

    async def fetchval(self, query, *args):
        return 0

    async def execute(self, query, *args):
        self.updated_rows.append((query, args))
        return "UPDATE 1"


def test_receive_rejects_draft_po():
    from services.inventory_service import receive_purchase_order
    import asyncio

    db = ReceiveFakeDB(po_status="draft")
    with pytest.raises(ValueError, match="Purchase order must be confirmed before receiving"):
        asyncio.run(
            receive_purchase_order(
                db,
                po_id="PO-DRAFT",
                received_items=[{"sku_id": "SKU-001", "quantity_received": 5}],
                performed_by="admin",
                actor_type="human",
            )
        )


def test_receive_rejects_cancelled_po():
    from services.inventory_service import receive_purchase_order
    import asyncio

    db = ReceiveFakeDB(po_status="cancelled")
    with pytest.raises(ValueError, match="cannot be received"):
        asyncio.run(
            receive_purchase_order(
                db,
                po_id="PO-CANCEL",
                received_items=[{"sku_id": "SKU-001", "quantity_received": 5}],
                performed_by="admin",
                actor_type="human",
            )
        )


def test_receive_confirmed_po_succeeds():
    from services.inventory_service import receive_purchase_order
    import asyncio

    db = ReceiveFakeDB(po_status="confirmed")
    result = asyncio.run(
        receive_purchase_order(
            db,
            po_id="PO-1",
            received_items=[{"sku_id": "SKU-001", "quantity_received": 5}],
            performed_by="admin",
            actor_type="human",
        )
    )
    assert result["status"] == "partially_received"
    assert any("UPDATE products" in sql for sql, _ in db.updated_rows)


def test_receive_idempotency_first_mutates_second_does_not():
    from services.inventory_service import receive_purchase_order
    import asyncio

    db_first = ReceiveFakeDB(po_status="confirmed", idempotency_hit=False)
    first = asyncio.run(
        receive_purchase_order(
            db_first,
            po_id="PO-1",
            received_items=[{"sku_id": "SKU-001", "quantity_received": 5}],
            performed_by="admin",
            actor_type="human",
            idempotency_key="recv-key-1",
        )
    )
    assert first["idempotent"] is False
    first_stock_mutations = [row for row in db_first.updated_rows if "UPDATE products" in row[0]]
    assert len(first_stock_mutations) == 1

    db_second = ReceiveFakeDB(po_status="confirmed", idempotency_hit=True)
    second = asyncio.run(
        receive_purchase_order(
            db_second,
            po_id="PO-1",
            received_items=[{"sku_id": "SKU-001", "quantity_received": 5}],
            performed_by="admin",
            actor_type="human",
            idempotency_key="recv-key-1",
        )
    )
    assert second["idempotent"] is True
    second_stock_mutations = [row for row in db_second.updated_rows if "UPDATE products" in row[0]]
    assert second_stock_mutations == []


def test_receive_endpoint_rejects_draft_via_api():
    db = FakeDB()
    client = TestClient(build_app(db))
    with patch.object(
        purchase_orders, "receive_purchase_order",
        new=AsyncMock(side_effect=ValueError("Purchase order must be confirmed before receiving")),
    ):
        response = client.post(
            "/api/purchase-orders/PO-DRAFT/receive",
            headers=auth_headers("admin"),
            json={"items": [{"sku_id": "SKU-001", "quantity_received": 5}]},
        )
    assert response.status_code == 400
    assert "confirmed" in response.json()["detail"].lower()
