"""Email classification: keyword rules first, Groq LLM fallback."""

from __future__ import annotations

import json
import logging

from groq import Groq

from . import config
from .models import Category, Classification, EmailMessage

logger = logging.getLogger(__name__)

ORDER_KEYWORDS = [
    "order confirmation",
    "purchase order",
    "new order",
    "order #",
    "order number",
    "your order",
    "po number",
]

PAYMENT_KEYWORDS = [
    "payment received",
    "payment confirmation",
    "remittance",
    "invoice paid",
    "receipt",
    "transaction id",
    "paid in full",
]

DISPUTE_KEYWORDS = [
    "chargeback",
    "dispute",
    "refund request",
    "complaint",
    "unauthorized",
    "incorrect charge",
    "billing error",
]

SYSTEM_PROMPT = (
    "You are an email classifier for an Order-to-Cash (O2C) system. "
    "Read the email and assign exactly ONE category:\n"
    "- ORDER: a new purchase order, order confirmation, order change, "
    "quote request, or anything about placing/modifying an order.\n"
    "- PAYMENT: remittance advice, payment confirmation, invoice settlement, "
    "receipt, or anything about money that has been or will be paid.\n"
    "- DISPUTE: chargeback, refund request, complaint, billing disagreement, "
    "unauthorized or incorrect charge, or escalation about an order/payment.\n"
    "- OTHER: anything not relevant to O2C, such as newsletters, marketing, "
    "spam, internal notices, or personal mail.\n"
    "Base the decision on the sender, subject, and body. If the email could "
    "plausibly fit more than one category, choose the most central business "
    "intent and lower your confidence accordingly.\n"
    "Respond ONLY with a JSON object with these keys: "
    "category (one of ORDER, PAYMENT, DISPUTE, OTHER), "
    "confidence (number from 0 to 1 reflecting how certain you are), "
    "reason (one short sentence explaining the choice)."
)


def _keyword_match(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _rule_classify(email: EmailMessage) -> Classification | None:
    """Return a confident classification from keyword rules, or None."""
    text = f"{email.subject}\n{email.body}".lower()

    matches: list[Category] = []
    if _keyword_match(text, ORDER_KEYWORDS):
        matches.append(Category.ORDER)
    if _keyword_match(text, PAYMENT_KEYWORDS):
        matches.append(Category.PAYMENT)
    if _keyword_match(text, DISPUTE_KEYWORDS):
        matches.append(Category.DISPUTE)

    # Only confident when exactly one category matches.
    if len(matches) == 1:
        return Classification(
            category=matches[0],
            confidence=1.0,
            reason="Matched keyword rule.",
        )
    return None


def _llm_classify(email: EmailMessage) -> Classification:
    """Classify an ambiguous email using the Groq LLM."""
    if not config.GROQ_API_KEY.strip():
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your "
            "Groq API key (get one at https://console.groq.com/keys)."
        )

    client = Groq(api_key=config.GROQ_API_KEY)

    user_content = (
        f"From: {email.sender}\n"
        f"Subject: {email.subject}\n\n"
        f"{email.body}"
    )

    response = client.chat.completions.create(
        model=config.GROQ_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )

    data = json.loads(response.choices[0].message.content)
    raw_category = str(data.get("category", "OTHER")).upper()
    try:
        category = Category(raw_category)
    except ValueError:
        category = Category.OTHER
    confidence = float(data.get("confidence", 0.0))
    reason = str(data.get("reason", ""))

    return Classification(category=category, confidence=confidence, reason=reason)


def classify(email: EmailMessage) -> Classification:
    """Classify an email using keyword rules first, then the LLM fallback."""
    rule_result = _rule_classify(email)
    if rule_result is not None:
        return rule_result

    result = _llm_classify(email)
    if result.confidence < config.LLM_CONFIDENCE_THRESHOLD:
        return Classification(
            category=Category.NEEDS_REVIEW,
            confidence=result.confidence,
            reason=f"Low confidence ({result.confidence:.2f}): {result.reason}",
        )
    return result
