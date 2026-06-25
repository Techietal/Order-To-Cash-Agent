"""Credit Agent runner (MAF v1.9.0, Ollama Cloud)."""
from __future__ import annotations

import logging

from database.postgres import get_pool
from agents_maf.llm import build_chat_client
from agents_maf.runtime import drive_agent, resume_run, get_run
from agents_maf.credit.tools import CREDIT_TOOLS, PD_LOW, PD_HIGH
from agents_maf.credit.prompts import CREDIT_SYSTEM

logger = logging.getLogger(__name__)
AGENT_NAME = "credit_agent"
ENTITY_TYPE = "customer"
HITL_EVENT = "CREDIT_HITL"


def build_agent(use_fallback: bool = False):
    client = build_chat_client(use_fallback)
    return client.as_agent(
        name=AGENT_NAME,
        instructions=CREDIT_SYSTEM.format(pd_low=PD_LOW, pd_high=PD_HIGH),
        tools=CREDIT_TOOLS,
        default_options={"temperature": 0.1},
    )


async def _load(customer_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        c = await db.fetchrow(
            "SELECT customer_id, company_name, credit_tier, credit_limit_inr "
            "FROM customers WHERE customer_id = $1",
            customer_id,
        )
    if not c:
        raise ValueError(f"Customer {customer_id} not found")
    return dict(c)


def _prompt(ctx: dict, order_amount_inr: float, extra: str = "") -> str:
    base = (
        f"Customer {ctx['customer_id']} ({ctx.get('company_name','?')}) | "
        f"Tier {ctx.get('credit_tier')} | Limit \u20b9{float(ctx.get('credit_limit_inr') or 0):,.0f}. "
        f"They request credit for an order of \u20b9{order_amount_inr:,.0f}. "
        f"Screen, assess, decide, or escalate."
    )
    return f"{base}\n\n{extra}".strip()


async def run(customer_id: str, order_amount_inr: float = 0.0,
              order_id: str = "", **_: object) -> dict:
    ctx = await _load(customer_id)
    if not order_amount_inr:
        order_amount_inr = float(ctx.get("credit_limit_inr") or 100000) * 0.5
    return await drive_agent(
        agent_name=AGENT_NAME, entity_type=ENTITY_TYPE, entity_id=customer_id,
        customer_id=customer_id, build_agent=build_agent,
        prompt=_prompt(ctx, order_amount_inr), hitl_event_type=HITL_EVENT,
    )


async def resume(thread_id: str, decision: dict) -> dict:
    run_row = await get_run(thread_id)
    if not run_row:
        return {"thread_id": thread_id, "status": "error", "summary": "Run not found"}
    ctx = await _load(run_row["entity_id"])
    amount = float(ctx.get("credit_limit_inr") or 100000) * 0.5
    extra = (
        f"A human credit controller reviewed the case and decided: {decision}. "
        f"Record that decision with record_credit_decision and a clear ECOA reason."
    )
    return await resume_run(
        thread_id=thread_id, decision=decision, build_agent=build_agent,
        prompt=_prompt(ctx, amount, extra),
    )
