"""
Tests for services/inventory_service.py

All tests use in-memory fake DB objects — no real PostgreSQL connection required.
The FakeDB simulates asyncpg's row interface and transaction context manager.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.inventory_service import (
    check_and_reserve,
    fulfill_reservation,
    release_reservation,
    record_adjustment,
    FULLY_RESERVED,
    PARTIALLY_RESERVED,
    FULL_BACKORDER,
    STOCK_ADJUSTMENT,
    DAMAGED_INVENTORY,
    MANUAL_CORRECTION,
    ORDER_RESERVATION,
    BACKORDER_CREATED,
    FULFILLMENT_DEDUCTION,
    FULFILLMENT_RESERVED_RELEASE,
    ORDER_RELEASE_CANCELLED,
    PURCHASE_ORDER_CONFIRMED,
    PURCHASE_RECEIPT,
    PURCHASE_RECEIPT_INCOMING_RELEASE,
    BACKORDER_FULFILLED,
    confirm_purchase_order,
    receive_purchase_order,
    auto_clear_backorders_for_sku,
)


# ── FakeDB helpers ────────────────────────────────────────────────────────────

class FakeRecord(dict):
    """asyncpg Record substitute — dict that also supports attribute access."""
    def __getitem__(self, key):
        return super().__getitem__(key)


def make_product(
    sku_id="SKU-001",
    stock_on_hand=100,
    reserved_stock=10,
    incoming_stock=0,
    reorder_level=20,
    safety_stock=10,
    lead_time_days=14,
    reorder_qty=50,
    is_active=True,
):
    return FakeRecord({
        "sku_id": sku_id,
        "stock_on_hand": stock_on_hand,
        "reserved_stock": reserved_stock,
        "incoming_stock": incoming_stock,
        "reorder_level": reorder_level,
        "safety_stock": safety_stock,
        "lead_time_days": lead_time_days,
        "reorder_qty": reorder_qty,
        "is_active": is_active,
    })


def make_reservation(**kwargs):
    defaults = dict(
        reservation_id="RES-TESTRES01",
        order_id="ORD-001",
        sku_id="SKU-001",
        quantity_requested=20,
        quantity_reserved=20,
        quantity_backordered=0,
        status="active",
        expected_availability_date=None,
    )
    defaults.update(kwargs)
    return FakeRecord(defaults)


class FakeDB:
    """
    Minimal asyncpg-like fake.

    Stores call history in `executed` for assertion.
    `_fetchrow_seq` is a queue: each call to fetchrow() pops the next item.
    """

    def __init__(self):
        self.executed: list = []          # list of (sql, *params) tuples
        self._fetchrow_seq: list = []     # queue of return values for fetchrow
        self._fetch_seq: list = []        # queue of return values for fetch
        self._fetchval_returns = None

    def _push_fetchrow(self, row):
        """Enqueue the next value fetchrow() will return."""
        self._fetchrow_seq.append(row)

    async def fetchrow(self, sql, *args):
        if self._fetchrow_seq:
            return self._fetchrow_seq.pop(0)
        return None

    async def fetchval(self, sql, *args):
        return self._fetchval_returns

    async def fetch(self, sql, *args):
        if self._fetch_seq:
            return self._fetch_seq.pop(0)
        return []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"

    @asynccontextmanager
    async def transaction(self):
        yield self


# ── check_and_reserve ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_reservation():
    """Enough stock available → FULLY_RESERVED, reserved_stock incremented."""
    db = FakeDB()
    # fetchrow calls in order:
    # 1. SELECT product FOR UPDATE
    # 2. SELECT existing reservation (None → no duplicate)
    # 3. compute_expected_availability_date: po query → None
    # 4. compute_expected_availability_date: lead_time query
    db._push_fetchrow(make_product(stock_on_hand=100, reserved_stock=10))  # product lock
    db._push_fetchrow(None)          # no duplicate reservation
    db._push_fetchrow(None)          # no confirmed PO
    db._push_fetchrow(FakeRecord({"lead_time_days": 14}))  # lead_time fallback

    result = await check_and_reserve(db, "SKU-001", 50, "ORD-TEST-001")

    assert result["verdict"] == FULLY_RESERVED
    assert result["quantity_reserved"] == 50
    assert result["quantity_backordered"] == 0
    assert result["expected_availability_date"] is None
    assert result["eta_reliability"] == "not_needed"
    assert result["reservation_id"].startswith("RES-")

    # Must have updated reserved_stock
    update_calls = [s for s, _ in db.executed if "UPDATE products" in s]
    assert len(update_calls) >= 1

    # Must have inserted ORDER_RESERVATION transaction
    txn_calls = [s for s, _ in db.executed if "inventory_transactions" in s]
    txn_types = [a[2] for s, a in db.executed if "inventory_transactions" in s and len(a) > 2]
    assert ORDER_RESERVATION in txn_types
    assert BACKORDER_CREATED not in txn_types


@pytest.mark.asyncio
async def test_available_stock_clamped_to_zero():
    """Negative raw availability becomes FULL_BACKORDER and returns a warning."""
    db = FakeDB()
    # Degenerate state: reserved_stock > stock_on_hand (possible after a manual adjustment)
    db._push_fetchrow(make_product(stock_on_hand=5, reserved_stock=20))  # product lock
    db._push_fetchrow(None)   # no duplicate reservation
    db._push_fetchrow(None)   # no confirmed PO
    db._push_fetchrow(FakeRecord({"lead_time_days": 7}))

    result = await check_and_reserve(db, "SKU-001", 10, "ORD-CLAMP")

    # available = max(0, 5 - 20) = 0 → full backorder, not negative reservation
    assert result["verdict"] == FULL_BACKORDER
    assert result["quantity_reserved"] == 0
    assert result["quantity_backordered"] == 10
    assert result["warning"] is not None
    assert "stock_on_hand" in result["warning"]
    assert "reserved_stock" in result["warning"]


@pytest.mark.asyncio
async def test_partial_reservation():
    """Partial stock → PARTIALLY_RESERVED, both ORDER_RESERVATION and BACKORDER_CREATED inserted."""
    db = FakeDB()
    # available = 100 - 60 = 40; requesting 70 → reserve 40, backorder 30
    db._push_fetchrow(make_product(stock_on_hand=100, reserved_stock=60))  # product lock
    db._push_fetchrow(None)          # no duplicate reservation
    db._push_fetchrow(None)          # no confirmed PO
    db._push_fetchrow(FakeRecord({"lead_time_days": 7}))

    result = await check_and_reserve(db, "SKU-001", 70, "ORD-TEST-002")

    assert result["verdict"] == PARTIALLY_RESERVED
    assert result["quantity_reserved"] == 40
    assert result["quantity_backordered"] == 30
    assert result["eta_reliability"] == "estimated_lead_time"

    txn_types = [a[2] for s, a in db.executed if "inventory_transactions" in s and len(a) > 2]
    assert ORDER_RESERVATION in txn_types
    assert BACKORDER_CREATED in txn_types

    # BACKORDER_CREATED must not imply a products stock-column mutation.
    backorder_rows = [a for s, a in db.executed if "inventory_transactions" in s and len(a) > 2 and a[2] == BACKORDER_CREATED]
    assert len(backorder_rows) == 1
    quantity_delta = backorder_rows[0][3]
    field_affected = backorder_rows[0][4]   # 5th positional param
    assert quantity_delta == 0
    assert field_affected == "backorder"


@pytest.mark.asyncio
async def test_full_backorder():
    """Zero available stock → FULL_BACKORDER, only BACKORDER_CREATED inserted."""
    db = FakeDB()
    # available = 50 - 50 = 0
    db._push_fetchrow(make_product(stock_on_hand=50, reserved_stock=50))
    db._push_fetchrow(None)   # no duplicate reservation
    db._push_fetchrow(None)   # no confirmed PO
    db._push_fetchrow(FakeRecord({"lead_time_days": 21}))

    result = await check_and_reserve(db, "SKU-001", 10, "ORD-TEST-003")

    assert result["verdict"] == FULL_BACKORDER
    assert result["quantity_reserved"] == 0
    assert result["quantity_backordered"] == 10

    txn_types = [a[2] for s, a in db.executed if "inventory_transactions" in s and len(a) > 2]
    assert BACKORDER_CREATED in txn_types
    assert ORDER_RESERVATION not in txn_types

    # reserved_stock must NOT be mutated (no UPDATE products when reserve qty == 0)
    update_calls = [s for s, _ in db.executed if "UPDATE products" in s]
    assert len(update_calls) == 0

    # BACKORDER_CREATED must use quantity_delta=0 and field_affected="backorder".
    backorder_rows = [a for s, a in db.executed if "inventory_transactions" in s and len(a) > 2 and a[2] == BACKORDER_CREATED]
    assert backorder_rows[0][3] == 0
    assert backorder_rows[0][4] == "backorder"


@pytest.mark.asyncio
async def test_duplicate_reservation_raises():
    """check_and_reserve raises ValueError if active reservation already exists."""
    db = FakeDB()
    db._push_fetchrow(make_product())
    db._push_fetchrow(FakeRecord({"reservation_id": "RES-EXISTING"}))  # duplicate!

    with pytest.raises(ValueError, match="Active reservation already exists"):
        await check_and_reserve(db, "SKU-001", 10, "ORD-DUPE")


@pytest.mark.asyncio
async def test_eta_uses_confirmed_po():
    """ETA reliability = confirmed_po when a matching PO covers the needed quantity."""
    from datetime import datetime, timezone, timedelta
    future = datetime.now(timezone.utc) + timedelta(days=5)

    db = FakeDB()
    db._push_fetchrow(make_product(stock_on_hand=5, reserved_stock=5))   # product lock
    db._push_fetchrow(None)    # no duplicate reservation
    # confirmed PO covers quantity
    db._push_fetchrow(FakeRecord({
        "available_incoming": 20,
        "expected_arrival_date": future,
    }))

    result = await check_and_reserve(db, "SKU-001", 10, "ORD-TEST-PO")

    assert result["eta_reliability"] == "confirmed_po"
    assert result["expected_availability_date"] is not None


# ── fulfill_reservation ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fulfill_writes_two_ledger_rows():
    """fulfill_reservation inserts separate ledger rows for stock and reserved release."""
    db = FakeDB()
    db._push_fetchrow(make_reservation(quantity_reserved=20, quantity_backordered=0))
    db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "reserved_stock": 20}))

    result = await fulfill_reservation(db, "ORD-001", quantity_to_fulfill=20)

    assert result["fulfilled"] is True
    assert result["quantity_fulfilled"] == 20

    txn_inserts = [(s, a) for s, a in db.executed if "inventory_transactions" in s]
    assert len(txn_inserts) == 2, f"Expected 2 ledger rows, got {len(txn_inserts)}"

    fields = [a[4] for _, a in txn_inserts]   # field_affected is 5th positional param
    assert "stock_on_hand"  in fields
    assert "reserved_stock" in fields

    types = [a[2] for _, a in txn_inserts]
    assert FULFILLMENT_DEDUCTION in types
    assert FULFILLMENT_RESERVED_RELEASE in types

    product_updates = [(s, a) for s, a in db.executed if "UPDATE products" in s]
    assert len(product_updates) == 1
    _, update_args = product_updates[0]
    assert update_args[0] == 80
    assert update_args[1] == 0


@pytest.mark.asyncio
async def test_fulfill_partial_decrements_quantity_reserved():
    """Partial fulfillment updates quantity_reserved on the reservation row."""
    db = FakeDB()
    db._push_fetchrow(make_reservation(quantity_reserved=20, quantity_backordered=0))
    db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "reserved_stock": 20}))

    result = await fulfill_reservation(db, "ORD-001", quantity_to_fulfill=10)

    assert result["quantity_fulfilled"] == 10

    res_updates = [(s, a) for s, a in db.executed if "inventory_reservations" in s and "UPDATE" in s]
    assert len(res_updates) == 1
    sql, args = res_updates[0]
    # SET status=$1, quantity_reserved=$2, fulfilled_at=$3 WHERE reservation_id=$4
    assert args[1] == 10, f"Expected quantity_reserved=10 after partial fulfillment, got {args[1]}"
    assert args[0] == "active", "Status should remain 'active' after partial fulfillment"

    product_updates = [(s, a) for s, a in db.executed if "UPDATE products" in s]
    _, update_args = product_updates[0]
    assert update_args[0] == 90
    assert update_args[1] == 10


@pytest.mark.asyncio
async def test_fulfill_full_sets_status_fulfilled():
    """Full fulfillment sets reservation status to 'fulfilled' and quantity_reserved to 0."""
    db = FakeDB()
    db._push_fetchrow(make_reservation(quantity_reserved=20))
    db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "reserved_stock": 20}))

    await fulfill_reservation(db, "ORD-001", quantity_to_fulfill=20)

    res_updates = [(s, a) for s, a in db.executed if "inventory_reservations" in s and "UPDATE" in s]
    assert len(res_updates) == 1
    _, args = res_updates[0]
    assert args[0] == "fulfilled"
    assert args[1] == 0   # remaining_reserved = 20 - 20 = 0


@pytest.mark.asyncio
async def test_fulfill_idempotency_key_returns_previous_result():
    """Repeated fulfillment with the same idempotency key does not mutate stock again."""
    db = FakeDB()
    db._push_fetchrow(FakeRecord({
        "quantity_fulfilled": 10,
        "reservation_id": "RES-TESTRES01",
    }))

    result = await fulfill_reservation(
        db, "ORD-001", quantity_to_fulfill=10, idempotency_key="fulfill-001"
    )

    assert result == {
        "fulfilled": True,
        "quantity_fulfilled": 10,
        "reservation_id": "RES-TESTRES01",
        "warning": "already_fulfilled — idempotent return",
    }
    assert db.executed == []


@pytest.mark.asyncio
async def test_fulfill_writes_idempotency_metadata():
    """Fulfillment ledger rows carry idempotency metadata when a key is supplied."""
    db = FakeDB()
    db._push_fetchrow(None)  # no previous idempotent transaction
    db._push_fetchrow(make_reservation(quantity_reserved=20))
    db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "reserved_stock": 20}))

    await fulfill_reservation(
        db, "ORD-001", quantity_to_fulfill=20, idempotency_key="fulfill-002"
    )

    txn_inserts = [(s, a) for s, a in db.executed if "inventory_transactions" in s]
    assert len(txn_inserts) == 2
    assert all('"idempotency_key": "fulfill-002"' in a[11] for _, a in txn_inserts)


# ── release_reservation ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_release_fails_when_reserved_stock_less_than_reservation():
    """release_reservation raises instead of silently clamping corrupted reserved_stock."""
    db = FakeDB()
    db._push_fetchrow(make_reservation(quantity_reserved=20))
    db._push_fetchrow(FakeRecord({"reserved_stock": 10}))

    with pytest.raises(ValueError, match="reserved_stock is only 10"):
        await release_reservation(db, "ORD-001")

    assert db.executed == []


# ── record_adjustment ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stock_adjustment_increases_stock():
    """STOCK_ADJUSTMENT with positive delta writes transaction and updates stock."""
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "reserved_stock": 10}))

    result = await record_adjustment(
        db, "SKU-001", 50, STOCK_ADJUSTMENT,
        "Replenishment receipt — manual entry", "controller"
    )

    assert result["new_stock_on_hand"] == 150
    assert result["txn_id"].startswith("TXN-")
    assert result["warning"] is None

    # Exactly one UPDATE products and one INSERT inventory_transactions
    updates = [s for s, _ in db.executed if "UPDATE products" in s]
    inserts = [s for s, _ in db.executed if "inventory_transactions" in s]
    assert len(updates) == 1
    assert len(inserts) == 1


@pytest.mark.asyncio
async def test_stock_adjustment_blocks_negative_stock_by_default():
    """record_adjustment rejects negative result unless allow_negative=True."""
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"stock_on_hand": 10, "reserved_stock": 5}))

    with pytest.raises(ValueError, match="allow_negative"):
        await record_adjustment(
            db, "SKU-001", -50, STOCK_ADJUSTMENT,
            "Damaged goods write-off", "admin"
        )


@pytest.mark.asyncio
async def test_stock_adjustment_allow_negative_succeeds():
    """record_adjustment succeeds with allow_negative=True even if stock goes negative."""
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"stock_on_hand": 10, "reserved_stock": 5}))

    result = await record_adjustment(
        db, "SKU-001", -50, DAMAGED_INVENTORY,
        "Flood damage — write off", "admin",
        allow_negative=True,
    )

    assert result["new_stock_on_hand"] == -40


@pytest.mark.asyncio
async def test_stock_adjustment_warns_below_reserved():
    """record_adjustment returns warning when stock_on_hand drops below reserved_stock."""
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"stock_on_hand": 30, "reserved_stock": 25}))

    result = await record_adjustment(
        db, "SKU-001", -10, STOCK_ADJUSTMENT,
        "Physical count correction", "admin"
    )

    assert result["new_stock_on_hand"] == 20
    assert result["warning"] is not None
    assert "reserved_stock" in result["warning"]


@pytest.mark.asyncio
async def test_stock_adjustment_rejects_empty_reason():
    """record_adjustment raises ValueError for an empty reason string."""
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "reserved_stock": 0}))

    with pytest.raises(ValueError, match="reason"):
        await record_adjustment(
            db, "SKU-001", 10, STOCK_ADJUSTMENT, "  ", "admin"
        )


@pytest.mark.asyncio
async def test_stock_adjustment_rejects_invalid_txn_type():
    """record_adjustment raises ValueError for a non-adjustment txn_type."""
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "reserved_stock": 0}))

    with pytest.raises(ValueError, match="not a valid adjustment type"):
        await record_adjustment(
            db, "SKU-001", 10, ORDER_RESERVATION, "Should fail", "admin"
        )


# ── purchase order confirmation / receiving ─────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_purchase_order_increments_incoming_stock():
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"po_id": "PO-001", "status": "draft"}))
    db._fetch_seq.append([
        FakeRecord({
            "po_item_id": "POI-001",
            "po_id": "PO-001",
            "sku_id": "SKU-001",
            "quantity_ordered": 20,
            "quantity_received": 0,
        })
    ])
    db._push_fetchrow(FakeRecord({"incoming_stock": 5}))

    result = await confirm_purchase_order(db, "PO-001", performed_by="admin")

    assert result["status"] == "confirmed"
    assert result["movements"][0]["incoming_stock_after"] == 25
    txn_rows = [a for s, a in db.executed if "inventory_transactions" in s]
    assert txn_rows[0][2] == PURCHASE_ORDER_CONFIRMED
    assert txn_rows[0][4] == "incoming_stock"


@pytest.mark.asyncio
async def test_receive_purchase_order_moves_incoming_to_on_hand():
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"po_id": "PO-001", "status": "confirmed"}))
    db._push_fetchrow(FakeRecord({
        "po_item_id": "POI-001",
        "sku_id": "SKU-001",
        "quantity_ordered": 20,
        "quantity_received": 0,
    }))
    db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "incoming_stock": 20}))
    db._fetch_seq.append([FakeRecord({"quantity_ordered": 20, "quantity_received": 20})])
    db._push_fetchrow(FakeRecord({"stock_on_hand": 120, "reserved_stock": 0}))
    db._push_fetchrow(None)

    result = await receive_purchase_order(
        db, "PO-001", [{"sku_id": "SKU-001", "quantity_received": 20}]
    )

    assert result["status"] == "received"
    assert result["movements"][0]["incoming_stock_after"] == 0
    assert result["movements"][0]["stock_on_hand_after"] == 120
    txn_rows = [a for s, a in db.executed if "inventory_transactions" in s]
    txn_types = [a[2] for a in txn_rows]
    assert PURCHASE_RECEIPT_INCOMING_RELEASE in txn_types
    assert PURCHASE_RECEIPT in txn_types


@pytest.mark.asyncio
async def test_receive_purchase_order_rejects_draft_before_line_reads():
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"po_id": "PO-001", "status": "draft"}))

    with pytest.raises(ValueError, match="Purchase order must be confirmed before receiving"):
        await receive_purchase_order(
            db, "PO-001", [{"sku_id": "SKU-001", "quantity_received": 5}]
        )

    assert db.executed == []


@pytest.mark.asyncio
async def test_receive_purchase_order_blocks_over_receipt():
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"po_id": "PO-001", "status": "confirmed"}))
    db._push_fetchrow(FakeRecord({
        "po_item_id": "POI-001",
        "sku_id": "SKU-001",
        "quantity_ordered": 20,
        "quantity_received": 15,
    }))

    with pytest.raises(ValueError, match="only 5 remains open"):
        await receive_purchase_order(
            db, "PO-001", [{"sku_id": "SKU-001", "quantity_received": 6}]
        )


@pytest.mark.asyncio
async def test_receive_purchase_order_supports_partial_receipt():
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"po_id": "PO-001", "status": "confirmed"}))
    db._push_fetchrow(FakeRecord({
        "po_item_id": "POI-001",
        "sku_id": "SKU-001",
        "quantity_ordered": 20,
        "quantity_received": 0,
    }))
    db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "incoming_stock": 20}))
    db._fetch_seq.append([FakeRecord({"quantity_ordered": 20, "quantity_received": 5})])
    db._push_fetchrow(FakeRecord({"stock_on_hand": 105, "reserved_stock": 0}))
    db._push_fetchrow(None)

    result = await receive_purchase_order(
        db, "PO-001", [{"sku_id": "SKU-001", "quantity_received": 5}]
    )

    assert result["status"] == "partially_received"
    assert result["movements"][0]["line_status"] == "open"


@pytest.mark.asyncio
async def test_receive_purchase_order_idempotency_first_mutates_second_does_not():
    first_db = FakeDB()
    first_db._push_fetchrow(None)  # no previous idempotent receive
    first_db._push_fetchrow(FakeRecord({"po_id": "PO-001", "status": "confirmed"}))
    first_db._push_fetchrow(FakeRecord({
        "po_item_id": "POI-001",
        "sku_id": "SKU-001",
        "quantity_ordered": 20,
        "quantity_received": 0,
    }))
    first_db._push_fetchrow(FakeRecord({"stock_on_hand": 100, "incoming_stock": 20}))
    first_db._fetch_seq.append([FakeRecord({"quantity_ordered": 20, "quantity_received": 5})])
    first_db._push_fetchrow(FakeRecord({"stock_on_hand": 105, "reserved_stock": 0}))
    first_db._push_fetchrow(None)

    first = await receive_purchase_order(
        first_db, "PO-001", [{"sku_id": "SKU-001", "quantity_received": 5}],
        idempotency_key="recv-001",
    )

    assert first["idempotent"] is False
    first_stock_updates = [s for s, _ in first_db.executed if "UPDATE products" in s]
    assert len(first_stock_updates) == 1

    second_db = FakeDB()
    previous = {
        "po_id": "PO-001",
        "status": "partially_received",
        "movements": [{"sku_id": "SKU-001", "quantity_received": 5}],
        "backorders_cleared": [],
        "idempotent": False,
    }
    second_db._push_fetchrow(FakeRecord({"result": previous}))

    second = await receive_purchase_order(
        second_db, "PO-001", [{"sku_id": "SKU-001", "quantity_received": 5}],
        idempotency_key="recv-001",
    )

    assert second["idempotent"] is True
    assert second_db.executed == []


@pytest.mark.asyncio
async def test_auto_clear_backorders_oldest_first():
    db = FakeDB()
    db._push_fetchrow(FakeRecord({"stock_on_hand": 10, "reserved_stock": 5}))
    db._push_fetchrow(FakeRecord({
        "reservation_id": "RES-OLD",
        "order_id": "ORD-OLD",
        "sku_id": "SKU-001",
        "quantity_reserved": 0,
        "quantity_backordered": 3,
    }))
    db._push_fetchrow(FakeRecord({"stock_on_hand": 10, "reserved_stock": 8}))
    db._push_fetchrow(None)

    result = await auto_clear_backorders_for_sku(db, "SKU-001")

    assert result[0]["reservation_id"] == "RES-OLD"
    assert result[0]["quantity_reserved"] == 3
    txn_rows = [a for s, a in db.executed if "inventory_transactions" in s]
    txn_types = [a[2] for a in txn_rows]
    assert ORDER_RESERVATION in txn_types
    assert BACKORDER_FULFILLED in txn_types


# ── RULE-008 via policy_engine ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rule008_hitl_for_unknown_eta_full_backorder():
    """RULE-008: FULL_BACKORDER + eta_reliability=unknown → REQUIRE_HITL."""
    from policy.policy_engine import policy_engine, PolicyAction

    result = await policy_engine.evaluate(
        agent_name="test_agent",
        tool_name="inventory_check",
        tool_args={},
        context={
            "inventory_verdict": "FULL_BACKORDER",
            "eta_reliability": "unknown",
            "customer_id": "CUST-TEST",
            "order_id": "ORD-TEST",
        },
    )

    assert result["action"] == PolicyAction.REQUIRE_HITL
    assert "RULE-008_FULL_BACKORDER" in result["flags"]
    assert "BACKORDER_NO_ETA" in result.get("hitl_reason", "")


@pytest.mark.asyncio
async def test_rule008_proceeds_for_known_eta_full_backorder():
    """RULE-008: FULL_BACKORDER + confirmed_po ETA → PROCEED (no HITL)."""
    from policy.policy_engine import policy_engine, PolicyAction

    result = await policy_engine.evaluate(
        agent_name="test_agent",
        tool_name="inventory_check",
        tool_args={},
        context={
            "inventory_verdict": "FULL_BACKORDER",
            "eta_reliability": "confirmed_po",
            "customer_id": "CUST-TEST",
            "order_id": "ORD-TEST",
        },
    )

    assert result["action"] == PolicyAction.PROCEED
    assert "RULE-008_FULL_BACKORDER" in result["flags"]


@pytest.mark.asyncio
async def test_rule008_partial_appends_flag():
    """RULE-008: PARTIALLY_RESERVED → RULE-008_PARTIAL_FULFILLMENT flag appended."""
    from policy.policy_engine import policy_engine, PolicyAction

    result = await policy_engine.evaluate(
        agent_name="test_agent",
        tool_name="inventory_check",
        tool_args={},
        context={
            "inventory_verdict": "PARTIALLY_RESERVED",
            "eta_reliability": "estimated_lead_time",
            "customer_id": "CUST-TEST",
            "order_id": "ORD-TEST",
        },
    )

    assert "RULE-008_PARTIAL_FULFILLMENT" in result["flags"]
    assert result["action"] == PolicyAction.PROCEED


@pytest.mark.asyncio
async def test_rule008_hitl_for_unknown_eta_partial():
    """RULE-008: PARTIALLY_RESERVED + unknown ETA → REQUIRE_HITL."""
    from policy.policy_engine import policy_engine, PolicyAction

    result = await policy_engine.evaluate(
        agent_name="test_agent",
        tool_name="inventory_check",
        tool_args={},
        context={
            "inventory_verdict": "PARTIALLY_RESERVED",
            "eta_reliability": "unknown",
            "customer_id": "CUST-TEST",
            "order_id": "ORD-TEST",
        },
    )

    assert result["action"] == PolicyAction.REQUIRE_HITL
    assert "BACKORDER_NO_ETA" in result.get("hitl_reason", "")
