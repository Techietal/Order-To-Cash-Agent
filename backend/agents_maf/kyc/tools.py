"""MAF tool library for the KYC Agent.

Validates Indian GSTINs (format + official checksum), screens a sanctions
denylist, and approves/rejects customer_kyc_requests.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Annotated

from agent_framework import tool

from agents_maf.runtime import _get_db, log_hitl

logger = logging.getLogger(__name__)

AGENT_NAME = "kyc_agent"

# GSTIN: 2-digit state + 10-char PAN + entity digit + 'Z' + checksum char.
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_GST_CODES = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Minimal illustrative sanctions denylist (substring match, case-insensitive).
_SANCTIONS_DENYLIST = {
    "shell global holdings", "redline traders", "blacklist corp",
    "sanctioned entity", "ofac restricted",
}


def _gstin_checksum_ok(gstin: str) -> bool:
    """Validate the GSTIN's 15th checksum character per the official algorithm."""
    if len(gstin) != 15:
        return False
    factor = 2
    total = 0
    mod = len(_GST_CODES)
    for ch in gstin[:14][::-1]:
        idx = _GST_CODES.find(ch)
        if idx < 0:
            return False
        addend = idx * factor
        addend = (addend // mod) + (addend % mod)
        total += addend
        factor = 1 if factor == 2 else 2
    check_char = _GST_CODES[(mod - (total % mod)) % mod]
    return check_char == gstin[14]


@tool(name="get_kyc_request", description="Fetch a customer KYC onboarding request.")
async def get_kyc_request(
    kyc_id: Annotated[str, "KYC request ID"],
) -> dict:
    """Return the submitted KYC fields."""
    async with await _get_db() as db:
        row = await db.fetchrow(
            "SELECT kyc_id, company_name, contact_name, email, gstin, pan_number, "
            "business_type, state, status FROM customer_kyc_requests WHERE kyc_id = $1",
            kyc_id,
        )
    if not row:
        return {"found": False}
    return {"found": True, **{k: row[k] for k in row.keys()}}


@tool(name="verify_gstin", description="Validate an Indian GSTIN (format + checksum).")
async def verify_gstin(
    gstin: Annotated[str, "15-character GSTIN"],
) -> dict:
    """Return validity, format check, and checksum check for a GSTIN."""
    g = (gstin or "").strip().upper()
    format_ok = bool(_GSTIN_RE.match(g))
    checksum_ok = _gstin_checksum_ok(g) if format_ok else False
    return {
        "gstin": g,
        "format_ok": format_ok,
        "checksum_ok": checksum_ok,
        "valid": format_ok and checksum_ok,
        "state_code": g[:2] if format_ok else None,
    }


@tool(name="check_sanctions", description="Screen a company name against the sanctions denylist.")
async def check_sanctions(
    company_name: Annotated[str, "Company / legal entity name"],
) -> dict:
    """Return whether the name matches any denylisted entity."""
    name = (company_name or "").strip().lower()
    hit = next((d for d in _SANCTIONS_DENYLIST if d in name), None)
    return {"company_name": company_name, "sanctions_hit": hit is not None,
            "matched_entry": hit}


@tool(name="approve_kyc", description="Approve a KYC request (verified, no sanctions).")
async def approve_kyc(
    kyc_id: Annotated[str, "KYC request ID"],
    note: Annotated[str, "Approval note"] = "",
) -> dict:
    """Set the KYC request status to approved."""
    async with await _get_db() as db:
        await db.execute(
            "UPDATE customer_kyc_requests SET status = 'approved', reviewer = 'kyc_agent', "
            "review_notes = $1, reviewed_at = NOW() WHERE kyc_id = $2",
            note, kyc_id,
        )
        await db.execute(
            """INSERT INTO audit_log (event_type, agent_name, action, details,
                                      actor_type, actor_username, actor_role)
               VALUES ('KYC_APPROVED','kyc_agent','approve_kyc',$1::jsonb,
                       'ai_agent','kyc_agent','ai')""",
            json.dumps({"kyc_id": kyc_id, "note": note}),
        )
    return {"approved": True, "kyc_id": kyc_id}


@tool(name="reject_kyc", description="Reject a KYC request (e.g. invalid GSTIN).")
async def reject_kyc(
    kyc_id: Annotated[str, "KYC request ID"],
    reason: Annotated[str, "Rejection reason"],
) -> dict:
    """Set the KYC request status to rejected with a reason."""
    async with await _get_db() as db:
        await db.execute(
            "UPDATE customer_kyc_requests SET status = 'rejected', reviewer = 'kyc_agent', "
            "rejection_reason = $1, reviewed_at = NOW() WHERE kyc_id = $2",
            reason, kyc_id,
        )
        await db.execute(
            """INSERT INTO audit_log (event_type, agent_name, action, details,
                                      actor_type, actor_username, actor_role)
               VALUES ('KYC_REJECTED','kyc_agent','reject_kyc',$1::jsonb,
                       'ai_agent','kyc_agent','ai')""",
            json.dumps({"kyc_id": kyc_id, "reason": reason}),
        )
    return {"rejected": True, "kyc_id": kyc_id}


@tool(name="escalate_to_hitl", description="Escalate a KYC case to a human compliance officer (pauses the run).")
async def escalate_to_hitl(
    kyc_id: Annotated[str, "KYC request ID"],
    reason: Annotated[str, "Why escalating"],
    suggested_action: Annotated[str, "approve | reject | request_documents"] = "",
) -> dict:
    """Log a HITL escalation keyed on the kyc_id."""
    return await log_hitl(
        agent_name=AGENT_NAME, event_type="KYC_HITL",
        entity_id=kyc_id, customer_id=None,
        reason=reason, suggested_action=suggested_action,
    )


KYC_TOOLS = [
    get_kyc_request,
    verify_gstin,
    check_sanctions,
    approve_kyc,
    reject_kyc,
    escalate_to_hitl,
]
