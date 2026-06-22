"""AI extraction for customer-created portal disputes.

This service is used before a dispute is submitted. It turns the customer's
natural-language description into editable form fields. It does not create a
dispute, make a decision, or generate a customer-facing response.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from config import settings
from ml.groq_client import _call_groq

logger = logging.getLogger(__name__)

VALID_DISPUTE_TYPES = {
    "pricing_error",
    "damaged_goods",
    "short_ship",
    "payment_not_reflected",
    "pod_dispute",
    "general",
}

TYPE_ALIASES = {
    "price": "pricing_error",
    "pricing": "pricing_error",
    "overcharge": "pricing_error",
    "overcharged": "pricing_error",
    "rate": "pricing_error",
    "wrong price": "pricing_error",
    "damaged": "damaged_goods",
    "damage": "damaged_goods",
    "broken": "damaged_goods",
    "defective": "damaged_goods",
    "missing": "short_ship",
    "short": "short_ship",
    "shortage": "short_ship",
    "less quantity": "short_ship",
    "payment": "payment_not_reflected",
    "paid": "payment_not_reflected",
    "not reflected": "payment_not_reflected",
    "delivery proof": "pod_dispute",
    "pod": "pod_dispute",
    "proof of delivery": "pod_dispute",
}


def _clean_text(value: Optional[str], max_len: int = 1200) -> str:
    return " ".join((value or "").split())[:max_len]


def _normalise_type(value: Optional[str], source_text: str = "") -> str:
    raw = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw in VALID_DISPUTE_TYPES:
        return raw
    if raw == "general_dispute" or raw == "deduction_claim":
        return "general"

    haystack = f"{raw} {source_text}".lower()
    for key, mapped in TYPE_ALIASES.items():
        if key in haystack:
            return mapped
    return "general"


def _subject_from_text(text: str, dispute_type: str, invoice_id: Optional[str], order_id: Optional[str]) -> str:
    first_sentence = re.split(r"[.\n!?]", text.strip(), maxsplit=1)[0]
    short = _clean_text(first_sentence, 72)
    if short:
        return short
    target = invoice_id or order_id or "selected transaction"
    return f"{dispute_type.replace('_', ' ').title()} for {target}"


def _find_allowed_id(text: str, allowed_ids: List[str]) -> Optional[str]:
    text_lower = text.lower()
    for item_id in allowed_ids:
        if item_id and item_id.lower() in text_lower:
            return item_id
    return None


def _fallback_preview(
    text: str,
    invoices: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
    reason: str = "fallback",
) -> Dict[str, Any]:
    invoice_ids = [str(i.get("invoice_id")) for i in invoices if i.get("invoice_id")]
    order_ids = [str(o.get("order_id")) for o in orders if o.get("order_id")]
    invoice_id = _find_allowed_id(text, invoice_ids)
    order_id = _find_allowed_id(text, order_ids)
    dispute_type = _normalise_type(None, text)

    missing = []
    if not invoice_id and not order_id:
        missing.append("invoice_or_order")
    if len(text.strip()) < 25:
        missing.append("dispute_details")

    return {
        "prefilled_form": {
            "invoice_id": invoice_id,
            "order_id": order_id,
            "dispute_type": dispute_type,
            "subject": _subject_from_text(text, dispute_type, invoice_id, order_id),
            "message": text.strip(),
        },
        "extracted": {
            "invoice_id": {"value": invoice_id, "confidence": 0.65 if invoice_id else 0},
            "order_id": {"value": order_id, "confidence": 0.65 if order_id else 0},
            "dispute_type": {"value": dispute_type, "confidence": 0.55},
            "subject": {"value": _subject_from_text(text, dispute_type, invoice_id, order_id), "confidence": 0.55},
            "message": {"value": text.strip(), "confidence": 0.7},
        },
        "ner_confidence": "LOW" if missing else "MEDIUM",
        "groq_corrections": [],
        "missing_fields": missing,
        "review_notes": [
            "AI extraction could not run, so the form was prepared using simple text matching. Please review carefully."
            if reason != "no_api_key"
            else "Groq API key is not configured, so the form was prepared using simple text matching. Please review carefully."
        ],
        "message": "Review the extracted dispute details below before submitting.",
        "source": reason,
    }


def build_customer_context(
    invoices: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Keep the prompt compact and force the model to choose from owned records."""
    compact_invoices = []
    for inv in invoices[:25]:
        compact_invoices.append(
            {
                "invoice_id": inv.get("invoice_id"),
                "order_id": inv.get("order_id"),
                "status": inv.get("status"),
                "total_amount_inr": inv.get("total_amount_inr"),
                "balance_due_inr": inv.get("balance_due_inr"),
            }
        )

    compact_orders = []
    for order in orders[:25]:
        compact_orders.append(
            {
                "order_id": order.get("order_id"),
                "status": order.get("status"),
                "total_amount_inr": order.get("total_amount_inr"),
                "requested_delivery_date": str(order.get("requested_delivery_date") or ""),
            }
        )

    return {"invoices": compact_invoices, "orders": compact_orders}


def extract_portal_dispute_preview(
    text: str,
    invoices: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Extract editable dispute fields from a free-text customer description."""
    text = (text or "").strip()
    if not text:
        return _fallback_preview("", invoices, orders)

    if not settings.groq_api_key:
        return _fallback_preview(text, invoices, orders, reason="no_api_key")

    context = build_customer_context(invoices, orders)
    allowed_invoice_ids = [i.get("invoice_id") for i in context["invoices"] if i.get("invoice_id")]
    allowed_order_ids = [o.get("order_id") for o in context["orders"] if o.get("order_id")]

    system = """You are an AI extraction assistant for a B2B customer portal dispute form.
Your job is to extract editable form fields from the customer's natural-language dispute description.

Hard rules:
- Do not decide the dispute.
- Do not approve, reject, promise credit, or write an admin reply.
- Extract only what the customer appears to be claiming.
- invoice_id must be null or one of the allowed invoice IDs.
- order_id must be null or one of the allowed order IDs.
- If the customer mentions an invoice/order that is not in the allowed list, set it to null and add it to missing_fields.
- Keep subject short and customer-facing.
- The message should be a clean first dispute message that preserves the customer's claim.
- Return JSON only."""

    user = f"""
Customer text:
{text}

Allowed customer invoices:
{json.dumps(context['invoices'], default=str)}

Allowed customer orders:
{json.dumps(context['orders'], default=str)}

Return exactly this JSON shape:
{{
  "invoice_id": "one of {allowed_invoice_ids} or null",
  "order_id": "one of {allowed_order_ids} or null",
  "dispute_type": "pricing_error | damaged_goods | short_ship | payment_not_reflected | pod_dispute | general",
  "subject": "short subject under 90 characters",
  "message": "clean first message preserving the customer's claim",
  "confidence": "HIGH | MEDIUM | LOW",
  "missing_fields": ["list of missing fields that customer should review"],
  "review_notes": ["short notes for the customer reviewing the extraction"],
  "corrections_made": ["what you inferred or normalized"]
}}
"""

    try:
        raw = _call_groq(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            json_mode=True,
        )
        data = json.loads(raw)

        invoice_id = data.get("invoice_id")
        order_id = data.get("order_id")
        if invoice_id not in allowed_invoice_ids:
            invoice_id = None
        if order_id not in allowed_order_ids:
            order_id = None

        dispute_type = _normalise_type(data.get("dispute_type"), text)
        subject = _clean_text(data.get("subject"), 90) or _subject_from_text(text, dispute_type, invoice_id, order_id)
        message = (data.get("message") or text).strip()
        if len(message) < 10:
            message = text

        missing = data.get("missing_fields") if isinstance(data.get("missing_fields"), list) else []
        if not invoice_id and not order_id and "invoice_or_order" not in missing:
            missing.append("invoice_or_order")

        notes = data.get("review_notes") if isinstance(data.get("review_notes"), list) else []
        corrections = data.get("corrections_made") if isinstance(data.get("corrections_made"), list) else []
        confidence = str(data.get("confidence") or "MEDIUM").upper()
        if confidence not in {"HIGH", "MEDIUM", "LOW"}:
            confidence = "MEDIUM"

        return {
            "prefilled_form": {
                "invoice_id": invoice_id,
                "order_id": order_id,
                "dispute_type": dispute_type,
                "subject": subject,
                "message": message,
            },
            "extracted": {
                "invoice_id": {"value": invoice_id, "confidence": 0.9 if invoice_id else 0},
                "order_id": {"value": order_id, "confidence": 0.9 if order_id else 0},
                "dispute_type": {"value": dispute_type, "confidence": 0.85},
                "subject": {"value": subject, "confidence": 0.85},
                "message": {"value": message, "confidence": 0.85},
            },
            "ner_confidence": confidence,
            "groq_corrections": corrections,
            "missing_fields": missing,
            "review_notes": notes,
            "message": "Review the extracted dispute details below before submitting.",
            "source": "groq",
        }
    except Exception as exc:
        logger.warning("Portal dispute preview extraction failed; using fallback: %s", exc)
        return _fallback_preview(text, invoices, orders, reason="failed_fallback")
