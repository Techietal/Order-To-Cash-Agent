"""
O2C Agent v2.0 — Compliance & Audit API
ECOA report reads from customers table (credit_tier distribution).
Audit log is append-only PostgreSQL table.
"""
from fastapi import APIRouter, Depends
from typing import Optional
from database.postgres import get_db
from api.staff_deps import require_role

router = APIRouter()


@router.get("/audit-log")
async def audit_log(
    order_id: Optional[str] = None,
    actor_type: Optional[str] = None,   # 'human' | 'ai_agent' — enables Human Action Log filter
    actor_username: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "controller"])),
):
    """Immutable SOX-compliant audit log — append-only, RLS-protected.

    Supports actor_type='human' filter so the Human Action Log page can display
    only staff decisions, separated from the AI agent pipeline events.
    """
    conditions = ["1=1"]
    params = []

    if order_id:
        params.append(order_id)
        conditions.append(f"order_id = ${len(params)}")

    if actor_type:
        params.append(actor_type)
        conditions.append(f"actor_type = ${len(params)}")

    if actor_username:
        params.append(actor_username)
        conditions.append(f"actor_username = ${len(params)}")

    where_clause = " AND ".join(conditions)
    params.extend([limit, offset])
    query = (
        f"SELECT * FROM audit_log WHERE {where_clause} "
        f"ORDER BY created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}"
    )
    rows = await db.fetch(query, *params)
    return {"audit_log": [dict(r) for r in rows], "total": len(rows)}


@router.get("/ecoa-report")
async def ecoa_report(
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "controller"])),
):
    """
    ECOA distribution report — credit tier breakdown across all customers.
    Uses customers table (credit_tier) instead of non-existent credit_decisions table.
    """
    rows = await db.fetch(
        """SELECT credit_tier as credit_risk_class, COUNT(*) as count
           FROM customers
           GROUP BY credit_tier
           ORDER BY credit_tier"""
    )
    # Also aggregate fraud verdicts for bias analysis
    fraud_dist = await db.fetch(
        """SELECT fraud_verdict as credit_risk_class, COUNT(*) as count
           FROM fraud_records
           GROUP BY fraud_verdict
           ORDER BY fraud_verdict"""
    )
    return {
        "ecoa_distribution": [dict(r) for r in rows],
        "fraud_verdict_distribution": [dict(r) for r in fraud_dist],
    }


@router.get("/stats")
async def compliance_stats(
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "controller"])),
):
    """Quick compliance health stats."""
    audit_count = await db.fetchval("SELECT COUNT(*) FROM audit_log") or 0
    human_count = await db.fetchval("SELECT COUNT(*) FROM audit_log WHERE actor_type='human'") or 0
    hitl_open = await db.fetchval(
        "SELECT COUNT(*) FROM orders WHERE hitl_required=TRUE AND (hitl_resolved_by='' OR hitl_resolved_by IS NULL)"
    ) or 0
    fraud_flagged = await db.fetchval(
        "SELECT COUNT(*) FROM fraud_records WHERE fraud_verdict='FRAUD'"
    ) or 0
    return {
        "audit_entries": int(audit_count),
        "human_actions": int(human_count),
        "hitl_open": int(hitl_open),
        "fraud_flagged": int(fraud_flagged),
        "policy_rules_active": 8,
    }
