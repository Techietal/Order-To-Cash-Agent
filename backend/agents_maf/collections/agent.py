"""Collections Agent runner (MAF v1.9.0, Ollama Cloud).

Design note — agent vs. durable workflow
----------------------------------------
MAF 1.9 exposes the agent loop via ``client.as_agent(...).run(...)``. This module
drives that loop directly. Human-in-the-loop (HITL) is implemented at the
application layer rather than via MAF workflow checkpoints:

  * The ``escalate_to_hitl`` tool writes a ``COLLECTIONS_HITL`` row to ``audit_log``.
  * After a run we check for such a row written during this run; if present the
    run is marked ``paused_hitl`` and surfaced for human review.
  * ``resume_collections_agent`` re-runs the agent with the human decision injected,
    then marks the run ``done``.

The durable ``PostgresCheckpointStorage`` remains initialised at startup and is
available for a future migration to a fully checkpointed MAF workflow (it is not
required for the application-level HITL implemented here).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from config import settings
from database.postgres import get_pool
from agents_maf.llm import build_chat_client, run_agent_with_fallback
from agents_maf.collections.tools import COLLECTIONS_TOOLS
from agents_maf.collections.prompts import COLLECTIONS_SYSTEM
from agents_maf.collections.state import CollectionsState

logger = logging.getLogger(__name__)


def build_agent(use_fallback: bool = False):
    """Construct the Collections ChatAgent from the provider-driven client.

    Temperature (G6) is supplied via ``default_options`` — MAF treats temperature
    as a per-request chat option, not a client constructor argument.
    """
    client = build_chat_client(use_fallback)
    return client.as_agent(
        name="collections_agent",
        instructions=COLLECTIONS_SYSTEM.format(
            max_per_week=settings.dunning_max_contacts_per_week
        ),
        tools=COLLECTIONS_TOOLS,
        default_options={"temperature": settings.collections_agent_temperature},
    )


async def _load_context(invoice_id: str) -> CollectionsState:
    """Hydrate invoice + customer + segment + FDCPA headroom before the run."""
    pool = await get_pool()
    async with pool.acquire() as db:
        inv = await db.fetchrow(
            """SELECT i.*, c.company_name, c.contact_name, c.email AS customer_email,
                      c.payment_terms_days
               FROM invoices i
               JOIN customers c ON i.customer_id = c.customer_id
               WHERE i.invoice_id = $1""",
            invoice_id,
        )
    if not inv:
        raise ValueError(f"Invoice {invoice_id} not found")

    from agents_maf.collections.tools import predict_segment, count_weekly_contacts

    seg = await predict_segment(inv["customer_id"])
    wk = await count_weekly_contacts(inv["customer_id"])
    return CollectionsState(
        invoice_id=invoice_id,
        customer_id=inv["customer_id"],
        invoice=dict(inv),
        segment=seg.get("segment", "Standard"),
        tone=seg.get("tone", "firm"),
        days_overdue=int(inv.get("days_overdue") or 0),
        balance_due_inr=float(inv.get("balance_due_inr") or 0),
        fdcpa_remaining=wk.get("remaining", 0),
    )


async def _hitl_escalation_since(invoice_id: str, since: datetime) -> Optional[dict]:
    """Return the HITL payload if escalate_to_hitl fired during this run.

    Detected via the COLLECTIONS_HITL audit_log row the tool writes — this is
    decoupled from MAF's internal message structure and therefore robust.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """SELECT details FROM audit_log
               WHERE invoice_id = $1
                 AND event_type = 'COLLECTIONS_HITL'
                 AND created_at >= $2
               ORDER BY created_at DESC
               LIMIT 1""",
            invoice_id,
            since,
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


def _run_prompt(ctx: CollectionsState, extra: str = "") -> str:
    base = (
        f"Invoice {ctx.invoice_id} | "
        f"Customer {ctx.invoice.get('company_name', '?')} ({ctx.customer_id}) | "
        f"Segment {ctx.segment} | "
        f"\u20b9{ctx.balance_due_inr:,.0f} due | "
        f"{ctx.days_overdue} days overdue | "
        f"FDCPA contacts remaining this week: {ctx.fdcpa_remaining}. "
        f"Decide the next collections action and execute it using your tools."
    )
    return f"{base}\n\n{extra}".strip()


async def run_collections_agent(invoice_id: str, *, triggered_by: str = "api") -> dict:
    """Run the Collections Agent for one invoice. Returns a status summary dict."""
    thread_id = f"collections-{invoice_id}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.utcnow()
    pool = await get_pool()

    async with pool.acquire() as db:
        cust_id = await db.fetchval(
            "SELECT customer_id FROM invoices WHERE invoice_id = $1", invoice_id
        )
        await db.execute(
            """INSERT INTO agent_runs
                   (thread_id, agent_name, invoice_id, customer_id, status)
               VALUES ($1, 'collections_agent', $2, $3, 'running')""",
            thread_id, invoice_id, cust_id,
        )

    status = "running"
    summary = ""
    hitl: Optional[dict] = None
    try:
        ctx = await _load_context(invoice_id)
        response = await run_agent_with_fallback(build_agent, _run_prompt(ctx))
        summary = (getattr(response, "text", None) or str(response))[:500]

        hitl = await _hitl_escalation_since(invoice_id, started_at)
        status = "paused_hitl" if hitl else "done"
    except Exception as exc:  # noqa: BLE001 — boundary: persist any failure
        logger.exception("Collections agent failed for %s", invoice_id)
        status, summary = "error", str(exc)[:500]

    async with pool.acquire() as db:
        await db.execute(
            """UPDATE agent_runs
                   SET status = $1,
                       last_summary = $2,
                       hitl_payload = $3::jsonb,
                       paused_at = CASE WHEN $1 = 'paused_hitl' THEN NOW() ELSE paused_at END,
                       finished_at = CASE WHEN $1 = 'done' THEN NOW() ELSE finished_at END,
                       error = $4,
                       updated_at = NOW()
               WHERE thread_id = $5""",
            status,
            summary,
            json.dumps(hitl or {}),
            summary if status == "error" else "",
            thread_id,
        )

    result = {"thread_id": thread_id, "invoice_id": invoice_id,
              "status": status, "summary": summary}
    if hitl:
        result["hitl"] = hitl
    return result


async def resume_collections_agent(thread_id: str, decision: dict) -> dict:
    """Resume a HITL-paused run with a human decision and finish it."""
    pool = await get_pool()
    async with pool.acquire() as db:
        run = await db.fetchrow(
            "SELECT invoice_id, status FROM agent_runs WHERE thread_id = $1", thread_id
        )
    if not run:
        return {"thread_id": thread_id, "status": "error", "summary": "Run not found"}
    if run["status"] != "paused_hitl":
        return {"thread_id": thread_id, "status": "error",
                "summary": f"Run is '{run['status']}', not paused_hitl"}

    invoice_id = run["invoice_id"]
    status = "running"
    summary = ""
    try:
        ctx = await _load_context(invoice_id)
        decision_text = json.dumps(decision, ensure_ascii=False)
        extra = (
            "A human collections controller has reviewed the earlier escalation "
            f"and provided this decision: {decision_text}. "
            "Carry out that decision now using your tools, respecting FDCPA limits. "
            "Do not escalate again unless a new blocker appears."
        )
        response = await run_agent_with_fallback(build_agent, _run_prompt(ctx, extra))
        summary = (getattr(response, "text", None) or str(response))[:500]
        status = "done"
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("Resume failed for %s", thread_id)
        status, summary = "error", str(exc)[:500]

    async with pool.acquire() as db:
        await db.execute(
            """UPDATE agent_runs
                   SET status = $1,
                       resumed_at = NOW(),
                       finished_at = CASE WHEN $1 = 'done' THEN NOW() ELSE finished_at END,
                       hitl_decision = $2::jsonb,
                       last_summary = $3,
                       error = $4,
                       updated_at = NOW()
               WHERE thread_id = $5""",
            status,
            json.dumps(decision),
            summary,
            summary if status == "error" else "",
            thread_id,
        )
    return {"thread_id": thread_id, "invoice_id": invoice_id,
            "status": status, "summary": summary}
