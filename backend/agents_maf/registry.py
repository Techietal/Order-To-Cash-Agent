"""Central registry that maps an agent key to its run entrypoint.

Used by the proactive monitor and the handoff processor to start any agent
generically. Imports are lazy (inside dispatch) to avoid circular imports —
runtime.py imports this module, and the agent modules import runtime.py.
"""
from __future__ import annotations

import importlib
from typing import Any

# key -> (module path, run-callable name, first positional arg name, agent_name)
AGENT_RUN = {
    "collections": ("agents_maf.collections.agent", "run_collections_agent", "invoice_id", "collections_agent"),
    "disputes":    ("agents_maf.disputes.agent",      "run", "dispute_id",  "disputes_agent"),
    "cash":        ("agents_maf.cash_application.agent", "run", "invoice_id", "cash_application_agent"),
    "credit":      ("agents_maf.credit.agent",          "run", "customer_id", "credit_agent"),
    "kyc":         ("agents_maf.kyc.agent",             "run", "kyc_id",     "kyc_agent"),
}

# agent_name -> key (reverse lookup)
AGENT_NAME_TO_KEY = {v[3]: k for k, v in AGENT_RUN.items()}


def agent_name_for(key: str) -> str:
    entry = AGENT_RUN.get(key)
    return entry[3] if entry else key


async def dispatch_run(key: str, entity_id: str, **extra: Any) -> dict:
    """Start the agent identified by ``key`` for ``entity_id``.

    ``extra`` keyword args are forwarded to the agent's run() (e.g.
    remittance_amount for cash, order_amount_inr for credit).
    """
    entry = AGENT_RUN.get(key)
    if not entry:
        raise ValueError(f"Unknown agent key '{key}'")
    module_path, func_name, arg_name, _ = entry
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    return await func(**{arg_name: entity_id, **extra})
