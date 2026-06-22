"""KYC Agent runner (MAF v1.9.0, Groq)."""
from __future__ import annotations

import logging

from database.postgres import get_pool
from agents_maf.llm import build_chat_client
from agents_maf.runtime import drive_agent, resume_run, get_run
from agents_maf.kyc.tools import KYC_TOOLS
from agents_maf.kyc.prompts import KYC_SYSTEM

logger = logging.getLogger(__name__)
AGENT_NAME = "kyc_agent"
ENTITY_TYPE = "kyc"
HITL_EVENT = "KYC_HITL"


def build_agent(use_fallback: bool = False):
    client = build_chat_client(use_fallback)
    return client.as_agent(
        name=AGENT_NAME,
        instructions=KYC_SYSTEM,
        tools=KYC_TOOLS,
        default_options={"temperature": 0.0},
    )


async def _load(kyc_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        k = await db.fetchrow(
            "SELECT kyc_id, company_name, gstin, email, status FROM customer_kyc_requests "
            "WHERE kyc_id = $1",
            kyc_id,
        )
    if not k:
        raise ValueError(f"KYC request {kyc_id} not found")
    return dict(k)


def _prompt(ctx: dict, extra: str = "") -> str:
    base = (
        f"KYC {ctx['kyc_id']} | Company '{ctx.get('company_name')}' | "
        f"GSTIN {ctx.get('gstin')} | Email {ctx.get('email')}. "
        f"Verify and approve, reject, or escalate."
    )
    return f"{base}\n\n{extra}".strip()


async def run(kyc_id: str, **_: object) -> dict:
    ctx = await _load(kyc_id)
    return await drive_agent(
        agent_name=AGENT_NAME, entity_type=ENTITY_TYPE, entity_id=kyc_id,
        customer_id=None, build_agent=build_agent,
        prompt=_prompt(ctx), hitl_event_type=HITL_EVENT,
    )


async def resume(thread_id: str, decision: dict) -> dict:
    run_row = await get_run(thread_id)
    if not run_row:
        return {"thread_id": thread_id, "status": "error", "summary": "Run not found"}
    ctx = await _load(run_row["entity_id"])
    extra = (
        f"A human compliance officer reviewed the case and decided: {decision}. "
        f"Carry out that decision now using approve_kyc or reject_kyc."
    )
    return await resume_run(
        thread_id=thread_id, decision=decision, build_agent=build_agent,
        prompt=_prompt(ctx, extra),
    )
