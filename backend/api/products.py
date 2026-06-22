"""Read-only product stock API for inventory screens."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.staff_deps import require_role
from database.postgres import get_db


router = APIRouter()

PRODUCT_READ_ROLES = ["admin", "controller", "inventory_manager"]

VALID_REORDER_STATUSES = {"URGENT", "REORDER", "OK"}

REORDER_STATUS_CASE = """CASE
  WHEN available_stock <= safety_stock THEN 'URGENT'
  WHEN available_stock > safety_stock AND available_stock <= reorder_level THEN 'REORDER'
  ELSE 'OK'
END"""


def _with_reorder_status(row) -> dict:
    item = dict(row)
    available = item.get("available_stock") or 0
    safety = item.get("safety_stock") or 0
    reorder = item.get("reorder_level") or 0
    if available <= safety:
        item["reorder_status"] = "URGENT"
    elif available <= reorder:
        item["reorder_status"] = "REORDER"
    else:
        item["reorder_status"] = "OK"
    return item


@router.get("")
async def list_products(
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    reorder_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
    staff=Depends(require_role(PRODUCT_READ_ROLES)),
):
    if reorder_status and reorder_status not in VALID_REORDER_STATUSES:
        raise HTTPException(400, f"Invalid reorder_status '{reorder_status}'. Must be one of: {sorted(VALID_REORDER_STATUSES)}")

    conditions = ["is_active = TRUE"]
    params = []
    if search:
        params.append(f"%{search.lower()}%")
        conditions.append(f"(LOWER(sku_id) LIKE ${len(params)} OR LOWER(product_name) LIKE ${len(params)})")
    if category:
        params.append(category)
        conditions.append(f"category = ${len(params)}")
    if reorder_status:
        conditions.append(f"{REORDER_STATUS_CASE} = ${len(params) + 1}")

    where = "WHERE " + " AND ".join(conditions)

    if reorder_status:
        params.append(reorder_status)

    total = await db.fetchval(
        f"SELECT COUNT(*) FROM product_stock_summary {where}",
        *params,
    )

    params.extend([limit, offset])
    rows = await db.fetch(
        f"""SELECT sku_id, product_name, category, unit_of_measure, base_price_inr,
                   stock_on_hand, reserved_stock, available_stock, incoming_stock,
                   reorder_level, safety_stock, lead_time_days, reorder_qty, is_active
            FROM product_stock_summary
            {where}
            ORDER BY sku_id
            LIMIT ${len(params)-1} OFFSET ${len(params)}""",
        *params,
    )

    products = [_with_reorder_status(r) for r in rows]
    return {"products": products, "total": total, "limit": limit, "offset": offset}


@router.get("/{sku_id}")
async def get_product(
    sku_id: str,
    db=Depends(get_db),
    staff=Depends(require_role(PRODUCT_READ_ROLES)),
):
    row = await db.fetchrow(
        """SELECT sku_id, product_name, category, unit_of_measure, base_price_inr,
                  stock_on_hand, reserved_stock, available_stock, incoming_stock,
                  reorder_level, safety_stock, lead_time_days, reorder_qty, is_active
           FROM product_stock_summary
           WHERE sku_id = $1 AND is_active = TRUE""",
        sku_id,
    )
    if not row:
        raise HTTPException(404, f"Product {sku_id} not found")

    transactions = await db.fetch(
        """SELECT txn_id, sku_id, txn_type, quantity_delta, field_affected,
                  balance_after, order_id, purchase_order_id, reason, performed_by,
                  actor_type, created_at
           FROM inventory_transactions
           WHERE sku_id = $1
           ORDER BY created_at DESC
           LIMIT 20""",
        sku_id,
    )
    incoming = await db.fetch(
        """SELECT po.po_id, po.supplier_id, po.status, po.expected_arrival_date,
                  poi.sku_id, poi.quantity_ordered, poi.quantity_received,
                  (poi.quantity_ordered - poi.quantity_received) AS remaining_incoming,
                  poi.line_status
           FROM purchase_orders po
           JOIN purchase_order_items poi ON po.po_id = poi.po_id
           WHERE poi.sku_id = $1
             AND po.status IN ('confirmed','partially_received')
             AND (poi.quantity_ordered - poi.quantity_received) > 0
           ORDER BY po.expected_arrival_date ASC NULLS LAST, po.po_id""",
        sku_id,
    )
    product = _with_reorder_status(row)
    product["recent_transactions"] = [dict(r) for r in transactions]
    product["incoming_po_lines"] = [dict(r) for r in incoming]
    return product
