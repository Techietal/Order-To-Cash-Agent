"""CollectionsState — runtime context loaded before the agent starts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CollectionsState:
    """Mutable state hydrated from the database before the agent run."""

    invoice_id: str

    # Populated by _load_context()
    customer_id: str = ""
    invoice: dict = field(default_factory=dict)
    customer: dict = field(default_factory=dict)
    segment: str = "Standard"
    tone: str = "firm"
    days_overdue: int = 0
    balance_due_inr: float = 0.0
    fdcpa_remaining: int = 2

    # Runtime tracking
    messages: list[Any] = field(default_factory=list)
    tools_log: list[dict] = field(default_factory=list)
    summary: str = ""
    hitl_payload: dict = field(default_factory=dict)
    error: Optional[str] = None
