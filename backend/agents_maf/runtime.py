"""Shared runtime for the MAF agents (Disputes, Cash Application, Credit, KYC).

Provides a single generic driver so each domain agent is a thin wrapper:
  * ``start_run`` / ``finish_run``  — register and update an ``agent_runs`` row.
  * ``log_hitl``                    — uniform HITL audit_log sentinel.
  * ``hitl_since``                  — detect whether HITL fired during a run.
  * ``drive_agent`` / ``resume_run``— run the MAF agent loop and persist status.

HITL detection is decoupled from MAF internals: every domain's ``escalate_to_hitl``
tool writes an audit_log row whose ``details->>'entity_id'`` matches the run, so a
post-run query reliably tells us whether to pause.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Optional

from database.postgres import get_pool
from agents_maf.llm import run_agent_with_fallback

logger = logging.getLogger(__name__)


async def _get_db():
    pool = await get_pool()
    return pool.acquire()


async def log_hitl(
    *,
    agent_name: str,
    event_type: str,
    entity_id: str,
    customer_id: Optional[str],
    reason: str,
    suggested_action: str = "",
) -> dict:
    """Write a HITL escalation sentinel to audit_log. Returned by escalate tools."""
    details = json.dumps({
        "entity_id": entity_id,
        "reason": reason,
        "suggested_action": suggested_action,
    })
    async with await _get_db() as db:
        try:
            await db.execute(
                """INSERT INTO audit_log
                   (event_type, agent_name, customer_id, action, details,
                    actor_type, actor_username, actor_role)
                   VALUES ($1, $2, $3, 'escalate_to_hitl', $4::jsonb,
                           'ai_agent', $2, 'ai')""",
                event_type, agent_name, customer_id, details,
            )
        except Exception as exc:  # noqa: BLE001 — never let audit failure break a tool
            logger.warning("HITL audit insert failed: %s", exc)
    return {
        "escalated": True,
        "reason": reason,
        "suggested_action": suggested_action,
        "_hitl_required": True,
    }


async def start_run(
    *,
    agent_name: str,
    entity_type: str,
    entity_id: str,
    customer_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
) -> tuple[str, datetime]:
    """Insert a fresh agent_runs row; return (thread_id, started_at)."""
    thread_id = f"{entity_type}-{entity_id}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.utcnow()
    async with await _get_db() as db:
        await db.execute(
            """INSERT INTO agent_runs
                   (thread_id, agent_name, entity_type, entity_id,
                    invoice_id, customer_id, status)
               VALUES ($1, $2, $3, $4, $5, $6, 'running')""",
            thread_id, agent_name, entity_type, entity_id, invoice_id, customer_id,
        )
    return thread_id, started_at


async def hitl_since(event_type: str, entity_id: str, since: datetime) -> Optional[dict]:
    """Return the HITL payload if escalate_to_hitl fired for this entity during the run."""
    async with await _get_db() as db:
        row = await db.fetchrow(
            """SELECT details FROM audit_log
               WHERE event_type = $1
                 AND created_at >= $2
                 AND details->>'entity_id' = $3
               ORDER BY created_at DESC
               LIMIT 1""",
            event_type, since, entity_id,
        )
    if not row:
        return None
    details = row["details"]
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (ValueError, TypeError):
            details = {"reason": "escalated"}
    return dict(details) if details else {"reason": "escalated"}


async def finish_run(
    thread_id: str,
    status: str,
    summary: str,
    *,
    hitl: Optional[dict] = None,
    decision: Optional[dict] = None,
    resumed: bool = False,
) -> None:
    """Update an agent_runs row with the terminal/paused state."""
    async with await _get_db() as db:
        await db.execute(
            """UPDATE agent_runs
                   SET status = $1,
                       last_summary = $2,
                       hitl_payload = COALESCE($3::jsonb, hitl_payload),
                       hitl_decision = COALESCE($4::jsonb, hitl_decision),
                       paused_at = CASE WHEN $1 = 'paused_hitl' THEN NOW() ELSE paused_at END,
                       resumed_at = CASE WHEN $5 THEN NOW() ELSE resumed_at END,
                       finished_at = CASE WHEN $1 = 'done' THEN NOW() ELSE finished_at END,
                       error = $6,
                       updated_at = NOW()
               WHERE thread_id = $7""",
            status,
            summary,
            json.dumps(hitl) if hitl is not None else None,
            json.dumps(decision) if decision is not None else None,
            resumed,
            summary if status == "error" else "",
            thread_id,
        )


async def drive_agent(
    *,
    agent_name: str,
    entity_type: str,
    entity_id: str,
    customer_id: Optional[str],
    build_agent: Callable[[bool], Any],
    prompt: str,
    hitl_event_type: str,
    invoice_id: Optional[str] = None,
) -> dict:
    """Register, run one agent loop (with model fallback), detect HITL, persist status."""
    thread_id, started_at = await start_run(
        agent_name=agent_name, entity_type=entity_type, entity_id=entity_id,
        customer_id=customer_id, invoice_id=invoice_id,
    )
    status, summary, hitl = "running", "", None
    try:
        response = await run_agent_with_fallback(build_agent, prompt)
        summary = (getattr(response, "text", None) or str(response))[:500]
        hitl = await hitl_since(hitl_event_type, entity_id, started_at)
        status = "paused_hitl" if hitl else "done"
    except Exception as exc:  # noqa: BLE001 — boundary: persist any failure
        logger.exception("%s agent failed for %s", agent_name, entity_id)
        status, summary = "error", str(exc)[:500]

    await finish_run(thread_id, status, summary, hitl=hitl)
    out = {"thread_id": thread_id, "entity_id": entity_id,
           "status": status, "summary": summary}
    if hitl:
        out["hitl"] = hitl
    return out


async def get_run(thread_id: str) -> Optional[dict]:
    async with await _get_db() as db:
        row = await db.fetchrow("SELECT * FROM agent_runs WHERE thread_id = $1", thread_id)
    return dict(row) if row else None


async def resume_run(
    *,
    thread_id: str,
    decision: dict,
    build_agent: Callable[[bool], Any],
    prompt: str,
) -> dict:
    """Resume a HITL-paused run with a human decision and finish it."""
    run = await get_run(thread_id)
    if not run:
        return {"thread_id": thread_id, "status": "error", "summary": "Run not found"}
    if run["status"] != "paused_hitl":
        return {"thread_id": thread_id, "status": "error",
                "summary": f"Run is '{run['status']}', not paused_hitl"}

    status, summary = "running", ""
    try:
        response = await run_agent_with_fallback(build_agent, prompt)
        summary = (getattr(response, "text", None) or str(response))[:500]
        status = "done"
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("Resume failed for %s", thread_id)
        status, summary = "error", str(exc)[:500]

    await finish_run(thread_id, status, summary, decision=decision, resumed=True)
    return {"thread_id": thread_id, "entity_id": run.get("entity_id"),
            "status": status, "summary": summary}


# ── Agent-to-agent chaining (handoffs) ────────────────────────────────────────

async def record_handoff(
    *,
    from_agent: str,
    to_agent: str,
    entity_type: str,
    entity_id: str,
    reason: str = "",
    payload: Optional[dict] = None,
) -> dict:
    """Queue a handoff so another agent picks up ``entity_id``. Returned by handoff tools."""
    from config import settings
    if not settings.agent_chain_enabled:
        return {"handoff": False, "reason": "chaining disabled"}
    async with await _get_db() as db:
        # Loop guard: cap total handoffs per entity so chains can't run away.
        prior = await db.fetchval(
            "SELECT COUNT(*) FROM agent_handoffs WHERE entity_id = $1", entity_id
        )
        if int(prior or 0) >= settings.agent_chain_max_depth:
            logger.warning("Handoff chain for %s hit max depth — dropping %s->%s",
                           entity_id, from_agent, to_agent)
            return {"handoff": False, "reason": "max chain depth reached"}
        await db.execute(
            """INSERT INTO agent_handoffs
                   (from_agent, to_agent, entity_type, entity_id, reason, payload, depth)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)""",
            from_agent, to_agent, entity_type, entity_id, reason,
            json.dumps(payload or {}), int(prior or 0) + 1,
        )
    logger.info("Handoff queued: %s -> %s for %s (%s)", from_agent, to_agent, entity_id, reason)
    return {"handoff": True, "to_agent": to_agent, "entity_id": entity_id, "reason": reason}


async def process_pending_handoffs(max_items: int = 5) -> int:
    """Run queued handoffs by dispatching to the target agent. Returns count processed."""
    from agents_maf.registry import dispatch_run, AGENT_RUN
    pool = await get_pool()
    async with pool.acquire() as db:
        rows = await db.fetch(
            "SELECT * FROM agent_handoffs WHERE status = 'pending' "
            "ORDER BY created_at LIMIT $1",
            max_items,
        )
    processed = 0
    for r in rows:
        key = r["to_agent"]
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                payload = {}
        new_status = "done"
        try:
            if key not in AGENT_RUN:
                new_status = "skipped"
                logger.warning("Handoff target '%s' unknown — skipping", key)
            else:
                await dispatch_run(key, r["entity_id"], **(payload or {}))
                processed += 1
        except Exception:  # noqa: BLE001
            logger.exception("Handoff dispatch failed for %s", key)
            new_status = "failed"

        async with pool.acquire() as db:
            await db.execute(
                "UPDATE agent_handoffs SET status = $1, processed_at = NOW() WHERE handoff_id = $2",
                new_status, r["handoff_id"],
            )
    return processed
