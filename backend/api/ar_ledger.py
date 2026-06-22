"""
O2C Agent v2.0 — AR Ledger API
Includes aging update endpoint and live aging summary.
"""
from fastapi import APIRouter, Depends, HTTPException
from database.postgres import get_db
from api.staff_deps import require_role

router = APIRouter()

AR_READ_ROLES = ["admin", "dispute_manager", "collections_analyst", "controller"]
AR_WRITE_ROLES = ["admin", "controller"]


@router.get("")
async def list_ar(
    aging_bucket: str = None,
    customer_id: str = None,
    limit: int = 100,
    db=Depends(get_db),
    staff=Depends(require_role(AR_READ_ROLES)),
):
    """List AR ledger entries with optional filters."""
    q = """SELECT a.*, c.company_name, c.email as customer_email,
                  i.payment_terms_days, i.invoice_date, i.due_date as invoice_due_date
           FROM ar_ledger a
           JOIN customers c ON a.customer_id = c.customer_id
           LEFT JOIN invoices i ON a.invoice_id = i.invoice_id
           WHERE 1=1"""
    params = []
    if aging_bucket:
        params.append(aging_bucket)
        q += f" AND a.aging_bucket = ${len(params)}"
    if customer_id:
        params.append(customer_id)
        q += f" AND a.customer_id = ${len(params)}"
    params.append(limit)
    q += f" ORDER BY a.days_overdue DESC NULLS LAST LIMIT ${len(params)}"
    rows = await db.fetch(q, *params)
    return {"ar_entries": [dict(r) for r in rows], "total": len(rows)}


@router.get("/aging-summary")
async def aging_summary(
    db=Depends(get_db),
    staff=Depends(require_role(AR_READ_ROLES)),
):
    """Aging bucket summary — computed from actual days_overdue in AR ledger."""
    rows = await db.fetch(
        """SELECT aging_bucket,
                  COUNT(*) as count,
                  SUM(outstanding_balance_inr) as total_outstanding,
                  AVG(days_overdue) as avg_days_overdue
           FROM ar_ledger
           WHERE payment_status != 'paid'
           GROUP BY aging_bucket
           ORDER BY aging_bucket"""
    )
    return {"aging": [dict(r) for r in rows]}


@router.post("/refresh-aging")
async def refresh_aging(
    db=Depends(get_db),
    staff=Depends(require_role(AR_WRITE_ROLES)),
):
    """
    Agent 7 support — Refresh days_overdue and aging_bucket for all open AR entries.
    Called by the payment monitor scheduler every 15 min, or on demand.
    """
    result = await db.execute(
        """UPDATE ar_ledger
           SET days_overdue = GREATEST(0, EXTRACT(DAY FROM NOW() - (
                   SELECT due_date FROM invoices i WHERE i.invoice_id = ar_ledger.invoice_id
               ))::int),
               aging_bucket = CASE
                   WHEN EXTRACT(DAY FROM NOW() - (
                       SELECT due_date FROM invoices i WHERE i.invoice_id = ar_ledger.invoice_id
                   )) <= 0 THEN 'current'
                   WHEN EXTRACT(DAY FROM NOW() - (
                       SELECT due_date FROM invoices i WHERE i.invoice_id = ar_ledger.invoice_id
                   )) <= 30 THEN '0-30'
                   WHEN EXTRACT(DAY FROM NOW() - (
                       SELECT due_date FROM invoices i WHERE i.invoice_id = ar_ledger.invoice_id
                   )) <= 60 THEN '31-60'
                   WHEN EXTRACT(DAY FROM NOW() - (
                       SELECT due_date FROM invoices i WHERE i.invoice_id = ar_ledger.invoice_id
                   )) <= 90 THEN '61-90'
                   ELSE '90+'
               END,
               payment_status = CASE
                   WHEN payment_status = 'paid' THEN 'paid'
                   WHEN EXTRACT(DAY FROM NOW() - (
                       SELECT due_date FROM invoices i WHERE i.invoice_id = ar_ledger.invoice_id
                   )) > 0 THEN 'overdue'
                   ELSE payment_status
               END
           WHERE payment_status != 'paid'
             AND invoice_id IN (SELECT invoice_id FROM invoices WHERE due_date IS NOT NULL)"""
    )
    updated = int(result.split(" ")[-1]) if result else 0
    return {"refreshed": updated, "message": f"Aging recalculated for {updated} open AR entries"}


@router.get("/outstanding/{customer_id}")
async def customer_outstanding(customer_id: str, db=Depends(get_db), staff=Depends(require_role(AR_READ_ROLES))):
    """Get all outstanding invoices for a customer (used by portal)."""
    rows = await db.fetch(
        """SELECT a.ar_id, a.invoice_id, a.amount_inr, a.outstanding_balance_inr,
                  a.aging_bucket, a.days_overdue, a.payment_status,
                  i.invoice_date, i.due_date, i.payment_terms_days
           FROM ar_ledger a
           LEFT JOIN invoices i ON a.invoice_id = i.invoice_id
           WHERE a.customer_id = $1
             AND a.payment_status != 'paid'
             AND a.outstanding_balance_inr > 0
           ORDER BY a.days_overdue DESC""",
        customer_id
    )
    total_outstanding = sum(float(r["outstanding_balance_inr"] or 0) for r in rows)
    return {
        "customer_id": customer_id,
        "outstanding_entries": [dict(r) for r in rows],
        "total_outstanding_inr": total_outstanding,
    }


# ── Manual Payment (Section 5) ───────────────────────────────────────────────
from pydantic import BaseModel

class ManualPaymentPayload(BaseModel):
    amount_received: float
    note: str = ""


MANUAL_PAY_ROLES = ["admin", "collections_analyst"]


@router.post("/{ar_id}/mark-received")
async def mark_payment_received(
    ar_id: str,
    payload: ManualPaymentPayload,
    db=Depends(get_db),
    staff=Depends(require_role(MANUAL_PAY_ROLES)),
):
    """
    Manually record a payment against an AR entry.
    - amount_received can be less than the outstanding balance (partial payment).
    - Updates outstanding_balance_inr; sets payment_status='paid' when fully settled.
    - Every call writes an audit_log row with actor_type='human' and JWT identity.
    Gated: admin + collections_analyst only.
    """
    import uuid
    from datetime import datetime

    # Fetch current AR entry
    ar = await db.fetchrow(
        "SELECT * FROM ar_ledger WHERE ar_id = $1",
        ar_id
    )
    if not ar:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"AR entry {ar_id} not found")

    current_balance = float(ar["outstanding_balance_inr"] or 0)
    if payload.amount_received <= 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="amount_received must be > 0")

    new_balance = max(0.0, current_balance - payload.amount_received)
    new_status  = "paid" if new_balance == 0 else ar["payment_status"]

    # Update AR ledger
    await db.execute(
        """UPDATE ar_ledger
           SET outstanding_balance_inr = $1,
               payment_status          = $2
           WHERE ar_id = $3""",
        new_balance, new_status, ar_id
    )

    # Also update invoice balance_due_inr if invoice exists
    if ar.get("invoice_id"):
        await db.execute(
            """UPDATE invoices
               SET balance_due_inr = GREATEST(0, balance_due_inr - $1),
                   payment_status  = CASE WHEN (balance_due_inr - $1) <= 0 THEN 'paid' ELSE payment_status END
               WHERE invoice_id = $2""",
            payload.amount_received, ar["invoice_id"]
        )

    # Audit log — human action
    import json
    details_json = json.dumps({
        "ar_id":            ar_id,
        "invoice_id":       ar.get("invoice_id"),
        "amount_received":  payload.amount_received,
        "balance_before":   current_balance,
        "balance_after":    new_balance,
        "note":             payload.note,
    })
    await db.execute(
        """INSERT INTO audit_log
           (event_type, agent_name, customer_id, invoice_id,
            action, details, actor_type, actor_username, actor_role)
           VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)""",
        "payment_received",
        "manual_payment",
        ar.get("customer_id"),
        ar.get("invoice_id"),
        f"Manual payment: ₹{payload.amount_received:,.0f} received",
        details_json,
        "human",
        staff["username"],
        staff["role"],
    )

    # ── Credit History entry — insert into credit_memos with source='ar_ledger_manual' ──
    # This makes every "Mark as Received" (partial or full) visible in Credit History
    # with source label 'AR Ledger (Manual)' so admin/collections can track all adjustments.
    import datetime as _dt
    memo_id = f"MEMO-AR-{_dt.datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:22]}"
    order_id_for_memo = None
    if ar.get("invoice_id"):
        row = await db.fetchrow("SELECT order_id FROM invoices WHERE invoice_id = $1", ar.get("invoice_id"))
        order_id_for_memo = row["order_id"] if row else None

    try:
        await db.execute(
            """INSERT INTO credit_memos
               (memo_id, order_id, invoice_id, customer_id,
                amount_inr, reason, approved_by, approved_by_role,
                balance_before_inr, balance_after_inr,
                source, payment_ref)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            memo_id,
            order_id_for_memo,
            ar.get("invoice_id"),
            ar.get("customer_id"),
            payload.amount_received,
            payload.note or f"Manual payment received — AR {ar_id}",
            staff["username"],
            staff["role"],
            current_balance,
            new_balance,
            "ar_ledger_manual",
            payload.note or None,
        )
    except Exception as e:
        # Non-fatal — audit log already written above
        import logging
        logging.getLogger(__name__).error(f"credit_memo insert failed (non-critical): {e}")

    return {
        "ar_id":           ar_id,
        "invoice_id":      ar.get("invoice_id"),
        "customer_id":     ar.get("customer_id"),
        "amount_received": payload.amount_received,
        "balance_before":  current_balance,
        "balance_after":   new_balance,
        "payment_status":  new_status,
        "memo_id":         memo_id,
        "recorded_by":     staff["username"],
        "recorded_by_role": staff["role"],
        "message": f"Payment of ₹{payload.amount_received:,.0f} recorded. {'Invoice fully paid.' if new_status == 'paid' else f'₹{new_balance:,.0f} still outstanding.'}"
    }

