"""
O2C Agent v2.0 — Inventory Service (Phase 2)
=============================================
Single source of truth for all stock mutations.

RULE: No code outside this module may issue:
    UPDATE products SET stock_on_hand ...
    UPDATE products SET reserved_stock ...
    UPDATE products SET incoming_stock ...

All mutations are wrapped in asyncpg transactions with SELECT ... FOR UPDATE
row-level locking to prevent phantom reads and double-reservations under
concurrent request load.

Canonical txn_type values (see inventory-service-rules.md):
    STOCK_ADJUSTMENT          — manual correction or opening-balance entry
    ORDER_RESERVATION         — units reserved when an order is approved
    BACKORDER_CREATED         — qty moved to backorder when stock is insufficient
    FULFILLMENT_DEDUCTION     — stock_on_hand decremented when order ships
    FULFILLMENT_RESERVED_RELEASE — reserved_stock decremented when order ships
    ORDER_RELEASE_CANCELLED   — reservation freed on order cancel/reject
    PURCHASE_RECEIPT_INCOMING_RELEASE — incoming_stock decremented when PO goods arrive
    PURCHASE_RECEIPT          — incoming_stock→on_hand on PO receipt
    PURCHASE_ORDER_CONFIRMED  — incoming_stock incremented when supplier confirms PO
    DAMAGED_INVENTORY         — negative write-off for damaged/expired units
    MANUAL_CORRECTION         — explicit override with mandatory reason (controller only)
    RETURN_RECEIPT            — stock_on_hand incremented on customer return
    BACKORDER_FULFILLED       — backorder cleared after PURCHASE_RECEIPT replenishes stock
"""

import logging
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
import asyncpg

logger = logging.getLogger(__name__)

# ── Canonical txn_type constants ─────────────────────────────────────────────
STOCK_ADJUSTMENT         = "STOCK_ADJUSTMENT"
ORDER_RESERVATION        = "ORDER_RESERVATION"
BACKORDER_CREATED        = "BACKORDER_CREATED"
FULFILLMENT_DEDUCTION    = "FULFILLMENT_DEDUCTION"
FULFILLMENT_RESERVED_RELEASE = "FULFILLMENT_RESERVED_RELEASE"
ORDER_RELEASE_CANCELLED  = "ORDER_RELEASE_CANCELLED"
PURCHASE_RECEIPT_INCOMING_RELEASE = "PURCHASE_RECEIPT_INCOMING_RELEASE"
PURCHASE_RECEIPT         = "PURCHASE_RECEIPT"
PURCHASE_ORDER_CONFIRMED = "PURCHASE_ORDER_CONFIRMED"
DAMAGED_INVENTORY        = "DAMAGED_INVENTORY"
MANUAL_CORRECTION        = "MANUAL_CORRECTION"
RETURN_RECEIPT           = "RETURN_RECEIPT"
BACKORDER_FULFILLED      = "BACKORDER_FULFILLED"

ADJUSTMENT_TYPES = {STOCK_ADJUSTMENT, DAMAGED_INVENTORY, MANUAL_CORRECTION, RETURN_RECEIPT}

# ── Verdict constants ─────────────────────────────────────────────────────────
FULLY_RESERVED     = "FULLY_RESERVED"
PARTIALLY_RESERVED = "PARTIALLY_RESERVED"
FULL_BACKORDER     = "FULL_BACKORDER"


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reservation_id() -> str:
    return f"RES-{uuid.uuid4().hex[:20].upper()}"

def _txn_id() -> str:
    return f"TXN-{uuid.uuid4().hex[:20].upper()}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. check_and_reserve
# ─────────────────────────────────────────────────────────────────────────────

async def check_and_reserve(
    db,
    sku_id: str,
    quantity_requested: int,
    order_id: str,
    performed_by: str = "system",
    actor_type: str = "system",
) -> dict:
    """
    Reserve stock for an order atomically.

    Returns a dict with keys:
        verdict        — FULLY_RESERVED | PARTIALLY_RESERVED | FULL_BACKORDER
        quantity_reserved   — units actually reserved (subtracted from available)
        quantity_backordered — units placed in backorder
        reservation_id — id of the inventory_reservations row
        expected_availability_date — ISO string or None
        eta_reliability — 'confirmed_po' | 'estimated_lead_time' | 'unknown'
        warning        — optional warning string
    """
    if quantity_requested <= 0:
        raise ValueError(f"quantity_requested must be > 0, got {quantity_requested}")

    async with db.transaction():
        # Lock the product row for the duration of this transaction
        product = await db.fetchrow(
            "SELECT sku_id, stock_on_hand, reserved_stock, incoming_stock, "
            "reorder_level, safety_stock, lead_time_days, reorder_qty, is_active "
            "FROM products WHERE sku_id = $1 FOR UPDATE",
            sku_id,
        )
        if not product:
            raise ValueError(f"SKU {sku_id} not found")
        if not product["is_active"]:
            raise ValueError(f"SKU {sku_id} is inactive")

        # reserved_stock should never exceed stock_on_hand in a healthy state,
        # but a prior manual adjustment could create that condition.
        raw_available = product["stock_on_hand"] - product["reserved_stock"]
        available = max(0, raw_available)
        warning = None
        if raw_available < 0:
            warning = (
                f"stock_on_hand ({product['stock_on_hand']}) is below reserved_stock "
                f"({product['reserved_stock']}) for SKU {sku_id}; available stock was clamped to 0."
            )
        now = datetime.now(timezone.utc)

        # ── Guard: prevent duplicate active reservation for same order ────────
        existing = await db.fetchrow(
            "SELECT reservation_id FROM inventory_reservations "
            "WHERE order_id = $1 AND sku_id = $2 AND status = 'active'",
            order_id, sku_id,
        )
        if existing:
            raise ValueError(
                f"Active reservation already exists for order {order_id} / SKU {sku_id} "
                f"(reservation_id={existing['reservation_id']}). "
                "Release or fulfil the existing reservation first."
            )

        qty_reserve  = min(available, quantity_requested)
        qty_backorder = quantity_requested - qty_reserve

        # ── Determine verdict ─────────────────────────────────────────────────
        if qty_backorder == 0:
            verdict = FULLY_RESERVED
        elif qty_reserve == 0:
            verdict = FULL_BACKORDER
        else:
            verdict = PARTIALLY_RESERVED

        # ── Compute expected availability date ────────────────────────────────
        if qty_backorder > 0:
            eta_info = await compute_expected_availability_date(db, sku_id, qty_backorder)
        else:
            eta_info = {"expected_availability_date": None, "reliability": "not_needed"}

        # ── Mutate: increment reserved_stock ──────────────────────────────────
        if qty_reserve > 0:
            await db.execute(
                "UPDATE products SET reserved_stock = reserved_stock + $1, updated_at = NOW() "
                "WHERE sku_id = $2",
                qty_reserve, sku_id,
            )

        # ── Insert inventory_reservations row ─────────────────────────────────
        res_id = _reservation_id()
        eta_dt = eta_info.get("expected_availability_date")
        await db.execute(
            """INSERT INTO inventory_reservations
               (reservation_id, order_id, sku_id, quantity_requested,
                quantity_reserved, quantity_backordered, status,
                expected_availability_date, reserved_at, metadata)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
            res_id, order_id, sku_id, quantity_requested,
            qty_reserve, qty_backorder,
            "active",
            eta_dt,
            now,
            "{}",
        )

        # ── Insert ORDER_RESERVATION transaction if any units were reserved ───
        if qty_reserve > 0:
            new_reserved = product["reserved_stock"] + qty_reserve
            await db.execute(
                """INSERT INTO inventory_transactions
                   (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                    balance_after, order_id, reason, performed_by, actor_type, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                _txn_id(), sku_id, ORDER_RESERVATION, qty_reserve, "reserved_stock",
                new_reserved, order_id,
                f"Reserved {qty_reserve} of {quantity_requested} requested for order {order_id}",
                performed_by, actor_type, now,
            )

        # ── Insert BACKORDER_CREATED transaction if any units backordered ─────
        # IMPORTANT: no products stock column changes for backordered units.
        # The ledger row records the backorder state without a stock delta.
        if qty_backorder > 0:
            await db.execute(
                """INSERT INTO inventory_transactions
                   (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                    balance_after, order_id, reason, performed_by, actor_type, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                _txn_id(), sku_id, BACKORDER_CREATED, 0, "backorder",
                qty_backorder,  # balance_after = total backordered qty on this reservation
                order_id,
                f"Backordered {qty_backorder} units for order {order_id} — insufficient stock",
                performed_by, actor_type, now,
            )

    return {
        "verdict": verdict,
        "quantity_reserved": qty_reserve,
        "quantity_backordered": qty_backorder,
        "reservation_id": res_id,
        "expected_availability_date": eta_dt.isoformat() if eta_dt else None,
        "eta_reliability": eta_info.get("reliability", "unknown"),
        "warning": warning,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. compute_expected_availability_date
# ─────────────────────────────────────────────────────────────────────────────

async def compute_expected_availability_date(db, sku_id: str, quantity_needed: int) -> dict:
    """
    Estimate when enough stock will be available for quantity_needed units.

    Priority:
      1. Confirmed PO with sufficient quantity  → reliability = 'confirmed_po'
      2. products.lead_time_days fallback       → reliability = 'estimated_lead_time'
      3. Neither available                      → reliability = 'unknown'

    Returns:
        {expected_availability_date: datetime | None, reliability: str}
    """
    now = datetime.now(timezone.utc)

    # Check for open confirmed PO items that cover the needed quantity
    po_row = await db.fetchrow(
        """SELECT poi.quantity_ordered - poi.quantity_received AS available_incoming,
                  po.expected_arrival_date
           FROM purchase_order_items poi
           JOIN purchase_orders po ON poi.po_id = po.po_id
           WHERE poi.sku_id = $1
             AND po.status IN ('confirmed', 'in_transit')
             AND poi.line_status = 'open'
             AND po.expected_arrival_date IS NOT NULL
             AND (poi.quantity_ordered - poi.quantity_received) >= $2
           ORDER BY po.expected_arrival_date ASC
           LIMIT 1""",
        sku_id, quantity_needed,
    )

    if po_row and po_row["expected_arrival_date"]:
        return {
            "expected_availability_date": po_row["expected_arrival_date"],
            "reliability": "confirmed_po",
        }

    # Fall back to lead_time_days from products
    product = await db.fetchrow(
        "SELECT lead_time_days FROM products WHERE sku_id = $1", sku_id
    )
    if product and product["lead_time_days"] and product["lead_time_days"] > 0:
        eta = now + timedelta(days=product["lead_time_days"])
        return {
            "expected_availability_date": eta,
            "reliability": "estimated_lead_time",
        }

    return {"expected_availability_date": None, "reliability": "unknown"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. fulfill_reservation
# ─────────────────────────────────────────────────────────────────────────────

async def fulfill_reservation(
    db,
    order_id: str,
    quantity_to_fulfill: Optional[int] = None,
    performed_by: str = "system",
    actor_type: str = "system",
    idempotency_key: Optional[str] = None,
) -> dict:
    """
    Deduct stock when an order ships.

    - Decrements stock_on_hand and reserved_stock by the fulfilled quantity.
    - Writes two ledger rows per fulfillment: FULFILLMENT_DEDUCTION for
      stock_on_hand and FULFILLMENT_RESERVED_RELEASE for reserved_stock.
    - For partial fulfillment, decrements quantity_reserved on the reservation
      row and leaves status as 'active' until fully fulfilled.
    - Updates order status to 'fulfilled' when fully fulfilled.

    idempotency_key: persisted in inventory_transactions.metadata so safe
      retries return the previous fulfillment result without decrementing twice.

    Returns:
        {fulfilled: bool, quantity_fulfilled: int, reservation_id: str, warning: str | None}
    """
    async with db.transaction():
        if idempotency_key:
            previous = await db.fetchrow(
                """SELECT ABS(quantity_delta) AS quantity_fulfilled,
                          metadata->>'reservation_id' AS reservation_id
                   FROM inventory_transactions
                   WHERE order_id = $1
                     AND txn_type = $2
                     AND field_affected = 'stock_on_hand'
                     AND metadata->>'idempotency_key' = $3
                   ORDER BY created_at DESC
                   LIMIT 1""",
                order_id, FULFILLMENT_DEDUCTION, idempotency_key,
            )
            if previous:
                return {
                    "fulfilled": True,
                    "quantity_fulfilled": previous["quantity_fulfilled"],
                    "reservation_id": previous["reservation_id"],
                    "warning": "already_fulfilled — idempotent return",
                }

        # Lock the reservation row
        reservation = await db.fetchrow(
            "SELECT * FROM inventory_reservations "
            "WHERE order_id = $1 AND status IN ('active','backordered') "
            "FOR UPDATE",
            order_id,
        )

        if not reservation:
            # Check for already-fulfilled (idempotent return)
            done = await db.fetchrow(
                "SELECT * FROM inventory_reservations WHERE order_id = $1 AND status = 'fulfilled'",
                order_id,
            )
            if done:
                return {
                    "fulfilled": True,
                    "quantity_fulfilled": done["quantity_reserved"],
                    "reservation_id": done["reservation_id"],
                    "warning": "already_fulfilled — idempotent return",
                }
            raise ValueError(f"No active reservation found for order {order_id}")

        if reservation["status"] in ("released_cancelled", "cancelled"):
            raise ValueError(
                f"Reservation {reservation['reservation_id']} is {reservation['status']} "
                "and cannot be fulfilled."
            )

        qty_reserved = reservation["quantity_reserved"]
        qty_fulfill = quantity_to_fulfill if quantity_to_fulfill is not None else qty_reserved
        if qty_fulfill <= 0:
            raise ValueError(f"quantity_to_fulfill must be > 0, got {qty_fulfill}")
        if qty_fulfill > qty_reserved:
            raise ValueError(
                f"Cannot fulfill {qty_fulfill} — only {qty_reserved} units reserved "
                f"for order {order_id}"
            )

        sku_id = reservation["sku_id"]
        now = datetime.now(timezone.utc)

        # Lock and read product
        product = await db.fetchrow(
            "SELECT stock_on_hand, reserved_stock FROM products WHERE sku_id = $1 FOR UPDATE",
            sku_id,
        )
        if not product:
            raise ValueError(f"SKU {sku_id} not found")

        new_stock    = product["stock_on_hand"]  - qty_fulfill
        new_reserved = product["reserved_stock"] - qty_fulfill

        if new_stock < 0:
            raise ValueError(
                f"Cannot fulfil {qty_fulfill} — only {product['stock_on_hand']} units "
                f"physically on hand for SKU {sku_id}"
            )
        if new_reserved < 0:
            raise ValueError(
                f"Cannot fulfil {qty_fulfill} — product reserved_stock is only "
                f"{product['reserved_stock']} for SKU {sku_id}"
            )

        txn_metadata = json.dumps({
            "idempotency_key": idempotency_key,
            "reservation_id": reservation["reservation_id"],
        }) if idempotency_key else "{}"

        # ── Mutate product: decrement both stock_on_hand and reserved_stock ───
        await db.execute(
            "UPDATE products SET stock_on_hand = $1, reserved_stock = $2, updated_at = NOW() "
            "WHERE sku_id = $3",
            new_stock, new_reserved, sku_id,
        )

        # ── Ledger row 1: FULFILLMENT_DEDUCTION against stock_on_hand ─────────
        await db.execute(
            """INSERT INTO inventory_transactions
               (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                 balance_after, order_id, reason, performed_by, actor_type, created_at, metadata)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            _txn_id(), sku_id, FULFILLMENT_DEDUCTION, -qty_fulfill, "stock_on_hand",
            new_stock, order_id,
            f"Fulfillment deduction for order {order_id}: {qty_fulfill} units shipped",
            performed_by, actor_type, now, txn_metadata,
        )

        # ── Ledger row 2: FULFILLMENT_RESERVED_RELEASE against reserved_stock ─
        # A separate row documents the reserved_stock decrement so the ledger
        # accurately reflects every change to every column.
        await db.execute(
            """INSERT INTO inventory_transactions
               (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                 balance_after, order_id, reason, performed_by, actor_type, created_at, metadata)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            _txn_id(), sku_id, FULFILLMENT_RESERVED_RELEASE, -qty_fulfill, "reserved_stock",
            new_reserved, order_id,
            f"Reserved stock released for order {order_id}: {qty_fulfill} units fulfilled",
            performed_by, actor_type, now, txn_metadata,
        )

        # ── Update reservation: decrement quantity_reserved for partial fills ─
        fully_fulfilled = qty_fulfill >= qty_reserved
        remaining_reserved = qty_reserved - qty_fulfill
        new_status = "fulfilled" if fully_fulfilled else "active"
        await db.execute(
            """UPDATE inventory_reservations
               SET status = $1,
                   quantity_reserved = $2,
                   fulfilled_at = $3
               WHERE reservation_id = $4""",
            new_status,
            remaining_reserved,
            now if fully_fulfilled else None,
            reservation["reservation_id"],
        )

        # ── Update order status to fulfilled when fully done ──────────────────
        if fully_fulfilled:
            await db.execute(
                "UPDATE orders SET status = 'fulfilled', updated_at = NOW() WHERE order_id = $1",
                order_id,
            )

    return {
        "fulfilled": True,
        "quantity_fulfilled": qty_fulfill,
        "reservation_id": reservation["reservation_id"],
        "warning": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. release_reservation
# ─────────────────────────────────────────────────────────────────────────────

async def release_reservation(
    db,
    order_id: str,
    performed_by: str = "system",
    actor_type: str = "system",
    force: bool = False,
) -> dict:
    """
    Release a reservation when an order is cancelled or rejected.

    - Decrements reserved_stock by quantity_reserved.
    - Does NOT touch stock_on_hand.
    - Marks reservation as 'released_cancelled'.
    - Inserts ORDER_RELEASE_CANCELLED transaction.

    Returns:
        {released: bool, quantity_released: int, reservation_id: str}
    """
    async with db.transaction():
        reservation = await db.fetchrow(
            "SELECT * FROM inventory_reservations WHERE order_id = $1 AND status = 'active' "
            "FOR UPDATE",
            order_id,
        )
        if not reservation:
            # If already released, return gracefully (idempotent)
            done = await db.fetchrow(
                "SELECT * FROM inventory_reservations "
                "WHERE order_id = $1 AND status = 'released_cancelled'",
                order_id,
            )
            if done:
                return {
                    "released": True,
                    "quantity_released": done["quantity_reserved"],
                    "reservation_id": done["reservation_id"],
                    "warning": "already_released — idempotent return",
                }
            raise ValueError(f"No active reservation found for order {order_id} to release")

        sku_id = reservation["sku_id"]
        qty_reserved = reservation["quantity_reserved"]
        now = datetime.now(timezone.utc)

        # Lock product
        product = await db.fetchrow(
            "SELECT reserved_stock FROM products WHERE sku_id = $1 FOR UPDATE", sku_id
        )
        if not product:
            raise ValueError(f"SKU {sku_id} not found")

        if product["reserved_stock"] < qty_reserved and not force:
            raise ValueError(
                f"Cannot release {qty_reserved} units — product reserved_stock is only "
                f"{product['reserved_stock']} for SKU {sku_id}. Use force=True only to repair data corruption."
            )

        new_reserved = (
            max(0, product["reserved_stock"] - qty_reserved)
            if force
            else product["reserved_stock"] - qty_reserved
        )

        # ── Mutate: decrement reserved_stock only ────────────────────────────
        await db.execute(
            "UPDATE products SET reserved_stock = $1, updated_at = NOW() WHERE sku_id = $2",
            new_reserved, sku_id,
        )

        # ── Insert ORDER_RELEASE_CANCELLED transaction ────────────────────────
        await db.execute(
            """INSERT INTO inventory_transactions
               (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                balance_after, order_id, reason, performed_by, actor_type, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
            _txn_id(), sku_id, ORDER_RELEASE_CANCELLED, -qty_reserved, "reserved_stock",
            new_reserved, order_id,
            f"Reservation released for order {order_id}: {qty_reserved} units returned to available",
            performed_by, actor_type, now,
        )

        # ── Mark reservation released ─────────────────────────────────────────
        await db.execute(
            "UPDATE inventory_reservations SET status = 'released_cancelled', released_at = $1 "
            "WHERE reservation_id = $2",
            now, reservation["reservation_id"],
        )

    return {
        "released": True,
        "quantity_released": qty_reserved,
        "reservation_id": reservation["reservation_id"],
        "warning": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. record_adjustment
# ─────────────────────────────────────────────────────────────────────────────

async def record_adjustment(
    db,
    sku_id: str,
    quantity_delta: int,
    txn_type: str,
    reason: str,
    performed_by: str,
    actor_type: str = "human",
    allow_negative: bool = False,
) -> dict:
    """
    Apply a manual stock adjustment to stock_on_hand.

    Supports: STOCK_ADJUSTMENT, DAMAGED_INVENTORY, MANUAL_CORRECTION, RETURN_RECEIPT.
    Requires a non-empty reason string.
    Blocks negative stock unless allow_negative=True.
    Returns a warning if stock_on_hand would drop below reserved_stock.

    Returns:
        {sku_id, new_stock_on_hand, txn_id, warning: str | None}
    """
    if txn_type not in ADJUSTMENT_TYPES:
        raise ValueError(
            f"txn_type '{txn_type}' is not a valid adjustment type. "
            f"Allowed: {sorted(ADJUSTMENT_TYPES)}"
        )
    if not reason or not reason.strip():
        raise ValueError("reason must be a non-empty string for stock adjustments")
    if quantity_delta == 0:
        raise ValueError("quantity_delta must be non-zero")

    async with db.transaction():
        product = await db.fetchrow(
            "SELECT stock_on_hand, reserved_stock FROM products WHERE sku_id = $1 FOR UPDATE",
            sku_id,
        )
        if not product:
            raise ValueError(f"SKU {sku_id} not found")

        new_stock = product["stock_on_hand"] + quantity_delta

        if not allow_negative and new_stock < 0:
            raise ValueError(
                f"Adjustment would set stock_on_hand to {new_stock} for SKU {sku_id}. "
                "Pass allow_negative=True to force this."
            )

        warning = None
        if new_stock < product["reserved_stock"]:
            warning = (
                f"stock_on_hand ({new_stock}) is now below reserved_stock "
                f"({product['reserved_stock']}) for SKU {sku_id}. "
                "Review active reservations."
            )

        now = datetime.now(timezone.utc)

        # ── Mutate stock_on_hand ──────────────────────────────────────────────
        await db.execute(
            "UPDATE products SET stock_on_hand = $1, updated_at = NOW() WHERE sku_id = $2",
            new_stock, sku_id,
        )

        # ── Insert transaction in same db.transaction() block ─────────────────
        txn_id = _txn_id()
        await db.execute(
            """INSERT INTO inventory_transactions
               (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                balance_after, reason, performed_by, actor_type, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
            txn_id, sku_id, txn_type, quantity_delta, "stock_on_hand",
            new_stock, reason.strip(), performed_by, actor_type, now,
        )

    return {
        "sku_id": sku_id,
        "new_stock_on_hand": new_stock,
        "txn_id": txn_id,
        "warning": warning,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. confirm_purchase_order
# ─────────────────────────────────────────────────────────────────────────────

async def confirm_purchase_order(
    db,
    po_id: str,
    performed_by: str = "system",
    actor_type: str = "human",
) -> dict:
    """Confirm a draft purchase order and move ordered remaining qty into incoming_stock."""
    async with db.transaction():
        po = await db.fetchrow(
            "SELECT * FROM purchase_orders WHERE po_id = $1 FOR UPDATE",
            po_id,
        )
        if not po:
            raise ValueError(f"Purchase order {po_id} not found")
        if po["status"] != "draft":
            raise ValueError(f"Only draft purchase orders can be confirmed; {po_id} is {po['status']}")

        items = await db.fetch(
            "SELECT * FROM purchase_order_items WHERE po_id = $1 FOR UPDATE",
            po_id,
        )
        if not items:
            raise ValueError(f"Purchase order {po_id} has no line items")

        now = datetime.now(timezone.utc)
        movements = []
        for item in items:
            qty_incoming = item["quantity_ordered"] - item["quantity_received"]
            if qty_incoming <= 0:
                continue

            product = await db.fetchrow(
                "SELECT incoming_stock FROM products WHERE sku_id = $1 FOR UPDATE",
                item["sku_id"],
            )
            if not product:
                raise ValueError(f"SKU {item['sku_id']} not found")

            new_incoming = product["incoming_stock"] + qty_incoming
            await db.execute(
                "UPDATE products SET incoming_stock = $1, updated_at = NOW() WHERE sku_id = $2",
                new_incoming, item["sku_id"],
            )
            await db.execute(
                """INSERT INTO inventory_transactions
                   (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                    balance_after, purchase_order_id, reason, performed_by, actor_type, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                _txn_id(), item["sku_id"], PURCHASE_ORDER_CONFIRMED, qty_incoming,
                "incoming_stock", new_incoming, po_id,
                f"Purchase order {po_id} confirmed: {qty_incoming} units incoming",
                performed_by, actor_type, now,
            )
            movements.append({
                "sku_id": item["sku_id"],
                "quantity_incoming": qty_incoming,
                "incoming_stock_after": new_incoming,
            })

        await db.execute(
            "UPDATE purchase_orders SET status='confirmed', confirmed_at=$1 WHERE po_id=$2",
            now, po_id,
        )

    return {"po_id": po_id, "status": "confirmed", "movements": movements}


# ─────────────────────────────────────────────────────────────────────────────
# 7. receive_purchase_order
# ─────────────────────────────────────────────────────────────────────────────

async def receive_purchase_order(
    db,
    po_id: str,
    received_items: list,
    performed_by: str = "system",
    actor_type: str = "human",
    idempotency_key: Optional[str] = None,
) -> dict:
    """Receive PO line quantities into stock_on_hand and release incoming_stock."""
    if not received_items:
        raise ValueError("received_items must contain at least one line")

    async with db.transaction():
        if idempotency_key:
            previous = await db.fetchrow(
                """SELECT metadata->'result' AS result
                   FROM inventory_transactions
                   WHERE purchase_order_id = $1
                     AND txn_type = $2
                     AND metadata->>'idempotency_key' = $3
                   ORDER BY created_at DESC
                   LIMIT 1""",
                po_id, PURCHASE_RECEIPT, idempotency_key,
            )
            if previous and previous["result"]:
                result = previous["result"]
                if isinstance(result, str):
                    result = json.loads(result)
                result["idempotent"] = True
                return result

        po = await db.fetchrow(
            "SELECT * FROM purchase_orders WHERE po_id = $1 FOR UPDATE",
            po_id,
        )
        if not po:
            raise ValueError(f"Purchase order {po_id} not found")
        if po["status"] == "draft":
            raise ValueError("Purchase order must be confirmed before receiving")
        if po["status"] not in ("confirmed", "partially_received"):
            raise ValueError(
                f"Purchase order {po_id} is '{po['status']}' and cannot be received"
            )

        now = datetime.now(timezone.utc)
        movements = []
        touched_skus = []

        for line in received_items:
            sku_id = line.get("sku_id")
            qty_received = int(line.get("quantity_received", 0))
            if not sku_id:
                raise ValueError("received item missing sku_id")
            if qty_received <= 0:
                raise ValueError(f"quantity_received must be > 0 for SKU {sku_id}")

            item = await db.fetchrow(
                "SELECT * FROM purchase_order_items WHERE po_id = $1 AND sku_id = $2 FOR UPDATE",
                po_id, sku_id,
            )
            if not item:
                raise ValueError(f"Purchase order {po_id} has no line for SKU {sku_id}")

            remaining = item["quantity_ordered"] - item["quantity_received"]
            if qty_received > remaining:
                raise ValueError(
                    f"Cannot receive {qty_received} for SKU {sku_id}; only {remaining} remains open"
                )

            product = await db.fetchrow(
                "SELECT stock_on_hand, incoming_stock FROM products WHERE sku_id = $1 FOR UPDATE",
                sku_id,
            )
            if not product:
                raise ValueError(f"SKU {sku_id} not found")
            if product["incoming_stock"] < qty_received:
                raise ValueError(
                    f"Cannot receive {qty_received} for SKU {sku_id}; incoming_stock is only "
                    f"{product['incoming_stock']}. Repair incoming_stock before receiving."
                )

            new_incoming = product["incoming_stock"] - qty_received
            new_stock = product["stock_on_hand"] + qty_received
            new_line_received = item["quantity_received"] + qty_received
            line_status = "received" if new_line_received == item["quantity_ordered"] else "open"

            await db.execute(
                "UPDATE products SET incoming_stock=$1, stock_on_hand=$2, updated_at=NOW() WHERE sku_id=$3",
                new_incoming, new_stock, sku_id,
            )
            await db.execute(
                "UPDATE purchase_order_items SET quantity_received=$1, line_status=$2 WHERE po_item_id=$3",
                new_line_received, line_status, item["po_item_id"],
            )

            metadata = json.dumps({"idempotency_key": idempotency_key}) if idempotency_key else "{}"
            await db.execute(
                """INSERT INTO inventory_transactions
                   (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                    balance_after, purchase_order_id, reason, performed_by, actor_type, created_at, metadata)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                _txn_id(), sku_id, PURCHASE_RECEIPT_INCOMING_RELEASE, -qty_received,
                "incoming_stock", new_incoming, po_id,
                f"Purchase order {po_id} received: released {qty_received} incoming units",
                performed_by, actor_type, now, metadata,
            )
            await db.execute(
                """INSERT INTO inventory_transactions
                   (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                    balance_after, purchase_order_id, reason, performed_by, actor_type, created_at, metadata)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                _txn_id(), sku_id, PURCHASE_RECEIPT, qty_received,
                "stock_on_hand", new_stock, po_id,
                f"Purchase order {po_id} received: added {qty_received} units on hand",
                performed_by, actor_type, now, metadata,
            )

            movements.append({
                "sku_id": sku_id,
                "quantity_received": qty_received,
                "incoming_stock_after": new_incoming,
                "stock_on_hand_after": new_stock,
                "line_status": line_status,
            })
            touched_skus.append(sku_id)

        lines = await db.fetch(
            "SELECT quantity_ordered, quantity_received FROM purchase_order_items WHERE po_id = $1 FOR UPDATE",
            po_id,
        )
        all_received = all(r["quantity_received"] >= r["quantity_ordered"] for r in lines)
        any_received = any(r["quantity_received"] > 0 for r in lines)
        po_status = "received" if all_received else ("partially_received" if any_received else po["status"])
        await db.execute(
            "UPDATE purchase_orders SET status=$1, received_at=$2 WHERE po_id=$3",
            po_status, now if all_received else None, po_id,
        )

        backorders_cleared = []
        for sku_id in dict.fromkeys(touched_skus):
            backorders_cleared.extend(
                await auto_clear_backorders_for_sku(db, sku_id, performed_by=performed_by)
            )

        result = {
            "po_id": po_id,
            "status": po_status,
            "movements": movements,
            "backorders_cleared": backorders_cleared,
            "idempotent": False,
        }

        if idempotency_key:
            result_metadata = json.dumps({"idempotency_key": idempotency_key, "result": result})
            await db.execute(
                """UPDATE inventory_transactions
                   SET metadata = $1::jsonb
                   WHERE purchase_order_id = $2
                     AND txn_type IN ($3, $4)
                     AND metadata->>'idempotency_key' = $5""",
                result_metadata, po_id, PURCHASE_RECEIPT, PURCHASE_RECEIPT_INCOMING_RELEASE, idempotency_key,
            )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 8. auto_clear_backorders_for_sku
# ─────────────────────────────────────────────────────────────────────────────

async def auto_clear_backorders_for_sku(db, sku_id: str, performed_by: str = "system") -> list:
    """Reserve newly available stock against active backorders FIFO by reserved_at."""
    cleared = []
    while True:
        product = await db.fetchrow(
            "SELECT stock_on_hand, reserved_stock FROM products WHERE sku_id = $1 FOR UPDATE",
            sku_id,
        )
        if not product:
            raise ValueError(f"SKU {sku_id} not found")
        available = max(0, product["stock_on_hand"] - product["reserved_stock"])
        if available <= 0:
            break

        reservation = await db.fetchrow(
            """SELECT * FROM inventory_reservations
               WHERE sku_id = $1 AND status = 'active' AND quantity_backordered > 0
               ORDER BY reserved_at ASC
               LIMIT 1
               FOR UPDATE""",
            sku_id,
        )
        if not reservation:
            break

        qty_to_reserve = min(available, reservation["quantity_backordered"])
        new_reserved_stock = product["reserved_stock"] + qty_to_reserve
        new_qty_reserved = reservation["quantity_reserved"] + qty_to_reserve
        new_qty_backordered = reservation["quantity_backordered"] - qty_to_reserve
        now = datetime.now(timezone.utc)

        await db.execute(
            "UPDATE products SET reserved_stock=$1, updated_at=NOW() WHERE sku_id=$2",
            new_reserved_stock, sku_id,
        )
        await db.execute(
            """UPDATE inventory_reservations
               SET quantity_reserved=$1, quantity_backordered=$2, status='active'
               WHERE reservation_id=$3""",
            new_qty_reserved, new_qty_backordered, reservation["reservation_id"],
        )
        await db.execute(
            """INSERT INTO inventory_transactions
               (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                balance_after, order_id, reason, performed_by, actor_type, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
            _txn_id(), sku_id, ORDER_RESERVATION, qty_to_reserve, "reserved_stock",
            new_reserved_stock, reservation["order_id"],
            f"Reserved {qty_to_reserve} backordered units after replenishment",
            performed_by, "system", now,
        )
        if new_qty_backordered == 0:
            await db.execute(
                """INSERT INTO inventory_transactions
                   (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                    balance_after, order_id, reason, performed_by, actor_type, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                _txn_id(), sku_id, BACKORDER_FULFILLED, -qty_to_reserve, "backorder",
                0, reservation["order_id"],
                f"Backorder fully cleared for reservation {reservation['reservation_id']}",
                performed_by, "system", now,
            )

        cleared.append({
            "reservation_id": reservation["reservation_id"],
            "order_id": reservation["order_id"],
            "sku_id": sku_id,
            "quantity_reserved": qty_to_reserve,
            "quantity_backordered_remaining": new_qty_backordered,
        })

    return cleared
