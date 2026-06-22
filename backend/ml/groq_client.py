"""
O2C Agent v2.0 — Groq LLM Client
Single entry point for all Groq API calls in the system.

Usage:
  - NER validation/correction after GLiNER (orders + disputes)
  - Dunning email generation (Collections agent)
  - Dispute summary generation

Model priority: llama-3.3-70b-versatile → llama-3.1-8b-instant (rate limit fallback)
All structured outputs use JSON mode for reliable parsing.
"""

import json
import logging
import time
from typing import Dict, Any, Optional
from groq import Groq
from config import settings

logger = logging.getLogger(__name__)

_client: Optional[Groq] = None


def get_groq_client() -> Groq:
    global _client
    if _client is None:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def _call_groq(messages: list, json_mode: bool = True, model: str = None) -> str:
    """
    Core Groq API call with automatic fallback to smaller model on rate limit.
    Returns raw response text.
    """
    client = get_groq_client()
    primary = model or settings.groq_model_primary
    fallback = settings.groq_model_fallback

    for attempt, mdl in enumerate([primary, fallback]):
        try:
            kwargs = dict(
                model=mdl,
                messages=messages,
                temperature=0.1,      # Low temp for structured extraction
                max_tokens=1024,
            )
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content
            logger.info(f"Groq [{mdl}] call ok — {resp.usage.total_tokens} tokens")
            return text
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() and attempt == 0:
                logger.warning(f"Groq rate limit on {mdl}, falling back to {fallback}")
                time.sleep(2)
                continue
            logger.error(f"Groq [{mdl}] error: {err}")
            raise
    raise RuntimeError("Both Groq models failed")


# ══════════════════════════════════════════════════════════════════
# 1. ORDER NER — Evaluate + correct GLiNER result
# ══════════════════════════════════════════════════════════════════

ORDER_NER_SYSTEM = """You are an expert Order Management AI for an Indian B2B manufacturing company.
You will receive:
1. The original order email text
2. The entities already extracted by GLiNER (a local NER model)

Your job:
- Verify each GLiNER extraction against the email text
- Correct any wrong extractions
- Fill in any missing entities you can find in the email
- If a field is truly not present in the email, set it to null

Return a JSON object with these exact keys:
{
  "customer_name": "string or null",
  "quantity": "string or null",
  "product_name": "string or null",
  "item_code": "string or null",
  "unit_price": "string or null",
  "delivery_date": "string or null",
  "shipping_address": "string or null",
  "order_reference": "string or null",
  "corrections_made": ["list of what you changed vs GLiNER"],
  "confidence": "HIGH | MEDIUM | LOW"
}

Be conservative — only override GLiNER if you are very sure. Preserve GLiNER values when they look correct."""


def evaluate_and_correct_ner(email_text: str, gliner_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    GLiNER runs first, then Groq evaluates its output and fills gaps / corrects mistakes.
    Returns enriched entity dict with source tags (gliner | groq | groq_corrected).
    """
    # Summarise what GLiNER found for the prompt
    gliner_summary = {
        k: v.get("value") if isinstance(v, dict) else v
        for k, v in gliner_result.items()
    }

    messages = [
        {"role": "system", "content": ORDER_NER_SYSTEM},
        {"role": "user", "content": (
            f"ORIGINAL EMAIL:\n{email_text}\n\n"
            f"GLINER EXTRACTED:\n{json.dumps(gliner_summary, indent=2)}"
        )},
    ]

    try:
        raw = _call_groq(messages, json_mode=True)
        groq_result = json.loads(raw)
    except Exception as e:
        logger.error(f"Groq NER evaluation failed: {e}. Keeping GLiNER result.")
        return gliner_result

    corrections = groq_result.pop("corrections_made", [])
    confidence  = groq_result.pop("confidence", "MEDIUM")
    if corrections:
        logger.info(f"Groq corrected GLiNER: {corrections}")

    # Merge: build final result with source tags
    merged = {}
    for field, groq_val in groq_result.items():
        if groq_val is None:
            # Groq says not present — keep GLiNER if it found something
            if field in gliner_result:
                merged[field] = {**gliner_result[field], "source": "gliner"}
            # else: field truly missing, omit
        else:
            gliner_val = (gliner_result.get(field) or {}).get("value")
            if gliner_val and str(gliner_val).strip() == str(groq_val).strip():
                # Both agree — gliner is authoritative
                merged[field] = {**gliner_result[field], "source": "gliner"}
            elif gliner_val and str(groq_val) not in str(gliner_val) and field not in ("corrections_made", "confidence"):
                # Groq corrected a wrong GLiNER value
                merged[field] = {"value": groq_val, "confidence": 0.90, "source": "groq_corrected"}
            else:
                # Groq filled a gap GLiNER missed
                gliner_conf = (gliner_result.get(field) or {}).get("confidence", 0)
                merged[field] = {
                    "value": groq_val,
                    "confidence": max(0.90, gliner_conf),
                    "source": "groq" if not gliner_val else "gliner",
                }

    merged["_ner_confidence"] = confidence
    merged["_groq_corrections"] = corrections
    return merged


# ══════════════════════════════════════════════════════════════════
# 2. DISPUTE NER — Groq handles disputes (free-form, always messy)
# ══════════════════════════════════════════════════════════════════

DISPUTE_NER_SYSTEM = """You are an expert Accounts Receivable AI for an Indian B2B company.
Extract dispute information from the customer email.

Return a JSON object with these exact keys:
{
  "invoice_reference": "invoice ID like INV-001, or null",
  "claim_amount": "amount as string like 75000 or null",
  "claim_amount_currency": "INR or USD or null",
  "dispute_type": "one of: damaged_goods | pricing_error | short_ship | pod_dispute | deduction_claim | general_dispute",
  "dispute_reason": "brief description of why they are disputing",
  "contact_name": "name of person who sent the email or null",
  "contact_email": "email address if present or null",
  "urgency": "HIGH | MEDIUM | LOW",
  "proposed_resolution": "what the customer is asking for, e.g. credit note, replacement, refund"
}"""


def extract_dispute_entities_groq(email_text: str) -> Dict[str, Any]:
    """Full Groq extraction for dispute emails — more reliable than GLiNER for this case."""
    messages = [
        {"role": "system", "content": DISPUTE_NER_SYSTEM},
        {"role": "user", "content": f"DISPUTE EMAIL:\n{email_text}"},
    ]
    try:
        raw = _call_groq(messages, json_mode=True)
        result = json.loads(raw)
        logger.info(f"Groq dispute NER: type={result.get('dispute_type')}, amount={result.get('claim_amount')}")
        return result
    except Exception as e:
        logger.error(f"Groq dispute NER failed: {e}")
        return {
            "dispute_type": "general_dispute",
            "dispute_reason": email_text[:200],
            "urgency": "MEDIUM",
        }


# ══════════════════════════════════════════════════════════════════
# 3. DUNNING EMAIL GENERATION — Collections agent
# ══════════════════════════════════════════════════════════════════

DUNNING_SYSTEM = """You are a professional accounts receivable specialist at an Indian B2B manufacturing company called MAQ Manufacturing.
Write a dunning (payment reminder) email. Be professional, clear, and use the TONE provided.

Tone guide:
- gentle_reminder: Polite, relationship-first. Assume the customer simply forgot.
- firm: Standard overdue notice. Mention potential service hold if unpaid.
- urgent: Escalated tone. Offer a payment plan, mention consequences.
- legal_warning: Final notice. Clearly state handoff to collections/legal if no response in 48 hours.

Always include: Invoice ID, amount due, days overdue, and a clear call to action.

Return JSON:
{
  "subject": "email subject line",
  "body": "full email body with proper formatting",
  "tone": "the tone you used"
}"""


def generate_dunning_email(
    customer_name: str,
    invoice_id: str,
    amount_inr: float,
    days_overdue: int,
    payment_terms: int = 30,
    contact_name: str = "",
    tone: str = "firm",
) -> Dict[str, str]:
    """Generate a personalised dunning email using Groq LLaMA 3.3 70B.
    
    tone is driven by k-means customer segment:
      gentle_reminder (Premium) | firm (Standard) | urgent (At-Risk) | legal_warning (Problem)
    """
    level = 1 if days_overdue <= 15 else (2 if days_overdue <= 30 else 3)
    messages = [
        {"role": "system", "content": DUNNING_SYSTEM},
        {"role": "user", "content": (
            f"Customer: {customer_name}\n"
            f"Contact: {contact_name or 'Accounts Payable Team'}\n"
            f"Invoice: {invoice_id}\n"
            f"Amount: Rs.{amount_inr:,.0f}\n"
            f"Days Overdue: {days_overdue}\n"
            f"Payment Terms: Net {payment_terms}\n"
            f"Dunning Level: {level}\n"
            f"TONE: {tone}\n"
            f"Generate the dunning email using the specified tone."
        )},
    ]
    try:
        raw = _call_groq(messages, json_mode=True)
        result = json.loads(raw)
        logger.info(f"Groq dunning L{level} [{tone}] generated for {invoice_id} ({days_overdue}d overdue)")
        return result
    except Exception as e:
        logger.error(f"Groq dunning generation failed: {e}")
        # Fallback template
        return {
            "subject": f"Payment Reminder - Invoice {invoice_id}",
            "body": (
                f"Dear {contact_name or customer_name},\n\n"
                f"This is a reminder that Invoice {invoice_id} for Rs.{amount_inr:,.0f} "
                f"is {days_overdue} days overdue.\n\n"
                f"Please arrange payment at the earliest.\n\nRegards,\nMAQ Finance Team"
            ),
            "tone": tone,
        }


# ══════════════════════════════════════════════════════════════════
# 4. DISPUTE SUMMARY — Human-readable AI summary for HITL
# ══════════════════════════════════════════════════════════════════

def generate_dispute_summary(dispute_data: Dict[str, Any]) -> str:
    """Generate a one-paragraph AI summary of a dispute for the HITL reviewer."""
    messages = [
        {"role": "system", "content": (
            "You are an AR specialist. Write a single clear sentence (max 30 words) "
            "summarising this dispute for a finance controller to review. Be factual, no fluff."
        )},
        {"role": "user", "content": json.dumps(dispute_data)},
    ]
    try:
        raw = _call_groq(messages, json_mode=False, model=settings.groq_model_fallback)
        return raw.strip().strip('"')
    except Exception as e:
        logger.error(f"Groq dispute summary failed: {e}")
        return f"{dispute_data.get('dispute_type','Dispute')} — ₹{dispute_data.get('claim_amount', 0):,.0f} claimed."
