"""MAF tool library for the Cash Application Agent.

Matches remittances to invoices and posts payments against the real schema
(invoices + payments + ar_ledger).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated

from agent_framework import tool

from agents_maf.runtime import _get_db, log_hitl

logger = logging.getLogger(__name__)

AGENT_NAME = "cash_application_agent"
AUTO_THRESHOLD = 0.78
REVIEW_THRESHOLD = 0.65


@tool(name="get_invoice_balance", description="Open balance + status for an invoice.")
async def get_invoice_balance(
    invoice_id: Annotated[str, "Invoice ID"],
) -> dict:
    """Return balance_due_inr, payment_status, customer_id for the invoice."""
    async with await _get_db() as db:
        row = await db.fetchrow(
            "SELECT customer_id, balance_due_inr, total_amount_inr, payment_status "
            "FROM invoices WHERE invoice_id = $1",
            invoice_id,
        )
    if not row:
        return {"found": False}
    return {
        "found": True,
        "customer_id": row["customer_id"],
        "balance_due_inr": float(row["balance_due_inr"] or 0),
        "total_amount_inr": float(row["total_amount_inr"] or 0),
        "payment_status": row["payment_status"],
    }


@tool(name="match_payment", description="Score how well a remittance matches an invoice (0-1 confidence).")
async def match_payment(
    invoice_id: Annotated[str, "Invoice ID"],
    remittance_amount: Annotated[float, "Amount on the remittance advice"],
    remittance_text: Annotated[str, "Free-text remittance note / reference"] = "",
) -> dict:
    """Combine amount-closeness and text similarity into a match confidence."""
    async with await _get_db() as db:
        row = await db.fetchrow(
            "SELECT balance_due_inr FROM invoices WHERE invoice_id = $1", invoice_id
        )
    if not row:
        return {"confidence": 0.0, "reason": "invoice not found"}

    balance = float(row["balance_due_inr"] or 0)
    if balance <= 0:
        return {"confidence": 0.0, "reason": "invoice already settled"}

    amount_score = max(0.0, 1.0 - abs(float(remittance_amount) - balance) / max(balance, 1.0))
    text_score = 0.0
    if remittance_text:
        try:
            from ml.embeddings import compute_similarity
            text_score = float(compute_similarity(remittance_text, invoice_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("similarity failed: %s", exc)
            text_score = 1.0 if invoice_id.lower() in remittance_text.lower() else 0.0

    confidence = round(0.7 * amount_score + 0.3 * text_score, 4)
    return {
        "confidence": confidence,
        "amount_score": round(amount_score, 4),
        "text_score": round(text_score, 4),
        "balance_due_inr": balance,
        "is_overpayment": float(remittance_amount) > balance,
    }


@tool(name="apply_payment", description="Post a matched payment to an invoice + AR ledger.")
async def apply_payment(
    invoice_id: Annotated[str, "Invoice ID"],
    customer_id: Annotated[str, "Customer ID"],
    amount_inr: Annotated[float, "Payment amount in INR"],
    payment_ref: Annotated[str, "Bank reference / remittance id"] = "",
) -> dict:
    """Apply a payment: update invoice + ar_ledger and insert a payments row."""
    if amount_inr <= 0:
        return {"applied": False, "reason": "amount must be positive"}

    async with await _get_db() as db:
        inv = await db.fetchrow(
            "SELECT balance_due_inr, amount_paid_inr FROM invoices WHERE invoice_id = $1",
            invoice_id,
        )
        if not inv:
            return {"applied": False, "reason": f"invoice {invoice_id} not found"}

        balance = float(inv["balance_due_inr"] or 0)
        paid = float(inv["amount_paid_inr"] or 0)
        if amount_inr > balance:
            return {"applied": False, "reason": "overpayment — escalate to a human"}

        new_balance = max(0.0, balance - float(amount_inr))
        new_paid = paid + float(amount_inr)
        new_status = "paid" if new_balance <= 0 else "partial"
        payment_id = f"PAY-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]}"

        await db.execute(
            "UPDATE invoices SET amount_paid_inr = $1, balance_due_inr = $2, "
            "payment_status = $3, updated_at = NOW() WHERE invoice_id = $4",
            new_paid, new_balance, new_status, invoice_id,
        )
        await db.execute(
            "UPDATE ar_ledger SET outstanding_balance_inr = $1, "
            "last_action = 'auto_matched_by_ai', last_action_date = NOW() "
            "WHERE invoice_id = $2",
            new_balance, invoice_id,
        )
        await db.execute(
            "INSERT INTO payments (payment_id, invoice_id, amount_inr, payment_method, "
            "bank_ref_number, status) VALUES ($1,$2,$3,'bank_transfer',$4,'processed')",
            payment_id, invoice_id, float(amount_inr), payment_ref or None,
        )
        await db.execute(
            """INSERT INTO audit_log
                   (event_type, agent_name, customer_id, invoice_id, action, details,
                    actor_type, actor_username, actor_role)
               VALUES ('CASH_APPLICATION','cash_application_agent',$1,$2,'apply_payment',
                       $3::jsonb,'ai_agent','cash_application_agent','ai')""",
            customer_id, invoice_id,
            json.dumps({"payment_id": payment_id, "amount_inr": amount_inr,
                        "balance_after": new_balance}),
        )
    return {"applied": True, "payment_id": payment_id,
            "balance_after": new_balance, "status": new_status}


@tool(name="escalate_to_hitl", description="Escalate unmatched/ambiguous payment to a human (pauses the run).")
async def escalate_to_hitl(
    invoice_id: Annotated[str, "Invoice ID"],
    customer_id: Annotated[str, "Customer ID"],
    reason: Annotated[str, "Why escalating"],
    suggested_action: Annotated[str, "manual_match | refund | partial_apply"] = "",
) -> dict:
    """Log a HITL escalation keyed on the invoice_id."""
    return await log_hitl(
        agent_name=AGENT_NAME, event_type="CASH_HITL",
        entity_id=invoice_id, customer_id=customer_id,
        reason=reason, suggested_action=suggested_action,
    )


@tool(
    name="handoff_to_collections",
    description=(
        "Hand off to the Collections Agent to pursue a REMAINING balance after a "
        "partial payment was applied. Use only when balance_after > 0."
    ),
)
async def handoff_to_collections(
    invoice_id: Annotated[str, "Invoice ID with a remaining balance"],
    reason: Annotated[str, "Why collections should follow up"] = "Residual balance after partial payment",
) -> dict:
    """Queue a Collections Agent run for the remaining invoice balance."""
    from agents_maf.runtime import record_handoff
    return await record_handoff(
        from_agent=AGENT_NAME, to_agent="collections",
        entity_type="invoice", entity_id=invoice_id, reason=reason,
    )


CASH_TOOLS = [
    get_invoice_balance,
    match_payment,
    apply_payment,
    handoff_to_collections,
    escalate_to_hitl,
]
