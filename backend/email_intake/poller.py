"""One polling cycle: fetch, dedup, classify, route, and record."""

from __future__ import annotations

import logging

from . import router
from .classifier import classify
from .gmail_client import GmailClient
from .models import Category
from .state import StateStore

logger = logging.getLogger(__name__)


def run_cycle() -> None:
    """Run a single intake cycle over unprocessed Gmail messages."""
    gmail = GmailClient()
    state = StateStore()

    emails = gmail.fetch_unprocessed()
    logger.info("Fetched %d unprocessed message(s).", len(emails))

    for email in emails:
        if state.already_seen(email.id):
            logger.debug("Skipping already-seen message %s.", email.id)
            continue

        try:
            classification = classify(email)

            # OTHER is intentionally not routed.
            if classification.category is not Category.OTHER:
                router.route(email, classification)

            # Only mark processed after successful handling.
            gmail.mark_processed(email.id)

            # Mark as read only for actionable O2C categories.
            if classification.category in (
                Category.ORDER,
                Category.PAYMENT,
                Category.DISPUTE,
            ):
                gmail.mark_read(email.id)

            state.record(email.id, classification.category)
            logger.info(
                "Processed message %s as %s.",
                email.id,
                classification.category.value,
            )
        except Exception:
            # Leave the message UNprocessed so it retries next cycle.
            logger.exception(
                "Failed to process message %s; will retry next cycle.",
                email.id,
            )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_cycle()
