from fastapi import APIRouter, Depends, HTTPException
from database.postgres import get_db
from api.staff_deps import require_role

router = APIRouter()

INVOICE_READ_ROLES = ["admin", "dispute_manager"]

@router.get("")
async def list_invoices(status: str = None, customer_id: str = None, limit: int = 50, offset: int = 0, db=Depends(get_db), staff=Depends(require_role(INVOICE_READ_ROLES))):
    q = "SELECT * FROM invoices WHERE 1=1"
    params = []
    if status: params.append(status); q += f" AND payment_status = ${len(params)}"
    if customer_id: params.append(customer_id); q += f" AND customer_id = ${len(params)}"
    params.extend([limit, offset]); q += f" ORDER BY created_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}"
    rows = await db.fetch(q, *params)
    return {"invoices": [dict(r) for r in rows]}

@router.get("/stats/summary")
async def invoice_summary(db=Depends(get_db), staff=Depends(require_role(INVOICE_READ_ROLES))):
    total = await db.fetchval("SELECT COUNT(*) FROM invoices")
    overdue = await db.fetchval("SELECT COUNT(*) FROM invoices WHERE payment_status = 'overdue'")
    total_outstanding = await db.fetchval("SELECT COALESCE(SUM(balance_due_inr),0) FROM invoices WHERE payment_status != 'paid'") or 0
    return {"total": total, "overdue": overdue, "total_outstanding_inr": float(total_outstanding)}

@router.get("/{invoice_id}")
async def get_invoice(invoice_id: str, db=Depends(get_db), staff=Depends(require_role(INVOICE_READ_ROLES))):
    row = await db.fetchrow("SELECT * FROM invoices WHERE invoice_id = $1", invoice_id)
    if not row: raise HTTPException(404, "Invoice not found")
    return dict(row)
