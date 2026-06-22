"""Routing of classified emails to the O2C backend agents (via HTTP)."""

from __future__ import annotations

import logging
from typing import Callable

import httpx

from api.staff_deps import create_service_token
from . import config
from .models import Category, Classification, EmailMessage

logger = logging.getLogger(__name__)

Handler = Callable[[EmailMessage, Classification], None]

# O2C FastAPI endpoints (paths are relative to O2C_API_BASE_URL).
ORDER_ENDPOINT = "/api/orders/ingest-email"
DISPUTE_ENDPOINT = "/api/disputes/submit-email"
PAYMENT_ENDPOINT = "/api/cash-app/process-payment"


def _post(base_url: str, path: str, payload: dict, timeout: float, auth: bool = True) -> dict:
    """POST a JSON payload to a URL and return the parsed response."""
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {create_service_token()}"} if auth else {}
    response = httpx.post(url, json=payload, timeout=timeout, headers=headers)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _forward_to_friend(category: str, email: EmailMessage, payload: dict) -> None:
    """Forward classified email payload to friend's external agent (best-effort)."""
    if not config.FRIEND_AGENT_URL:
        return
    try:
        url = f"{config.FRIEND_AGENT_URL.rstrip('/')}/{category.lower()}"
        result = httpx.post(url, json={**payload, "category": category,
                                        "email_from": email.sender,
                                        "subject": email.subject,
                                        "message_id": email.id},
                            timeout=config.FRIEND_AGENT_TIMEOUT)
        logger.info("Forwarded %s to friend agent -> HTTP %s", category, result.status_code)
    except Exception as e:
        logger.warning("Friend agent forward failed (non-fatal): %s", e)


def handle_order(email: EmailMessage, classification: Classification) -> None:
    """Forward an ORDER email to Agent 1 (Order Ingestion)."""
    payload = {
        "email_text": email.body,
        "email_from": email.sender,
        "subject": email.subject,
    }
    result = _post(config.O2C_API_BASE_URL, ORDER_ENDPOINT, payload, config.O2C_API_TIMEOUT)
    logger.info("ORDER forwarded for message %s -> %s", email.id, result)
    _forward_to_friend("ORDER", email, payload)


def handle_payment(email: EmailMessage, classification: Classification) -> None:
    """Forward a PAYMENT email to the Cash Application agent."""
    payload = {
        "remittance_text": f"{email.subject}\n\n{email.body}".strip(),
        "email_from": email.sender,   # email-first customer scope
    }
    result = _post(config.O2C_API_BASE_URL, PAYMENT_ENDPOINT, payload, config.O2C_API_TIMEOUT)
    logger.info("PAYMENT forwarded for message %s -> %s", email.id, result)
    _forward_to_friend("PAYMENT", email, payload)



def handle_dispute(email: EmailMessage, classification: Classification) -> None:
    """Forward a DISPUTE email to Agent 4 (Dispute Ingestion).

    The dispute submission endpoint is intentionally public (registered-sender
    verification happens inside the endpoint), so we do not send a service token.
    """
    payload = {
        "email_text": email.body,
        "email_from": email.sender,
        "subject": email.subject,
    }
    result = _post(config.O2C_API_BASE_URL, DISPUTE_ENDPOINT, payload, config.O2C_API_TIMEOUT, auth=False)
    logger.info("DISPUTE forwarded for message %s -> %s", email.id, result)
    _forward_to_friend("DISPUTE", email, payload)


def handle_review(email: EmailMessage, classification: Classification) -> None:
    """Surface ambiguous emails for manual review."""
    logger.warning(
        "NEEDS_REVIEW message %s (subject=%r, reason=%s)",
        email.id,
        email.subject,
        classification.reason,
    )


AGENT_REGISTRY: dict[Category, Handler] = {
    Category.ORDER: handle_order,
    Category.PAYMENT: handle_payment,
    Category.DISPUTE: handle_dispute,
    Category.NEEDS_REVIEW: handle_review,
}


def route(email: EmailMessage, classification: Classification) -> None:
    """Dispatch an email to the handler registered for its category."""
    handler = AGENT_REGISTRY.get(classification.category)
    if handler is None:
        logger.debug(
            "No handler for category %s (message %s); skipping.",
            classification.category,
            email.id,
        )
        return
    handler(email, classification)
