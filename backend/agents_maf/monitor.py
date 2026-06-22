"""Proactive monitor — starts agents on its own when DB conditions are met.

This is the autonomy layer on top of the agents: instead of waiting for an API
call, a single long-lived coroutine (launched from the FastAPI lifespan) scans
the database every ``proactive_poll_seconds`` and triggers the relevant agent for
work that needs attention. It also drains the agent-to-agent handoff queue.

Guards against runaway cost:
  * ``proactive_max_per_cycle``  caps how many agents start per scan.
  * ``proactive_cooldown_minutes`` prevents re-triggering the same entity.
  * Only entities with no active/recent run are picked up.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from config import settings
from database.postgres import get_pool

logger = logging.getLogger(__name__)


async def _already_handled(db, agent_name: str, entity_id: str, since: datetime) -> bool:
    """True if this agent already has an active or recent run for the entity."""
    row = await db.fetchval(
        """SELECT 1 FROM agent_runs
           WHERE agent_name = $1
             AND (entity_id = $2 OR invoice_id = $2)
             AND (status IN ('running', 'paused_hitl') OR started_at >= $3)
           LIMIT 1""",
        agent_name, entity_id, since,
    )
    return bool(row)


async def _scan_candidates(db) -> list[dict]:
    """Return prioritized work items: {key, agent_name, entity_id, extra}."""
    candidates: list[dict] = []

    # 1) Pending KYC requests → KYC agent
    kyc = await db.fetch(
        "SELECT kyc_id FROM customer_kyc_requests WHERE status = 'pending' "
        "ORDER BY submitted_at LIMIT 5"
    )
    for r in kyc:
        candidates.append({"key": "kyc", "agent_name": "kyc_agent",
                           "entity_id": r["kyc_id"], "extra": {}})

    # 2) Pending portal disputes → Disputes agent
    disp = await db.fetch(
        "SELECT dispute_id FROM portal_disputes WHERE status = 'pending_admin' "
        "ORDER BY created_at LIMIT 5"
    )
    for r in disp:
        candidates.append({"key": "disputes", "agent_name": "disputes_agent",
                           "entity_id": r["dispute_id"], "extra": {}})

    # 3) Overdue invoices with no dunning in the last 7 days → Collections agent
    overdue = await db.fetch(
        """SELECT i.invoice_id
           FROM invoices i
           WHERE i.balance_due_inr > 0
             AND i.days_overdue >= $1
             AND NOT EXISTS (
                 SELECT 1 FROM dunning_log d
                 WHERE d.invoice_id = i.invoice_id
                   AND d.sent_at >= NOW() - INTERVAL '7 days'
             )
           ORDER BY i.days_overdue DESC LIMIT 5""",
        settings.proactive_overdue_days,
    )
    for r in overdue:
        candidates.append({"key": "collections", "agent_name": "collections_agent",
                           "entity_id": r["invoice_id"], "extra": {}})

    return candidates


async def _run_one_cycle() -> int:
    """One monitor pass: drain handoffs, then trigger due agents. Returns count started."""
    from agents_maf.registry import dispatch_run
    from agents_maf.runtime import process_pending_handoffs

    cap = settings.proactive_max_per_cycle
    since = datetime.utcnow() - timedelta(minutes=settings.proactive_cooldown_minutes)

    # Agent chaining: run any queued handoffs first.
    try:
        n = await process_pending_handoffs(max_items=cap)
        if n:
            logger.info("Processed %d agent handoff(s)", n)
    except Exception:  # noqa: BLE001
        logger.exception("Handoff processing failed")

    pool = await get_pool()
    async with pool.acquire() as db:
        candidates = await _scan_candidates(db)

    started = 0
    for c in candidates:
        if started >= cap:
            break
        pool = await get_pool()
        async with pool.acquire() as db:
            if await _already_handled(db, c["agent_name"], c["entity_id"], since):
                continue
        try:
            logger.info("Proactive trigger: %s for %s", c["key"], c["entity_id"])
            await dispatch_run(c["key"], c["entity_id"], **c["extra"])
            started += 1
        except Exception:  # noqa: BLE001
            logger.exception("Proactive trigger failed for %s %s", c["key"], c["entity_id"])
    return started


async def proactive_monitor(poll_seconds: int | None = None) -> None:
    """Long-lived loop that proactively starts agents. Cancelled on shutdown."""
    if not settings.proactive_monitor_enabled:
        logger.info("Proactive monitor disabled (proactive_monitor_enabled=False)")
        return
    interval = poll_seconds or settings.proactive_poll_seconds
    logger.info("Proactive agent monitor started (poll=%ss, cap=%s/cycle)",
                interval, settings.proactive_max_per_cycle)
    # Small initial delay so the DB pool and storage are fully ready.
    await asyncio.sleep(20)
    while True:
        try:
            await _run_one_cycle()
        except asyncio.CancelledError:
            logger.info("Proactive monitor stopping")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Proactive monitor cycle failed")
        await asyncio.sleep(interval)
