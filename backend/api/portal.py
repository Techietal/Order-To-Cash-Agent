"""
O2C Agent v2.0 — Admin Portal Quick-View API
Provides fast read-only endpoints for the admin dashboard portal view.
"""
from fastapi import APIRouter, Depends, HTTPException
from database.postgres import get_db
from api.staff_deps import require_role

router = APIRouter()

LEGACY_PORTAL_ROLES = ["admin", "controller"]


@router.get("/{customer_id}/invoices")
async def portal_invoices(customer_id: str, db=Depends(get_db), staff=Depends(require_role(LEGACY_PORTAL_ROLES))):
    """Last 20 invoices for a customer — used by admin portal customer detail view."""
    rows = await db.fetch(
        """SELECT invoice_id, invoice_date, due_date, total_amount_inr,
                  payment_status, balance_due_inr, days_overdue
           FROM invoices
           WHERE customer_id = $1
           ORDER BY invoice_date DESC
           LIMIT 20""",
        customer_id
    )
    return {"invoices": [dict(r) for r in rows]}


@router.get("/{customer_id}/orders")
async def portal_orders(customer_id: str, db=Depends(get_db), staff=Depends(require_role(LEGACY_PORTAL_ROLES))):
    """Last 20 orders for a customer — used by admin portal customer detail view."""
    rows = await db.fetch(
        """SELECT order_id, order_date, total_amount_inr, status,
                  sku_id, quantity, channel, fraud_score
           FROM orders
           WHERE customer_id = $1
           ORDER BY order_date DESC
           LIMIT 20""",
        customer_id
    )
    return {"orders": [dict(r) for r in rows]}


@router.get("/{customer_id}/summary")
async def portal_customer_summary(customer_id: str, db=Depends(get_db), staff=Depends(require_role(LEGACY_PORTAL_ROLES))):
    """Full customer summary: profile + AR stats + credit info."""
    customer = await db.fetchrow(
        "SELECT * FROM customers WHERE customer_id = $1",
        customer_id
    )
    if not customer:
        raise HTTPException(404, f"Customer {customer_id} not found")

    customer = dict(customer)

    # AR stats
    ar = await db.fetchrow(
        """SELECT
               COUNT(*) as invoice_count,
               COALESCE(SUM(total_amount_inr), 0) as total_billed,
               COALESCE(SUM(balance_due_inr), 0) as total_outstanding,
               COALESCE(MAX(days_overdue), 0) as max_days_overdue
           FROM invoices
           WHERE customer_id = $1""",
        customer_id
    )

    return {
        "customer":    customer,
        "ar_summary":  dict(ar) if ar else {},
    }
