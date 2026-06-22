"""
O2C Agent v2.0 — Inventory API (Phase 2)
=========================================
Read and adjust endpoints for the inventory service.

Stock mutations NEVER touch products columns directly — all writes go through
services/inventory_service.py which wraps every mutation in an asyncpg
transaction with row-level locking.

Endpoints:
    GET  /api/inventory/transactions   — paginated ledger with filters
    POST /api/inventory/adjust         — manual stock adjustment
    GET  /api/inventory/stock-summary  — live stock view with reorder status
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database.postgres import get_db
from api.staff_deps import require_role
from services.inventory_service import (
    record_adjustment,
    STOCK_ADJUSTMENT,
    DAMAGED_INVENTORY,
    MANUAL_CORRECTION,
    RETURN_RECEIPT,
    ADJUSTMENT_TYPES,
)
from services.inventory_forecast_service import (
    generate_all_forecast_snapshots,
    generate_forecast_snapshot,
    get_inventory_forecast,
)

router = APIRouter()
logger = logging.getLogger(__name__)

INVENTORY_READ_ROLES   = ["admin", "controller", "inventory_manager"]
INVENTORY_ADJUST_ROLES = ["admin", "controller", "inventory_manager"]


# ── Pydantic models ───────────────────────────────────────────────────────────

class AdjustRequest(BaseModel):
    sku_id: str
    quantity_delta: int = Field(..., description="Positive = add stock, negative = remove")
    txn_type: str = Field(
        STOCK_ADJUSTMENT,
        description=f"One of: {sorted(ADJUSTMENT_TYPES)}",
    )
    reason: str = Field(..., min_length=3, description="Mandatory explanation for the adjustment")
    allow_negative: bool = Field(
        False,
        description="Set True only when forcing a write-off that results in negative stock",
    )


class ForecastRefreshRequest(BaseModel):
    days: int = Field(30, ge=1, le=365)
    sku_id: Optional[str] = None


# ── GET /transactions ─────────────────────────────────────────────────────────

@router.get("/transactions")
async def list_transactions(
    sku_id: Optional[str]             = Query(None),
    order_id: Optional[str]           = Query(None),
    purchase_order_id: Optional[str]  = Query(None),
    txn_type: Optional[str]           = Query(None),
    limit: int                        = Query(50, ge=1, le=500),
    offset: int                       = Query(0, ge=0),
    db=Depends(get_db),
    staff=Depends(require_role(INVENTORY_READ_ROLES)),
):
    """
    Paginated inventory transaction ledger.
    Filterable by sku_id, order_id, purchase_order_id, and txn_type.
    Results are ordered latest-first.
    """
    conditions = []
    params: list = []

    def _add(col: str, val):
        params.append(val)
        conditions.append(f"{col} = ${len(params)}")

    if sku_id:
        _add("sku_id", sku_id)
    if order_id:
        _add("order_id", order_id)
    if purchase_order_id:
        _add("purchase_order_id", purchase_order_id)
    if txn_type:
        _add("txn_type", txn_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    rows = await db.fetch(
        f"""SELECT txn_id, sku_id, txn_type, quantity_delta, field_affected,
                   balance_after, order_id, purchase_order_id, reason,
                   performed_by, actor_type, created_at
            FROM inventory_transactions
            {where}
            ORDER BY created_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}""",
        *params,
    )

    total = await db.fetchval(
        f"SELECT COUNT(*) FROM inventory_transactions {where}",
        *params[: len(params) - 2],
    )

    return {
        "transactions": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ── POST /adjust ──────────────────────────────────────────────────────────────

@router.post("/adjust")
async def adjust_stock(
    body: AdjustRequest,
    db=Depends(get_db),
    staff=Depends(require_role(INVENTORY_ADJUST_ROLES)),
):
    """
    Apply a manual stock adjustment.

    - Only STOCK_ADJUSTMENT, DAMAGED_INVENTORY, MANUAL_CORRECTION, RETURN_RECEIPT are accepted.
    - All writes go through inventory_service.record_adjustment (row-lock + transaction).
    - Returns updated stock summary and the new transaction id.
    """
    try:
        result = await record_adjustment(
            db=db,
            sku_id=body.sku_id,
            quantity_delta=body.quantity_delta,
            txn_type=body.txn_type,
            reason=body.reason,
            performed_by=staff["username"],
            actor_type="human",
            allow_negative=body.allow_negative,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error in adjust_stock for SKU %s", body.sku_id)
        raise HTTPException(status_code=500, detail=f"Adjustment failed: {exc}")

    # Return updated stock summary row alongside the transaction id
    summary_row = await db.fetchrow(
        """SELECT sku_id, product_name, category, stock_on_hand,
                  reserved_stock,
                  (stock_on_hand - reserved_stock) AS available_stock,
                  incoming_stock, reorder_level, safety_stock
           FROM products
           WHERE sku_id = $1""",
        body.sku_id,
    )

    return {
        "txn_id": result["txn_id"],
        "sku_id": result["sku_id"],
        "new_stock_on_hand": result["new_stock_on_hand"],
        "warning": result.get("warning"),
        "stock_summary": dict(summary_row) if summary_row else None,
    }


# ── GET /stock-summary ────────────────────────────────────────────────────────

@router.get("/stock-summary")
async def stock_summary(
    db=Depends(get_db),
    staff=Depends(require_role(INVENTORY_READ_ROLES)),
):
    """
    Live stock snapshot from the product_stock_summary view.

    Adds a computed reorder_status per SKU:
        URGENT  — available_stock <= safety_stock
        REORDER — available_stock <= reorder_level
        OK      — otherwise
    """
    rows = await db.fetch(
        """SELECT sku_id, product_name, category, unit_of_measure,
                  base_price_inr, stock_on_hand, reserved_stock, available_stock,
                  incoming_stock, reorder_level, safety_stock, lead_time_days,
                  reorder_qty, is_active
           FROM product_stock_summary
           ORDER BY sku_id"""
    )

    items = []
    for r in rows:
        row = dict(r)
        avail = row["available_stock"]
        safety = row["safety_stock"] or 0
        reorder = row["reorder_level"] or 0

        if avail <= safety:
            row["reorder_status"] = "URGENT"
        elif avail <= reorder:
            row["reorder_status"] = "REORDER"
        else:
            row["reorder_status"] = "OK"

        items.append(row)

    urgent  = sum(1 for i in items if i["reorder_status"] == "URGENT")
    reorder = sum(1 for i in items if i["reorder_status"] == "REORDER")

    return {
        "items": items,
        "summary": {
            "total_skus": len(items),
            "urgent_count": urgent,
            "reorder_count": reorder,
            "ok_count": len(items) - urgent - reorder,
        },
    }


@router.get("/forecast/{sku_id}")
async def forecast_for_sku(
    sku_id: str,
    days: int = Query(30, ge=1, le=365),
    refresh: bool = Query(False),
    db=Depends(get_db),
    staff=Depends(require_role(INVENTORY_READ_ROLES)),
):
    try:
        return await get_inventory_forecast(db, sku_id, days=days, refresh=refresh)
    except ValueError as exc:
        raise HTTPException(404, detail=str(exc))


@router.post("/forecast/refresh")
async def refresh_forecasts(
    body: Optional[ForecastRefreshRequest] = None,
    days: int = Query(30, ge=1, le=365),
    sku_id: Optional[str] = Query(None),
    db=Depends(get_db),
    staff=Depends(require_role(INVENTORY_ADJUST_ROLES)),
):
    refresh_days = body.days if body else days
    refresh_sku = body.sku_id if body and body.sku_id else sku_id
    try:
        if refresh_sku:
            return await generate_forecast_snapshot(db, refresh_sku, days=refresh_days, performed_by=staff["username"])
        return await generate_all_forecast_snapshots(db, days=refresh_days)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


@router.get("/dashboard-summary")
async def dashboard_summary(
    db=Depends(get_db),
    staff=Depends(require_role(INVENTORY_READ_ROLES)),
):
    stock_rows = await db.fetch(
        """SELECT sku_id, product_name, stock_on_hand, reserved_stock, available_stock,
                  incoming_stock, reorder_level, safety_stock
           FROM product_stock_summary
           ORDER BY available_stock ASC"""
    )
    backorder_rows = await db.fetch(
        """SELECT sku_id, SUM(quantity_backordered) AS quantity_backordered,
                  COUNT(*) AS order_count
           FROM inventory_reservations
           WHERE status = 'active' AND quantity_backordered > 0
           GROUP BY sku_id
           ORDER BY quantity_backordered DESC
           LIMIT 10"""
    )
    recent = await db.fetch(
        """SELECT txn_id, sku_id, txn_type, quantity_delta, field_affected,
                  balance_after, order_id, purchase_order_id, reason, created_at
           FROM inventory_transactions
           ORDER BY created_at DESC
           LIMIT 10"""
    )

    items = [dict(r) for r in stock_rows]
    urgent_count = sum(1 for r in items if (r.get("available_stock") or 0) <= (r.get("safety_stock") or 0))
    reorder_count = sum(
        1 for r in items
        if (r.get("available_stock") or 0) > (r.get("safety_stock") or 0)
        and (r.get("available_stock") or 0) <= (r.get("reorder_level") or 0)
    )
    ok_count = len(items) - urgent_count - reorder_count
    return {
        "total_skus": len(items),
        "urgent_count": urgent_count,
        "reorder_count": reorder_count,
        "ok_count": ok_count,
        "backordered_orders_count": sum(int(r.get("order_count") or 0) for r in backorder_rows),
        "incoming_pos_count": sum(1 for r in items if (r.get("incoming_stock") or 0) > 0),
        "total_available_stock": sum(int(r.get("available_stock") or 0) for r in items),
        "total_reserved_stock": sum(int(r.get("reserved_stock") or 0) for r in items),
        "total_incoming_stock": sum(int(r.get("incoming_stock") or 0) for r in items),
        "top_low_stock": items[:10],
        "top_backordered": [dict(r) for r in backorder_rows],
        "recent_inventory_transactions": [dict(r) for r in recent],
    }


@router.get("/incoming")
async def incoming_inventory(
    sku_id: Optional[str] = Query(None),
    db=Depends(get_db),
    staff=Depends(require_role(INVENTORY_READ_ROLES)),
):
    params = []
    where = "WHERE po.status IN ('confirmed','partially_received') AND (poi.quantity_ordered - poi.quantity_received) > 0"
    if sku_id:
        params.append(sku_id)
        where += f" AND poi.sku_id = ${len(params)}"
    rows = await db.fetch(
        f"""SELECT po.po_id, po.supplier_id, po.status, po.expected_arrival_date,
                   poi.sku_id, poi.quantity_ordered, poi.quantity_received,
                   (poi.quantity_ordered - poi.quantity_received) AS remaining_incoming,
                   poi.line_status
            FROM purchase_orders po
            JOIN purchase_order_items poi ON po.po_id = poi.po_id
            {where}
            ORDER BY po.expected_arrival_date ASC NULLS LAST, po.po_id""",
        *params,
    )
    return {"incoming": [dict(r) for r in rows], "total": len(rows)}
