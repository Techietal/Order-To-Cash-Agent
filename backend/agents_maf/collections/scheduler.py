"""In-process follow-up sweeper — the no-Celery replacement for Celery beat.

A single long-lived coroutine, launched from the FastAPI lifespan, polls the
`followups` table for due rows and re-runs the collections agent for each.
"""
from __future__ import annotations

import asyncio
import logging

from database.postgres import get_pool

logger = logging.getLogger(__name__)


async def followup_sweeper(poll_seconds: int = 300) -> None:
    """Run due follow-ups on a fixed interval until cancelled."""
    # Imported lazily so a missing agent module never blocks app startup.
    from agents_maf.collections.agent import run_collections_agent

    logger.info("Follow-up sweeper started (poll=%ss)", poll_seconds)
    while True:
        try:
            pool = await get_pool()
            async with pool.acquire() as db:
                due = await db.fetch(
                    """SELECT followup_id, invoice_id FROM followups
                       WHERE status = 'pending' AND due_at <= NOW()
                       ORDER BY due_at LIMIT 20"""
                )
            for row in due:
                try:
                    await run_collections_agent(row["invoice_id"], triggered_by="followup")
                except Exception:
                    logger.exception("Follow-up run failed for %s", row["invoice_id"])
                    continue
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE followups SET status = 'done' WHERE followup_id = $1",
                        row["followup_id"],
                    )
        except asyncio.CancelledError:
            logger.info("Follow-up sweeper stopping")
            raise
        except Exception:
            logger.exception("Follow-up sweeper iteration failed")
        await asyncio.sleep(poll_seconds)
