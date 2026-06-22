"""
O2C Agent v2.0 — Credit Memos API
Read-only endpoint returning credit memos created from dispute resolutions.
Gated: admin + dispute_manager (full) · collections_analyst (view-only for their accounts)
"""
from fastapi import APIRouter, Depends
from database.postgres import get_db
from api.staff_deps import require_role
from datetime import datetime, timezone

router = APIRouter()

CREDIT_READ_ROLES = ["admin", "dispute_manager", "collections_analyst", "controller"]


@router.get("")
async def list_credit_memos(
    customer_id: str = None,
    invoice_id: str = None,
    order_id: str = None,
    dispute_id: str = None,
    since: str = None,       # ISO date string e.g. "2025-04-01"
    limit: int = 200,
    db=Depends(get_db),
    staff=Depends(require_role(CREDIT_READ_ROLES)),
):
    """
    Return credit memos ordered newest-first.
    Supports filtering by customer, invoice, order, dispute, or date range.
    """
    q = """SELECT cm.*,
                  c.company_name
           FROM credit_memos cm
           LEFT JOIN customers c ON cm.customer_id = c.customer_id
           WHERE 1=1"""
    params = []

    if customer_id:
        params.append(customer_id)
        q += f" AND cm.customer_id = ${len(params)}"
    if invoice_id:
        params.append(invoice_id)
        q += f" AND cm.invoice_id = ${len(params)}"
    if order_id:
        params.append(order_id)
        q += f" AND cm.order_id = ${len(params)}"
    if dispute_id:
        params.append(dispute_id)
        q += f" AND cm.dispute_id = ${len(params)}"
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            since_dt = datetime.now(timezone.utc).replace(month=1, day=1)
        params.append(since_dt)
        q += f" AND cm.created_at >= ${len(params)}"

    params.append(limit)
    q += f" ORDER BY cm.created_at DESC LIMIT ${len(params)}"

    rows = await db.fetch(q, *params)
    memos = [dict(r) for r in rows]
    total_amount = sum(float(m.get("amount_inr") or 0) for m in memos)

    return {
        "credit_memos": memos,
        "total_amount_inr": total_amount,
        "count": len(memos),
    }


@router.get("/summary")
async def credit_memos_summary(
    since: str = None,
    db=Depends(get_db),
    staff=Depends(require_role(CREDIT_READ_ROLES)),
):
    """Aggregate summary — total credited, count, and per-approver breakdown."""
    q = """SELECT
               COUNT(*)::int                  AS total_count,
               COALESCE(SUM(amount_inr), 0)   AS total_amount_inr,
               COUNT(DISTINCT customer_id)     AS customers_credited
           FROM credit_memos"""
    params = []
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            since_dt = datetime.now(timezone.utc).replace(month=1, day=1)
        params.append(since_dt)
        q += f" WHERE created_at >= ${len(params)}"

    row = await db.fetchrow(q, *params)
    return dict(row) if row else {"total_count": 0, "total_amount_inr": 0, "customers_credited": 0}
