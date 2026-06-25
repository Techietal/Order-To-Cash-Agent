"""MAF tool library for the Disputes Agent.

Wraps existing NER/summary helpers and performs SOX-guarded credit-memo issuance
against the real schema (credit_memos + invoices + ar_ledger).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated

from agent_framework import tool

from agents_maf.runtime import _get_db, log_hitl

logger = logging.getLogger(__name__)

# SOX RULE-002: credits at/above this require a human approver.
SOX_CREDIT_LIMIT_INR = 50_000.0
AGENT_NAME = "disputes_agent"


# ── READ tools ────────────────────────────────────────────────────────────────

@tool(name="get_dispute", description="Fetch a portal dispute and its message thread.")
async def get_dispute(
    dispute_id: Annotated[str, "Dispute ID e.g. DISP-20250101-0001"],
) -> dict:
    """Return the dispute record plus its messages (oldest first)."""
    async with await _get_db() as db:
        d = await db.fetchrow("SELECT * FROM portal_disputes WHERE dispute_id = $1", dispute_id)
        if not d:
            return {"found": False}
        msgs = await db.fetch(
            "SELECT sender_type, body, created_at FROM portal_dispute_messages "
            "WHERE dispute_id = $1 ORDER BY created_at ASC",
            dispute_id,
        )
    return {
        "found": True,
        "dispute": {k: d[k] for k in ("dispute_id", "customer_id", "invoice_id",
                                       "dispute_type", "subject", "status", "proof_count")},
        "messages": [{"sender": m["sender_type"], "body": m["body"]} for m in msgs],
    }


@tool(name="extract_dispute_entities", description="Extract dispute_type, amount, invoice ref from text via Ollama Cloud NER.")
async def extract_dispute_entities(
    text: Annotated[str, "The customer's dispute message text"],
) -> dict:
    """Return structured dispute entities from free text."""
    from ml.llm_client import extract_dispute_entities
    try:
        return extract_dispute_entities(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("dispute NER failed: %s", exc)
        return {"dispute_type": "general_dispute", "dispute_reason": text[:200]}


@tool(name="summarize_dispute", description="One-line reviewer summary of a dispute.")
async def summarize_dispute(
    subject: Annotated[str, "Dispute subject"],
    dispute_type: Annotated[str, "Dispute type"],
    detail: Annotated[str, "Key dispute detail / customer claim"] = "",
) -> dict:
    """Generate a short summary string for a human reviewer."""
    from ml.llm_client import generate_dispute_summary
    try:
        summary = generate_dispute_summary({
            "subject": subject, "dispute_type": dispute_type, "detail": detail,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("dispute summary failed: %s", exc)
        summary = f"{dispute_type}: {subject}"[:200]
    return {"summary": summary}


# ── WRITE tools ───────────────────────────────────────────────────────────────

@tool(
    name="issue_credit_memo",
    description=(
        "Issue a credit memo against an invoice (reduces its balance). "
        "SOX-guarded: blocked if amount >= the policy limit — escalate instead."
    ),
)
async def issue_credit_memo(
    invoice_id: Annotated[str, "Invoice ID to credit"],
    customer_id: Annotated[str, "Customer ID"],
    amount_inr: Annotated[float, "Credit amount in INR"],
    reason: Annotated[str, "Reason for the credit"],
    dispute_id: Annotated[str, "Originating dispute ID"] = "",
) -> dict:
    """Create a credit_memo and apply it to invoices + ar_ledger (SOX-guarded)."""
    if amount_inr >= SOX_CREDIT_LIMIT_INR:
        return {
            "issued": False,
            "blocked_reason": (
                f"SOX RULE-002: credit \u20b9{amount_inr:,.0f} >= "
                f"\u20b9{SOX_CREDIT_LIMIT_INR:,.0f} limit — requires human approval"
            ),
        }

    async with await _get_db() as db:
        inv = await db.fetchrow(
            "SELECT balance_due_inr, order_id FROM invoices WHERE invoice_id = $1", invoice_id
        )
        if not inv:
            return {"issued": False, "blocked_reason": f"Invoice {invoice_id} not found"}

        balance_before = float(inv["balance_due_inr"] or 0)
        balance_after = max(0.0, balance_before - float(amount_inr))
        memo_id = f"MEMO-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]}"

        await db.execute(
            """INSERT INTO credit_memos
                   (memo_id, order_id, invoice_id, customer_id, dispute_id, amount_inr,
                    reason, approved_by, approved_by_role, balance_before_inr,
                    balance_after_inr, source)
               VALUES ($1,$2,$3,$4,$5,$6,$7,'disputes_agent','ai',$8,$9,'dispute_resolution')""",
            memo_id, inv["order_id"], invoice_id, customer_id, dispute_id or None,
            float(amount_inr), reason, balance_before, balance_after,
        )
        new_status = "paid" if balance_after <= 0 else "partial"
        await db.execute(
            "UPDATE invoices SET balance_due_inr = $1, payment_status = $2, updated_at = NOW() "
            "WHERE invoice_id = $3",
            balance_after, new_status, invoice_id,
        )
        await db.execute(
            "UPDATE ar_ledger SET outstanding_balance_inr = $1, "
            "last_action = 'credit_memo_applied', last_action_date = NOW() "
            "WHERE invoice_id = $2",
            balance_after, invoice_id,
        )
        await db.execute(
            """INSERT INTO audit_log
                   (event_type, agent_name, customer_id, invoice_id, action, details,
                    actor_type, actor_username, actor_role)
               VALUES ('CREDIT_MEMO_ISSUED','disputes_agent',$1,$2,'issue_credit_memo',
                       $3::jsonb,'ai_agent','disputes_agent','ai')""",
            customer_id, invoice_id,
            json.dumps({"memo_id": memo_id, "amount_inr": amount_inr,
                        "balance_after": balance_after, "dispute_id": dispute_id}),
        )
    return {"issued": True, "memo_id": memo_id,
            "balance_before": balance_before, "balance_after": balance_after}


@tool(name="resolve_dispute", description="Mark a dispute resolved with a decision note.")
async def resolve_dispute(
    dispute_id: Annotated[str, "Dispute ID"],
    note: Annotated[str, "Resolution note"],
) -> dict:
    """Close the dispute (status='resolved')."""
    async with await _get_db() as db:
        await db.execute(
            "UPDATE portal_disputes SET status = 'resolved', next_actor = 'customer', "
            "decided_by = 'disputes_agent', decision_note = $1, "
            "closed_at = NOW(), updated_at = NOW() WHERE dispute_id = $2",
            note, dispute_id,
        )
    return {"resolved": True, "dispute_id": dispute_id}


@tool(name="escalate_to_hitl", description="Escalate the dispute to a human disputes manager (pauses the run).")
async def escalate_to_hitl(
    dispute_id: Annotated[str, "Dispute ID"],
    customer_id: Annotated[str, "Customer ID"],
    reason: Annotated[str, "Why escalating"],
    suggested_action: Annotated[str, "credit | reject | request_evidence"] = "",
) -> dict:
    """Log a HITL escalation keyed on the dispute_id."""
    return await log_hitl(
        agent_name=AGENT_NAME, event_type="DISPUTES_HITL",
        entity_id=dispute_id, customer_id=customer_id,
        reason=reason, suggested_action=suggested_action,
    )


@tool(
    name="handoff_to_collections",
    description=(
        "Hand off to the Collections Agent to pursue the REMAINING invoice balance "
        "after a partial credit memo. Use only when the invoice still has a balance due."
    ),
)
async def handoff_to_collections(
    invoice_id: Annotated[str, "Invoice ID that still has a balance due"],
    reason: Annotated[str, "Why collections should follow up"] = "Residual balance after dispute credit",
) -> dict:
    """Queue a Collections Agent run for the remaining invoice balance."""
    from agents_maf.runtime import record_handoff
    return await record_handoff(
        from_agent=AGENT_NAME, to_agent="collections",
        entity_type="invoice", entity_id=invoice_id, reason=reason,
    )


DISPUTES_TOOLS = [
    get_dispute,
    extract_dispute_entities,
    summarize_dispute,
    issue_credit_memo,
    resolve_dispute,
    handoff_to_collections,
    escalate_to_hitl,
]
