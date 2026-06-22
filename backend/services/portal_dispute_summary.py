"""
AI summary generation for customer-created portal disputes.
This service creates internal triage summaries only. It must never decide a
dispute or generate customer-facing replies.
"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from config import settings
from database.postgres import get_pool
from ml.groq_client import _call_groq

logger = logging.getLogger(__name__)


def fallback_summary(
    dispute_type: str,
    subject: str,
    message: str,
    proof_count: int,
    attachment_names: Optional[List[str]] = None,
) -> str:
    proof = "Proof uploaded" if proof_count > 0 else "No proof uploaded"
    names = f" Files: {', '.join(attachment_names[:3])}." if attachment_names else ""
    clean_type = (dispute_type or "general").replace("_", " ").title()
    clean_message = " ".join((message or "").split())[:260]
    return f"{clean_type} dispute. Subject: {subject}. Customer says: {clean_message}. {proof}.{names}"


def generate_ai_summary_payload(
    dispute_type: str,
    subject: str,
    latest_customer_message: str,
    proof_count: int,
    attachment_names: List[str],
    invoice_id: Optional[str] = None,
    order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a concise internal summary. Falls back safely if Groq is unavailable."""
    base = fallback_summary(dispute_type, subject, latest_customer_message, proof_count, attachment_names)

    if not settings.groq_api_key:
        return {"summary": base, "status": "fallback_no_api_key", "model": "fallback"}

    prompt = f"""
You are summarizing a B2B accounts receivable customer dispute for an internal Admin reviewer.

Hard rules:
- Do not decide the dispute.
- Do not approve, reject, or recommend a credit amount.
- Do not write a reply to the customer.
- Summarize only what the customer is claiming.
- Mention whether proof was uploaded.
- Mention missing information only if obvious.
- Keep the summary under 90 words.
- Return JSON only.

Context:
Dispute type: {dispute_type}
Subject: {subject}
Invoice ID: {invoice_id or 'N/A'}
Order ID: {order_id or 'N/A'}
Latest customer message: {latest_customer_message}
Proof count: {proof_count}
Proof filenames: {', '.join(attachment_names) if attachment_names else 'None'}

Return exactly this JSON shape:
{{
  "summary": "...",
  "proof_uploaded": true,
  "key_claim": "...",
  "missing_info": "..."
}}
"""

    try:
        raw = _call_groq([{"role": "user", "content": prompt}], json_mode=True)
        data = json.loads(raw)
        summary = (data.get("summary") or base).strip()
        return {
            "summary": summary[:1200],
            "status": "generated",
            "model": settings.groq_model_primary,
            "raw": data,
        }
    except Exception as exc:
        logger.warning("Portal dispute AI summary failed; using fallback: %s", exc)
        return {"summary": base, "status": "failed_fallback", "model": "fallback"}


async def refresh_portal_dispute_summary(dispute_id: str) -> None:
    """Background task: refresh the internal AI summary for a dispute."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        dispute = await conn.fetchrow(
            """
            SELECT dispute_id, dispute_type, subject, invoice_id, order_id, proof_count
            FROM portal_disputes
            WHERE dispute_id = $1
            """,
            dispute_id,
        )
        if not dispute:
            logger.warning("Cannot summarize missing dispute %s", dispute_id)
            return

        latest_customer_msg = await conn.fetchval(
            """
            SELECT body
            FROM portal_dispute_messages
            WHERE dispute_id = $1 AND sender_type = 'customer'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            dispute_id,
        ) or ""

        attachment_names = await conn.fetch(
            """
            SELECT filename
            FROM portal_dispute_attachments
            WHERE dispute_id = $1
            ORDER BY created_at
            """,
            dispute_id,
        )
        names = [r["filename"] for r in attachment_names]

    payload = await asyncio.to_thread(
        generate_ai_summary_payload,
        dispute["dispute_type"],
        dispute["subject"],
        latest_customer_msg,
        int(dispute["proof_count"] or 0),
        names,
        dispute["invoice_id"],
        dispute["order_id"],
    )

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE portal_disputes
            SET ai_summary = $1,
                ai_summary_status = $2,
                ai_summary_model = $3,
                ai_summary_generated_at = NOW(),
                updated_at = NOW()
            WHERE dispute_id = $4
            """,
            payload["summary"],
            payload["status"],
            payload["model"],
            dispute_id,
        )
        await conn.execute(
            """
            INSERT INTO audit_log (event_type, agent_name, action, details, outcome)
            VALUES ('PORTAL_DISPUTE_AI_SUMMARY', 'portal_dispute_summary', 'AI summary refreshed', $1::jsonb, $2)
            """,
            json.dumps({"dispute_id": dispute_id, "status": payload["status"], "model": payload["model"]}),
            payload["status"],
        )
