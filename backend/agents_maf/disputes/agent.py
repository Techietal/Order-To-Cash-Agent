"""Disputes Agent runner (MAF v1.9.0, Groq) — see agents_maf/runtime.py for the driver."""
from __future__ import annotations

import logging

from database.postgres import get_pool
from agents_maf.llm import build_chat_client
from agents_maf.runtime import drive_agent, resume_run, get_run
from agents_maf.disputes.tools import DISPUTES_TOOLS, SOX_CREDIT_LIMIT_INR
from agents_maf.disputes.prompts import DISPUTES_SYSTEM

logger = logging.getLogger(__name__)
AGENT_NAME = "disputes_agent"
ENTITY_TYPE = "dispute"
HITL_EVENT = "DISPUTES_HITL"


def build_agent(use_fallback: bool = False):
    client = build_chat_client(use_fallback)
    return client.as_agent(
        name=AGENT_NAME,
        instructions=DISPUTES_SYSTEM.format(sox_limit=SOX_CREDIT_LIMIT_INR),
        tools=DISPUTES_TOOLS,
        default_options={"temperature": 0.2},
    )


async def _load(dispute_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        d = await db.fetchrow("SELECT * FROM portal_disputes WHERE dispute_id = $1", dispute_id)
    if not d:
        raise ValueError(f"Dispute {dispute_id} not found")
    return dict(d)


def _prompt(ctx: dict, extra: str = "") -> str:
    base = (
        f"Dispute {ctx['dispute_id']} | Customer {ctx.get('customer_id')} | "
        f"Invoice {ctx.get('invoice_id')} | Type {ctx.get('dispute_type')} | "
        f"Subject: {ctx.get('subject')}. Triage and resolve, or escalate."
    )
    return f"{base}\n\n{extra}".strip()


async def run(dispute_id: str, **_: object) -> dict:
    ctx = await _load(dispute_id)
    return await drive_agent(
        agent_name=AGENT_NAME, entity_type=ENTITY_TYPE, entity_id=dispute_id,
        customer_id=ctx.get("customer_id"), invoice_id=ctx.get("invoice_id"),
        build_agent=build_agent, prompt=_prompt(ctx), hitl_event_type=HITL_EVENT,
    )


async def resume(thread_id: str, decision: dict) -> dict:
    run_row = await get_run(thread_id)
    if not run_row:
        return {"thread_id": thread_id, "status": "error", "summary": "Run not found"}
    ctx = await _load(run_row["entity_id"])
    extra = (
        f"A human disputes manager reviewed the escalation and decided: "
        f"{decision}. Carry out that decision now using your tools."
    )
    return await resume_run(thread_id=thread_id, decision=decision,
                            build_agent=build_agent, prompt=_prompt(ctx, extra))
