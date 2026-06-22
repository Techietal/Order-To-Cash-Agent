"""Generic agent control plane — /api/agents.

One uniform surface to run, resume, and inspect the MAF agents
(Disputes, Cash Application, Credit, KYC). Collections keeps its own
/api/collections/agent/* routes; this router covers the rest.

Each agent runs in-process via FastAPI BackgroundTasks (no Celery).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from database.postgres import get_db
from api.staff_deps import require_role

router = APIRouter()
logger = logging.getLogger(__name__)

AGENT_ROLES = ["admin", "controller", "collections_analyst", "dispute_manager"]

# domain -> (module path, allowed extra body keys passed to run())
_REGISTRY = {
    "disputes": "agents_maf.disputes.agent",
    "cash": "agents_maf.cash_application.agent",
    "credit": "agents_maf.credit.agent",
    "kyc": "agents_maf.kyc.agent",
}

_AGENT_NAME = {
    "disputes": "disputes_agent",
    "cash": "cash_application_agent",
    "credit": "credit_agent",
    "kyc": "kyc_agent",
}


def _module(domain: str):
    import importlib
    path = _REGISTRY.get(domain)
    if not path:
        raise HTTPException(404, f"Unknown agent domain '{domain}'")
    return importlib.import_module(path)


class RunRequest(BaseModel):
    entity_id: str                       # dispute_id | invoice_id | customer_id | kyc_id
    order_amount_inr: Optional[float] = None
    remittance_amount: Optional[float] = None
    remittance_text: Optional[str] = None
    order_id: Optional[str] = None


class ResumeRequest(BaseModel):
    thread_id: str
    decision: str = "continue"
    notes: str = ""


async def _run_bg(domain: str, kwargs: dict):
    try:
        mod = _module(domain)
        await mod.run(**kwargs)
    except Exception as exc:  # noqa: BLE001 — already persisted to agent_runs
        logger.exception("Background %s agent failed: %s", domain, exc)


@router.post("/{domain}/run")
async def run_agent(
    domain: str,
    payload: RunRequest,
    background: BackgroundTasks,
    staff=Depends(require_role(AGENT_ROLES)),
):
    """Kick off an agent for one entity; returns immediately (poll /runs)."""
    _module(domain)  # validates domain
    kwargs = {k: v for k, v in {
        "order_amount_inr": payload.order_amount_inr,
        "remittance_amount": payload.remittance_amount,
        "remittance_text": payload.remittance_text,
        "order_id": payload.order_id,
    }.items() if v is not None}

    # Map the generic entity_id to the domain's first positional arg name.
    arg_name = {"disputes": "dispute_id", "cash": "invoice_id",
                "credit": "customer_id", "kyc": "kyc_id"}[domain]
    kwargs[arg_name] = payload.entity_id
    background.add_task(_run_bg, domain, kwargs)
    return {"status": "accepted", "domain": domain, "entity_id": payload.entity_id}


@router.post("/{domain}/resume")
async def resume_agent(
    domain: str,
    payload: ResumeRequest,
    staff=Depends(require_role(AGENT_ROLES)),
):
    """Resume a HITL-paused run with a human decision."""
    mod = _module(domain)
    result = await mod.resume(
        payload.thread_id, {"decision": payload.decision, "notes": payload.notes}
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("summary", "resume failed"))
    return result


@router.get("/runs")
async def list_runs(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_db),
    staff=Depends(require_role(AGENT_ROLES)),
):
    """List agent runs across all non-collections agents, with optional filters."""
    q = "SELECT * FROM agent_runs WHERE 1=1"
    params: list = []
    if domain:
        params.append(_AGENT_NAME.get(domain, domain))
        q += f" AND agent_name = ${len(params)}"
    if status:
        params.append(status)
        q += f" AND status = ${len(params)}"
    params.append(limit)
    q += f" ORDER BY started_at DESC LIMIT ${len(params)}"
    rows = await db.fetch(q, *params)
    return {"runs": [dict(r) for r in rows]}


@router.get("/runs/{run_id}")
async def get_run_by_id(
    run_id: str,
    db=Depends(get_db),
    staff=Depends(require_role(AGENT_ROLES)),
):
    row = await db.fetchrow("SELECT * FROM agent_runs WHERE run_id = $1", run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    return dict(row)


@router.get("/handoffs")
async def list_handoffs(
    status: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_db),
    staff=Depends(require_role(AGENT_ROLES)),
):
    """List agent-to-agent handoffs (the chaining audit trail)."""
    q = "SELECT * FROM agent_handoffs WHERE 1=1"
    params: list = []
    if status:
        params.append(status)
        q += f" AND status = ${len(params)}"
    params.append(limit)
    q += f" ORDER BY created_at DESC LIMIT ${len(params)}"
    rows = await db.fetch(q, *params)
    return {"handoffs": [dict(r) for r in rows]}
