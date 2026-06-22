"""MAF tool library for the Credit Agent.

Wraps the fraud + credit-risk models and records ECOA-auditable decisions in
credit_decisions.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated

from agent_framework import tool

from agents_maf.runtime import _get_db, log_hitl

logger = logging.getLogger(__name__)

AGENT_NAME = "credit_agent"
PD_LOW = 0.20
PD_HIGH = 0.55


@tool(name="get_customer_credit_profile", description="Credit tier, limit, open AR and history for a customer.")
async def get_customer_credit_profile(
    customer_id: Annotated[str, "Customer ID"],
) -> dict:
    """Return the credit-relevant attributes for a customer."""
    async with await _get_db() as db:
        row = await db.fetchrow(
            """SELECT credit_tier, credit_limit_inr, open_ar_balance_inr, avg_dso_days,
                      missed_payments_12m, account_age_months, payment_terms_days, industry
               FROM customers WHERE customer_id = $1""",
            customer_id,
        )
    if not row:
        return {"found": False}
    return {"found": True, **{k: row[k] for k in row.keys()}}


@tool(name="screen_fraud", description="Run fraud screening for an order amount against a customer profile.")
async def screen_fraud(
    customer_id: Annotated[str, "Customer ID"],
    order_amount_inr: Annotated[float, "Order / credit amount requested"],
) -> dict:
    """Return fraud_probability + verdict from the fraud model."""
    async with await _get_db() as db:
        c = await db.fetchrow(
            "SELECT account_age_months, avg_dso_days, missed_payments_12m, "
            "open_ar_balance_inr, credit_limit_inr FROM customers WHERE customer_id = $1",
            customer_id,
        )
    if not c:
        return {"fraud_verdict": "REVIEW", "fraud_probability": 1.0, "reason": "unknown customer"}

    from ml.model_placeholders import predict_fraud
    open_ar_ratio = float(c["open_ar_balance_inr"] or 0) / max(float(c["credit_limit_inr"] or 100000), 1)
    return predict_fraud({
        "amount_inr": float(order_amount_inr),
        "customer_age_months": int(c["account_age_months"] or 12),
        "avg_days_late": max(0.0, float(c["avg_dso_days"] or 30) - 30),
        "missed_payments": int(c["missed_payments_12m"] or 0),
        "open_ar_ratio": open_ar_ratio,
        "is_new_customer": int(c["account_age_months"] or 12) < 6,
        "hour_of_day": datetime.utcnow().hour,
        "channel": "portal",
    })


@tool(name="assess_credit_risk", description="Score credit risk (LOW/MEDIUM/HIGH) + probability of default.")
async def assess_credit_risk(
    customer_id: Annotated[str, "Customer ID"],
    order_amount_inr: Annotated[float, "Order / credit amount requested"],
) -> dict:
    """Return credit_risk_class + pd_score from the credit model."""
    async with await _get_db() as db:
        c = await db.fetchrow(
            "SELECT credit_tier, credit_limit_inr, open_ar_balance_inr, avg_dso_days, "
            "missed_payments_12m, account_age_months, industry FROM customers WHERE customer_id = $1",
            customer_id,
        )
    if not c:
        return {"credit_risk_class": "HIGH", "pd_score": 1.0, "reason": "unknown customer"}

    from ml.model_placeholders import predict_credit_risk
    tier_letter = (c["credit_tier"] or "C")
    payment_tier_num = {"A": 1, "B": 2, "C": 3, "D": 4}.get(tier_letter, 3)
    return predict_credit_risk({
        "order_value_inr": float(order_amount_inr),
        "credit_limit_inr": float(c["credit_limit_inr"] or 100000),
        "open_ar_balance_inr": float(c["open_ar_balance_inr"] or 0),
        "avg_days_late": max(0.0, float(c["avg_dso_days"] or 30) - 30),
        "payment_tier": payment_tier_num,
        "missed_payment_count": int(c["missed_payments_12m"] or 0),
        "account_age_months": int(c["account_age_months"] or 12),
        "industry_segment": c["industry"] or "general",
        "credit_tier": tier_letter,
    })


@tool(name="propose_terms", description="Recommend a credit limit and payment terms from risk signals.")
async def propose_terms(
    credit_risk_class: Annotated[str, "LOW | MEDIUM | HIGH"],
    pd_score: Annotated[float, "Probability of default 0-1"],
    current_limit_inr: Annotated[float, "Current credit limit"],
) -> dict:
    """Pure rule-based terms recommendation (no DB write)."""
    terms_map = {"LOW": 45, "MEDIUM": 30, "HIGH": 15}
    mult_map = {"LOW": 1.25, "MEDIUM": 1.0, "HIGH": 0.6}
    risk = (credit_risk_class or "MEDIUM").upper()
    net_terms = terms_map.get(risk, 30)
    recommended_limit = round(float(current_limit_inr or 0) * mult_map.get(risk, 1.0), 2)
    return {
        "recommended_net_terms_days": net_terms,
        "recommended_credit_limit_inr": recommended_limit,
        "note": f"{risk} risk, PD {pd_score:.2f}",
    }


@tool(name="record_credit_decision", description="Persist an ECOA-auditable credit decision.")
async def record_credit_decision(
    customer_id: Annotated[str, "Customer ID"],
    decision: Annotated[str, "approved | denied | hitl"],
    credit_risk_class: Annotated[str, "LOW | MEDIUM | HIGH"],
    pd_score: Annotated[float, "Probability of default 0-1"],
    decision_reason: Annotated[str, "Plain-language ECOA reason"],
    order_amount_inr: Annotated[float, "Order / credit amount"] = 0.0,
    recommended_credit_limit_inr: Annotated[float, "Recommended limit"] = 0.0,
    order_id: Annotated[str, "Order ID if applicable"] = "",
) -> dict:
    """Insert a credit_decisions row (decision audit trail)."""
    decision_id = f"CRD-{datetime.utcnow().strftime('%y%m%d%H%M%S%f')[:16]}"  # <= 20 chars
    async with await _get_db() as db:
        prof = await db.fetchrow(
            "SELECT credit_tier, credit_limit_inr, open_ar_balance_inr FROM customers WHERE customer_id = $1",
            customer_id,
        )
        await db.execute(
            """INSERT INTO credit_decisions
                   (decision_id, order_id, customer_id, credit_tier, credit_limit_inr,
                    open_ar_balance_inr, order_amount_inr, credit_risk_class, pd_score,
                    recommended_credit_limit_inr, decision, decision_reason,
                    ecoa_audit_logged, hitl_required, processed_by_agent)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,TRUE,$13,'credit_agent')""",
            decision_id, order_id or None, customer_id,
            (prof["credit_tier"] if prof else None),
            (float(prof["credit_limit_inr"]) if prof and prof["credit_limit_inr"] else None),
            (float(prof["open_ar_balance_inr"]) if prof and prof["open_ar_balance_inr"] else None),
            float(order_amount_inr), credit_risk_class, float(pd_score),
            float(recommended_credit_limit_inr), decision, decision_reason,
            decision == "hitl",
        )
        await db.execute(
            """INSERT INTO audit_log
                   (event_type, agent_name, customer_id, action, details,
                    actor_type, actor_username, actor_role)
               VALUES ('CREDIT_DECISION','credit_agent',$1,'record_credit_decision',
                       $2::jsonb,'ai_agent','credit_agent','ai')""",
            customer_id,
            json.dumps({"decision_id": decision_id, "decision": decision,
                        "credit_risk_class": credit_risk_class, "pd_score": pd_score,
                        "reason": decision_reason}),
        )
    return {"recorded": True, "decision_id": decision_id, "decision": decision}


@tool(name="escalate_to_hitl", description="Escalate a borderline credit case to a human (pauses the run).")
async def escalate_to_hitl(
    customer_id: Annotated[str, "Customer ID"],
    reason: Annotated[str, "Why escalating"],
    suggested_action: Annotated[str, "approve | deny | request_collateral"] = "",
) -> dict:
    """Log a HITL escalation keyed on the customer_id."""
    return await log_hitl(
        agent_name=AGENT_NAME, event_type="CREDIT_HITL",
        entity_id=customer_id, customer_id=customer_id,
        reason=reason, suggested_action=suggested_action,
    )


CREDIT_TOOLS = [
    get_customer_credit_profile,
    screen_fraud,
    assess_credit_risk,
    propose_terms,
    record_credit_decision,
    escalate_to_hitl,
]
