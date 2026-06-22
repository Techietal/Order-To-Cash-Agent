"""
MAF tool library for the Collections Agent.

Each tool wraps an existing service/utility. The @tool decorator from MAF v1.1
produces FunctionTool objects with JSON-schema auto-derived from Annotated params.

FDCPA RULE-007 guard is enforced in send_dunning_email:
  - Checks count_weekly_contacts before sending
  - Blocks and returns {sent: False, blocked_reason: ...} if over the limit

All write tools log to audit_log with actor_type='ai_agent'.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from agent_framework import tool

from config import settings

logger = logging.getLogger(__name__)


async def _get_db():
    """Acquire an asyncpg connection from the pool."""
    from database.postgres import get_pool
    pool = await get_pool()
    return pool.acquire()


# ── READ tools ────────────────────────────────────────────────────────────────

@tool(name="get_dunning_history", description="Prior dunning contacts for an invoice.")
async def get_dunning_history(
    invoice_id: Annotated[str, "Invoice ID e.g. INV-20250101-001"],
) -> dict:
    """Return all previous dunning log entries for the given invoice."""
    async with await _get_db() as db:
        rows = await db.fetch(
            """SELECT dunning_id, dunning_level, channel, sent_at, account_segment,
                      promise_to_pay, promise_kept, groq_generated
               FROM dunning_log
               WHERE invoice_id = $1
               ORDER BY sent_at DESC""",
            invoice_id,
        )
    return {"history": [dict(r) for r in rows], "count": len(rows)}


@tool(name="predict_segment", description="Customer collection segment via k-means (Premium/Standard/At-Risk/Problem).")
async def predict_segment(
    customer_id: Annotated[str, "Customer ID e.g. CUST-001"],
) -> dict:
    """Return the k-means segment and tone recommendation for a customer."""
    from ml.model_placeholders import predict_customer_segment
    async with await _get_db() as db:
        row = await db.fetchrow("SELECT * FROM customers WHERE customer_id = $1", customer_id)
    if not row:
        return {"segment": "Standard", "tone": "firm"}
    result = predict_customer_segment(dict(row))
    tone_map = {
        "Premium":  "gentle_reminder",
        "Standard": "firm",
        "At-Risk":  "urgent",
        "Problem":  "legal_warning",
    }
    result["tone"] = tone_map.get(result.get("segment", "Standard"), "firm")
    return result


@tool(name="count_weekly_contacts", description="FDCPA weekly contact count — returns can_contact flag.")
async def count_weekly_contacts(
    customer_id: Annotated[str, "Customer ID"],
) -> dict:
    """Count dunning contacts in the past 7 days for FDCPA RULE-007 compliance."""
    since = datetime.utcnow() - timedelta(days=7)
    async with await _get_db() as db:
        n = await db.fetchval(
            "SELECT COUNT(*) FROM dunning_log WHERE customer_id = $1 AND sent_at >= $2",
            customer_id,
            since,
        )
    limit = settings.dunning_max_contacts_per_week
    n = int(n or 0)
    return {
        "contacts_this_week": n,
        "max_per_week": limit,
        "remaining": max(0, limit - n),
        "can_contact": n < limit,
    }


# ── WRITE tools ───────────────────────────────────────────────────────────────

@tool(name="draft_dunning_email", description="Draft (but do not send) a segment-toned dunning email via Groq.")
async def draft_dunning_email(
    customer_name: Annotated[str, "Company name"],
    invoice_id: Annotated[str, "Invoice ID"],
    amount_inr: Annotated[float, "Amount due in INR"],
    days_overdue: Annotated[int, "Days the invoice is overdue"],
    contact_name: Annotated[str, "Contact person name"] = "",
    payment_terms: Annotated[int, "Net payment terms in days"] = 30,
    tone: Annotated[str, "Tone: gentle_reminder | firm | urgent | legal_warning"] = "firm",
) -> dict:
    """Generate a personalised dunning email draft using Groq LLaMA 3.3 70B."""
    from ml.groq_client import generate_dunning_email
    result = generate_dunning_email(
        customer_name=customer_name,
        invoice_id=invoice_id,
        amount_inr=amount_inr,
        days_overdue=days_overdue,
        payment_terms=payment_terms,
        contact_name=contact_name,
        tone=tone,
    )
    return {
        "subject": result.get("subject", ""),
        "body": result.get("body", ""),
        "tone": result.get("tone", tone),
    }


@tool(name="send_dunning_email", description="Send + log a dunning email. FDCPA-guarded: blocked if weekly limit exceeded.")
async def send_dunning_email(
    to_email: Annotated[str, "Recipient email address"],
    subject: Annotated[str, "Email subject"],
    body: Annotated[str, "Email body"],
    invoice_id: Annotated[str, "Invoice ID"],
    customer_id: Annotated[str, "Customer ID"],
    segment: Annotated[str, "Customer segment (Premium/Standard/At-Risk/Problem)"] = "Standard",
    days_overdue: Annotated[int, "Days overdue"] = 0,
) -> dict:
    """Send a dunning email via Gmail SMTP and log to dunning_log + audit_log.

    Returns {sent: False, blocked_reason: ...} if FDCPA weekly limit is exceeded.
    """
    # ── FDCPA RULE-007 guard ───────────────────────────────────────────────────
    fdcpa = await count_weekly_contacts(customer_id)
    if not fdcpa["can_contact"]:
        return {
            "sent": False,
            "blocked_reason": (
                f"FDCPA RULE-007: already contacted {fdcpa['contacts_this_week']}/"
                f"{fdcpa['max_per_week']} times this week"
            ),
        }

    # ── Send via SMTP ──────────────────────────────────────────────────────────
    from api.customer_portal import send_email
    sent, err = False, None
    try:
        send_email(to=to_email, subject=subject, body=body)
        sent = True
    except Exception as exc:
        err = str(exc)
        logger.error(f"Collections agent SMTP send failed for {invoice_id}: {exc}")

    # ── Persist to dunning_log + audit_log ────────────────────────────────────
    dunning_id = f"DUNN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    level = 1 if days_overdue <= 15 else (2 if days_overdue <= 30 else 3)
    async with await _get_db() as db:
        try:
            await db.execute(
                """INSERT INTO dunning_log
                   (dunning_id, customer_id, invoice_id, dunning_level, channel,
                    message_subject, message_body_preview, sent_at, groq_generated, account_segment)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,TRUE,$9)""",
                dunning_id, customer_id, invoice_id, f"LEVEL_{level}",
                "email" if sent else "draft",
                subject, body[:500], datetime.utcnow(), segment,
            )
        except Exception as exc:
            logger.warning(f"dunning_log insert failed: {exc}")

        audit_detail = json.dumps({
            "dunning_id": dunning_id,
            "sent": sent,
            "error": err or "",
        })
        try:
            await db.execute(
                """INSERT INTO audit_log
                   (event_type, agent_name, customer_id, invoice_id, action,
                    details, actor_type, actor_username, actor_role)
                   VALUES ('DUNNING_SENT','collections_agent',$1,$2,
                           'send_dunning_email',$3::jsonb,'ai_agent','collections_agent','ai')""",
                customer_id, invoice_id, audit_detail,
            )
        except Exception as exc:
            logger.warning(f"audit_log insert failed: {exc}")

    return {"sent": sent, "dunning_id": dunning_id, "error": err}


@tool(name="log_promise_to_pay", description="Record a promise-to-pay and update the AR ledger.")
async def log_promise_to_pay(
    invoice_id: Annotated[str, "Invoice ID"],
    customer_id: Annotated[str, "Customer ID"],
    promise_date: Annotated[str, "ISO date string e.g. 2025-07-01"],
    promise_amount_inr: Annotated[float, "Amount promised"],
) -> dict:
    """Insert a promise_to_pay record and update the ar_ledger last_action."""
    ptp_id = f"PTP-{uuid.uuid4().hex[:14].upper()}"
    pd = datetime.fromisoformat(promise_date)
    async with await _get_db() as db:
        ar = await db.fetchrow(
            "SELECT ar_id FROM ar_ledger WHERE invoice_id = $1 LIMIT 1", invoice_id
        )
        await db.execute(
            """INSERT INTO promise_to_pay
               (ptp_id, customer_id, invoice_id, ar_id, promise_date,
                promise_amount_inr, channel, status, logged_by_agent)
               VALUES ($1,$2,$3,$4,$5,$6,'agent','pending','collections_agent')""",
            ptp_id, customer_id, invoice_id,
            ar["ar_id"] if ar else None,
            pd, promise_amount_inr,
        )
        if ar:
            await db.execute(
                """UPDATE ar_ledger
                   SET promise_to_pay_date = $1,
                       promise_to_pay_amount = $2,
                       last_action = 'promise_to_pay_logged',
                       last_action_date = NOW()
                   WHERE ar_id = $3""",
                pd, promise_amount_inr, ar["ar_id"],
            )
    return {"ptp_id": ptp_id, "logged": True}


@tool(name="schedule_followup", description="Schedule a collections re-check for this invoice in N days.")
async def schedule_followup(
    invoice_id: Annotated[str, "Invoice ID"],
    days_from_now: Annotated[int, "Days until the follow-up"] = 3,
    reason: Annotated[str, "Reason for follow-up"] = "",
) -> dict:
    """Queue a delayed collections re-check.

    No Celery: inserts a row into the `followups` table, which the in-process
    FastAPI lifespan sweeper (agents_maf.collections.scheduler.followup_sweeper)
    picks up when due and re-runs the collections agent.
    """
    run_at = datetime.utcnow() + timedelta(days=days_from_now)
    async with await _get_db() as db:
        await db.execute(
            "INSERT INTO followups (invoice_id, due_at, reason) VALUES ($1, $2, $3)",
            invoice_id, run_at, reason,
        )
    return {"scheduled_for": run_at.isoformat(), "reason": reason}


@tool(
    name="escalate_to_hitl",
    description=(
        "Escalate the invoice to a human collections controller. "
        "Logs the escalation to audit_log and signals that human approval is needed. "
        "Use when FDCPA limit is hit, promise broken twice, or non-responsive after 3 contacts."
    ),
)
async def escalate_to_hitl(
    invoice_id: Annotated[str, "Invoice ID"],
    customer_id: Annotated[str, "Customer ID"],
    reason: Annotated[str, "Why escalating to human"],
    suggested_action: Annotated[str, "Suggested action: write_off | payment_plan | agency"] = "",
) -> dict:
    """Log HITL escalation and return a payload that the agent runner uses to pause the run."""
    audit_detail = json.dumps({
        "reason": reason,
        "suggested_action": suggested_action,
    })
    async with await _get_db() as db:
        try:
            await db.execute(
                """INSERT INTO audit_log
                   (event_type, agent_name, customer_id, invoice_id, action,
                    details, actor_type, actor_username, actor_role)
                   VALUES ('COLLECTIONS_HITL','collections_agent',$1,$2,
                           'escalate_to_hitl',$3::jsonb,'ai_agent','collections_agent','ai')""",
                customer_id, invoice_id, audit_detail,
            )
        except Exception as exc:
            logger.warning(f"audit_log HITL insert failed: {exc}")

    return {
        "escalated": True,
        "reason": reason,
        "suggested_action": suggested_action,
        # Sentinel read by run_collections_agent to pause the run
        "_hitl_required": True,
    }


# ── Tool registry ─────────────────────────────────────────────────────────────

COLLECTIONS_TOOLS = [
    get_dunning_history,
    predict_segment,
    count_weekly_contacts,
    draft_dunning_email,
    send_dunning_email,
    log_promise_to_pay,
    schedule_followup,
    escalate_to_hitl,
]
