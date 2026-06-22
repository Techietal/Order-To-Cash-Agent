from fastapi import APIRouter, Depends
from typing import Optional
from database.postgres import get_db
from api.staff_deps import require_role

router = APIRouter()


@router.get("")
async def list_fraud(
    verdict: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "controller"])),
):
    q = "SELECT * FROM fraud_records WHERE 1=1"
    params = []
    if verdict:
        params.append(verdict)
        q += f" AND fraud_verdict = ${len(params)}"
    if customer_id:
        params.append(customer_id)
        q += f" AND customer_id = ${len(params)}"
    params.append(limit)
    q += f" ORDER BY detected_at DESC LIMIT ${len(params)}"
    rows = await db.fetch(q, *params)
    return {"fraud_records": [dict(r) for r in rows]}


@router.get("/stats")
async def fraud_stats(
    customer_id: Optional[str] = None,
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "controller"])),
):
    if customer_id:
        total = await db.fetchval(
            "SELECT COUNT(*) FROM fraud_records WHERE customer_id = $1", customer_id
        )
        flagged = await db.fetchval(
            "SELECT COUNT(*) FROM fraud_records WHERE fraud_verdict = 'FRAUD' AND customer_id = $1",
            customer_id,
        )
    else:
        total = await db.fetchval("SELECT COUNT(*) FROM fraud_records")
        flagged = await db.fetchval("SELECT COUNT(*) FROM fraud_records WHERE fraud_verdict = 'FRAUD'")
    return {"total_screened": total, "fraud_flagged": flagged, "clear": total - flagged}
