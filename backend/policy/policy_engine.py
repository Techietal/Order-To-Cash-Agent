"""
O2C Agent v2.0 — Policy Engine (MAF Middleware)
Intercepts every agent tool call. <5ms overhead.
Enforces: ECOA, SOX, GDPR/PII, FDCPA, Credit Limit, Fraud Block rules.

FIX: Audit log now writes to DB via a per-request connection passed at call time,
     OR via the pool directly when no connection is provided.
"""

import logging
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class PolicyAction(str, Enum):
    PROCEED = "PROCEED"
    BLOCK = "BLOCK"
    REQUIRE_HITL = "REQUIRE_HITL"
    MASK_PII = "MASK_PII"
    LOG_ONLY = "LOG_ONLY"
    RATE_LIMIT = "RATE_LIMIT"


class PolicyViolation(Exception):
    """Raised when a blocking policy is violated."""
    def __init__(self, rule_id: str, message: str):
        self.rule_id = rule_id
        self.message = message
        super().__init__(f"[{rule_id}] {message}")


PII_FIELDS = {"address", "billing_address", "shipping_address", "phone", "email", "contact_name"}


class PolicyEngine:
    """
    MAF 1.0 Middleware Filter — Policy Engine.
    Intercepts all agent tool calls before execution.
    Audit log writes directly to PostgreSQL pool — no stale connection needed.
    """

    def __init__(self, settings=None):
        from config import settings as cfg
        self.settings = settings or cfg

    async def evaluate(
        self,
        agent_name: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        db=None,   # optional per-request connection; falls back to pool
    ) -> Dict[str, Any]:
        """
        Evaluate all applicable policy rules for a tool call.
        Returns: {action, flags, masked_args}
        """
        flags = []
        masked_args = dict(tool_args)
        ctx = context or {}

        # ── RULE-001: ECOA Credit Audit ──────────────────────────────────
        if tool_name in ("run_credit_check", "update_credit_decision", "persist_order"):
            flags.append("RULE-001_ECOA_AUDIT")
            await self._audit_log(agent_name, tool_name, "ECOA_CREDIT_DECISION", masked_args, ctx, db)

        # ── RULE-002: SOX Dual Approval (credit memo / write-off > 50K) ──
        amount = float(tool_args.get("amount_inr", tool_args.get("credit_memo_amount_inr", 0)))
        if tool_name in ("issue_credit_memo", "approve_write_off") and amount > self.settings.hitl_gate_sox_amount_inr:
            flags.append("RULE-002_SOX_DUAL_APPROVAL")
            await self._audit_log(agent_name, tool_name, "SOX_HITL_TRIGGERED", masked_args, ctx, db)
            return {"action": PolicyAction.REQUIRE_HITL, "flags": flags, "masked_args": masked_args,
                    "hitl_reason": f"SOX: Credit memo/write-off ₹{amount:,.0f} > ₹{self.settings.hitl_gate_sox_amount_inr:,.0f} requires Finance Controller approval"}

        # ── RULE-003: GDPR PII Masking ────────────────────────────────────
        masked_args = self._mask_pii_fields(masked_args)
        if any(k in tool_args for k in PII_FIELDS):
            flags.append("RULE-003_PII_MASKED")

        # ── RULE-004: Credit Limit Block ──────────────────────────────────
        order_amount = float(ctx.get("order_amount_inr", 0))
        credit_limit = float(ctx.get("credit_limit_inr", float("inf")))
        open_ar = float(ctx.get("open_ar_balance_inr", 0))
        if credit_limit > 0 and order_amount > 0 and credit_limit < float("inf"):
            utilization = (open_ar + order_amount) / credit_limit
            if utilization > self.settings.credit_limit_hitl_threshold:
                flags.append("RULE-004_CREDIT_LIMIT_HITL")
                await self._audit_log(agent_name, tool_name, "CREDIT_LIMIT_HITL", masked_args, ctx, db)
                return {"action": PolicyAction.REQUIRE_HITL, "flags": flags, "masked_args": masked_args,
                        "hitl_reason": f"Credit utilization {utilization:.0%} exceeds {self.settings.credit_limit_hitl_threshold:.0%} threshold"}

        # ── RULE-005: Fraud Block ─────────────────────────────────────────
        fraud_prob = float(ctx.get("fraud_probability", 0))
        if fraud_prob > self.settings.fraud_block_threshold:
            flags.append("RULE-005_FRAUD_BLOCK")
            await self._audit_log(agent_name, tool_name, "FRAUD_BLOCK", masked_args, ctx, db)
            return {"action": PolicyAction.BLOCK, "flags": flags, "masked_args": masked_args,
                    "block_reason": f"Fraud probability {fraud_prob:.2%} > {self.settings.fraud_block_threshold:.0%} threshold — order blocked pending HITL review"}

        # ── RULE-007: FDCPA Dunning Rate Limit ───────────────────────────
        if tool_name in ("send_dunning_email", "send_dunning_sms"):
            weekly_count = int(ctx.get("dunning_contacts_this_week", 0))
            if weekly_count >= self.settings.dunning_max_contacts_per_week:
                flags.append("RULE-007_FDCPA_RATE_LIMIT")
                return {"action": PolicyAction.RATE_LIMIT, "flags": flags, "masked_args": masked_args,
                        "rate_limit_reason": f"FDCPA: Max {self.settings.dunning_max_contacts_per_week} contacts/week reached for customer"}

        # ── RULE-008: Inventory Backorder Gate ───────────────────────────
        # Evaluates when tool_name == "inventory_check" OR when the caller
        # passes an inventory_verdict in context (e.g. from check_and_reserve).
        # NOTE: This rule reads from context only — it never calls inventory_service.
        inventory_verdict = ctx.get("inventory_verdict", "")
        if tool_name == "inventory_check" or inventory_verdict:
            eta_reliability = ctx.get("eta_reliability", "unknown")

            if inventory_verdict == "FULL_BACKORDER":
                flags.append("RULE-008_FULL_BACKORDER")
                await self._audit_log(agent_name, tool_name, "INVENTORY_FULL_BACKORDER", masked_args, ctx, db)
                if eta_reliability == "unknown":
                    return {
                        "action": PolicyAction.REQUIRE_HITL,
                        "flags": flags,
                        "masked_args": masked_args,
                        "hitl_reason": "BACKORDER_NO_ETA: Full backorder with no confirmed PO or lead-time estimate — requires human review",
                    }
                return {"action": PolicyAction.PROCEED, "flags": flags, "masked_args": masked_args}

            elif inventory_verdict == "PARTIALLY_RESERVED":
                flags.append("RULE-008_PARTIAL_FULFILLMENT")
                await self._audit_log(agent_name, tool_name, "INVENTORY_PARTIAL_RESERVATION", masked_args, ctx, db)
                if eta_reliability == "unknown":
                    return {
                        "action": PolicyAction.REQUIRE_HITL,
                        "flags": flags,
                        "masked_args": masked_args,
                        "hitl_reason": "BACKORDER_NO_ETA: Partial backorder with no confirmed PO or lead-time estimate — requires human review",
                    }
                return {"action": PolicyAction.PROCEED, "flags": flags, "masked_args": masked_args}

            elif inventory_verdict == "FULLY_RESERVED":
                # Full reservation — no backorder flag needed, proceed normally
                pass

        # ── Audit all tool calls ───────────────────────────────────────────
        await self._audit_log(agent_name, tool_name, "TOOL_CALL", masked_args, ctx, db)

        return {"action": PolicyAction.PROCEED, "flags": flags, "masked_args": masked_args}

    def _mask_pii_fields(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Mask PII fields in tool call args for audit log."""
        masked = {}
        for k, v in args.items():
            if k.lower() in PII_FIELDS:
                masked[k] = "[MASKED]"
            else:
                masked[k] = v
        return masked

    async def _audit_log(
        self, agent_name: str, tool_name: str, event_type: str,
        args: Dict[str, Any], ctx: Dict[str, Any], db=None
    ):
        """Write to audit log (append-only PostgreSQL table).
        
        Uses the per-request db connection if provided, otherwise acquires from pool.
        This ensures audit writes always reach the DB regardless of how policy_engine is called.
        """
        details = json.dumps({"args_keys": list(args.keys()), "flags": ctx.get("flags", [])})
        sql = """INSERT INTO audit_log (event_type, agent_name, customer_id, order_id, action, details, policy_rule_id)
                 VALUES ($1, $2, $3, $4, $5, $6, $7)"""
        params = (
            event_type, agent_name,
            ctx.get("customer_id", ""),
            ctx.get("order_id", ""),
            tool_name,
            details,
            next((f for f in ctx.get("flags", []) if "RULE-" in f), None),
        )

        try:
            if db is not None:
                await db.execute(sql, *params)
            else:
                # Acquire from pool directly
                from database.postgres import get_pool
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(sql, *params)
        except Exception as e:
            logger.error(f"Audit log write failed: {e}")


# Singleton instance for import
policy_engine = PolicyEngine()
