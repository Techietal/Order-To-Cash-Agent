"""Cash Application Agent runner (MAF v1.9.0, Groq)."""
from __future__ import annotations

import logging

from database.postgres import get_pool
from agents_maf.llm import build_chat_client
from agents_maf.runtime import drive_agent, resume_run, get_run
from agents_maf.cash_application.tools import (
    CASH_TOOLS, AUTO_THRESHOLD, REVIEW_THRESHOLD,
)
from agents_maf.cash_application.prompts import CASH_SYSTEM

logger = logging.getLogger(__name__)
AGENT_NAME = "cash_application_agent"
ENTITY_TYPE = "invoice"
HITL_EVENT = "CASH_HITL"


def build_agent(use_fallback: bool = False):
    client = build_chat_client(use_fallback)
    return client.as_agent(
        name=AGENT_NAME,
        instructions=CASH_SYSTEM.format(
            auto_threshold=AUTO_THRESHOLD, review_threshold=REVIEW_THRESHOLD
        ),
        tools=CASH_TOOLS,
        default_options={"temperature": 0.1},
    )


async def _load(invoice_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        inv = await db.fetchrow(
            "SELECT invoice_id, customer_id, balance_due_inr FROM invoices WHERE invoice_id = $1",
            invoice_id,
        )
    if not inv:
        raise ValueError(f"Invoice {invoice_id} not found")
    return dict(inv)


def _prompt(ctx: dict, remittance_amount: float, remittance_text: str, extra: str = "") -> str:
    base = (
        f"Invoice {ctx['invoice_id']} | Customer {ctx.get('customer_id')} | "
        f"Open balance \u20b9{float(ctx.get('balance_due_inr') or 0):,.0f}. "
        f"A remittance of \u20b9{remittance_amount:,.0f} arrived"
        + (f" with note '{remittance_text}'." if remittance_text else ".")
        + " Match it and post the payment, or escalate."
    )
    return f"{base}\n\n{extra}".strip()


async def run(invoice_id: str, remittance_amount: float = 0.0,
              remittance_text: str = "", **_: object) -> dict:
    ctx = await _load(invoice_id)
    if not remittance_amount:
        remittance_amount = float(ctx.get("balance_due_inr") or 0)
    return await drive_agent(
        agent_name=AGENT_NAME, entity_type=ENTITY_TYPE, entity_id=invoice_id,
        customer_id=ctx.get("customer_id"), invoice_id=invoice_id,
        build_agent=build_agent,
        prompt=_prompt(ctx, remittance_amount, remittance_text),
        hitl_event_type=HITL_EVENT,
    )


async def resume(thread_id: str, decision: dict) -> dict:
    run_row = await get_run(thread_id)
    if not run_row:
        return {"thread_id": thread_id, "status": "error", "summary": "Run not found"}
    ctx = await _load(run_row["entity_id"])
    amount = float(ctx.get("balance_due_inr") or 0)
    extra = (
        f"A human reviewed the unmatched payment and decided: {decision}. "
        f"Carry out that decision now using your tools."
    )
    return await resume_run(
        thread_id=thread_id, decision=decision, build_agent=build_agent,
        prompt=_prompt(ctx, amount, "", extra),
    )
