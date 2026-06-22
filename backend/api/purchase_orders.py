"""Purchase Orders API for inventory replenishment."""

import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.staff_deps import require_role
from database.postgres import get_db
from services.inventory_service import confirm_purchase_order, receive_purchase_order


def _pydantic_to_dict(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj.dict()


router = APIRouter()

PO_READ_ROLES = ["admin", "controller", "inventory_manager"]
PO_WRITE_ROLES = ["admin", "controller", "inventory_manager"]


class PurchaseOrderLineCreate(BaseModel):
    sku_id: str
    quantity_ordered: int = Field(gt=0)
    unit_cost_inr: float = 0


class PurchaseOrderCreate(BaseModel):
    supplier_id: Optional[str] = None
    expected_arrival_date: Optional[str] = None
    items: List[PurchaseOrderLineCreate]


class ReceiveLine(BaseModel):
    sku_id: str
    quantity_received: int = Field(gt=0)


class ReceivePurchaseOrderRequest(BaseModel):
    items: List[ReceiveLine]
    idempotency_key: Optional[str] = None


def _po_id() -> str:
    return f"PO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"


def _po_item_id() -> str:
    return f"POI-{uuid.uuid4().hex[:20].upper()}"


async def _fetch_po_with_items(db, po_id: str) -> dict:
    po = await db.fetchrow("SELECT * FROM purchase_orders WHERE po_id = $1", po_id)
    if not po:
        raise HTTPException(404, f"Purchase order {po_id} not found")
    items = await db.fetch(
        "SELECT * FROM purchase_order_items WHERE po_id = $1 ORDER BY created_at, sku_id",
        po_id,
    )
    result = dict(po)
    result["items"] = [dict(i) for i in items]
    return result


@router.get("")
async def list_purchase_orders(
    status: Optional[str] = None,
    sku_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db=Depends(get_db),
    staff=Depends(require_role(PO_READ_ROLES)),
):
    params = []
    count_params = []
    query = "SELECT DISTINCT po.* FROM purchase_orders po"
    count_query = "SELECT COUNT(DISTINCT po.po_id) FROM purchase_orders po"
    if sku_id:
        query += " JOIN purchase_order_items poi ON po.po_id = poi.po_id"
        count_query += " JOIN purchase_order_items poi ON po.po_id = poi.po_id"
    query += " WHERE 1=1"
    count_query += " WHERE 1=1"
    if status:
        params.append(status)
        count_params.append(status)
        query += f" AND po.status = ${len(params)}"
        count_query += f" AND po.status = ${len(count_params)}"
    if sku_id:
        params.append(sku_id)
        count_params.append(sku_id)
        query += f" AND poi.sku_id = ${len(params)}"
        count_query += f" AND poi.sku_id = ${len(count_params)}"

    total = await db.fetchval(count_query, *count_params)

    params.extend([limit, offset])
    query += f" ORDER BY po.created_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}"

    rows = await db.fetch(query, *params)
    orders = []
    for row in rows:
        po = dict(row)
        items = await db.fetch(
            "SELECT * FROM purchase_order_items WHERE po_id = $1 ORDER BY created_at, sku_id",
            po["po_id"],
        )
        po["items"] = [dict(i) for i in items]
        orders.append(po)
    return {"purchase_orders": orders, "total": total}


@router.get("/{po_id}")
async def get_purchase_order(
    po_id: str,
    db=Depends(get_db),
    staff=Depends(require_role(PO_READ_ROLES)),
):
    return await _fetch_po_with_items(db, po_id)


@router.post("")
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    db=Depends(get_db),
    staff=Depends(require_role(PO_WRITE_ROLES)),
):
    if not payload.items:
        raise HTTPException(400, "Purchase order must include at least one line item")

    seen = set()
    po_id = _po_id()
    try:
        async with db.transaction():
            for item in payload.items:
                if item.sku_id in seen:
                    raise HTTPException(400, f"Duplicate SKU {item.sku_id} in purchase order")
                seen.add(item.sku_id)
                product = await db.fetchrow(
                    "SELECT sku_id FROM products WHERE sku_id = $1 AND is_active = TRUE",
                    item.sku_id,
                )
                if not product:
                    raise HTTPException(400, f"SKU {item.sku_id} not found or inactive")

            expected_arrival = None
            if payload.expected_arrival_date:
                try:
                    expected_arrival = datetime.fromisoformat(payload.expected_arrival_date.replace("Z", "+00:00"))
                except ValueError:
                    raise HTTPException(400, "expected_arrival_date must be ISO-8601")

            await db.execute(
                """INSERT INTO purchase_orders
                   (po_id, supplier_id, status, expected_arrival_date, created_by)
                   VALUES ($1,$2,'draft',$3,$4)""",
                po_id, payload.supplier_id or "", expected_arrival, staff["username"],
            )
            for item in payload.items:
                await db.execute(
                    """INSERT INTO purchase_order_items
                       (po_item_id, po_id, sku_id, quantity_ordered, quantity_received,
                        unit_cost_inr, line_status)
                       VALUES ($1,$2,$3,$4,0,$5,'open')""",
                    _po_item_id(), po_id, item.sku_id, item.quantity_ordered, item.unit_cost_inr,
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Purchase order creation failed: {exc}")

    return await _fetch_po_with_items(db, po_id)


@router.post("/{po_id}/confirm")
async def confirm_po(
    po_id: str,
    db=Depends(get_db),
    staff=Depends(require_role(PO_WRITE_ROLES)),
):
    try:
        return await confirm_purchase_order(
            db,
            po_id,
            performed_by=staff["username"],
            actor_type="human",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/{po_id}/receive")
async def receive_po(
    po_id: str,
    payload: ReceivePurchaseOrderRequest,
    db=Depends(get_db),
    staff=Depends(require_role(PO_WRITE_ROLES)),
):
    try:
        return await receive_purchase_order(
            db,
            po_id,
            [_pydantic_to_dict(item) for item in payload.items],
            performed_by=staff["username"],
            actor_type="human",
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
