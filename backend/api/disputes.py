from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from database.postgres import get_db
from api.staff_deps import require_role
from ml.groq_client import _call_groq
from config import settings
import logging, json, smtplib
from email.mime.text import MIMEText
from datetime import datetime
import re

router = APIRouter()
logger = logging.getLogger(__name__)

DISPUTE_ROLES = ["admin", "dispute_manager"]


class DisputeCreate(BaseModel):
    invoice_id: str
    dispute_type: str
    claim_amount_inr: float
    description: str


class DisputeEmailIngest(BaseModel):
    email_text: str
    email_from: Optional[str] = None
    subject: Optional[str] = None


def extract_order_id_from_text(text: str) -> Optional[str]:
    match = re.search(r"\bORD-[A-Za-z0-9-]+\b", text or "", re.IGNORECASE)
    return match.group(0).upper() if match else None


@router.get("")
async def list_disputes(status: str = None, limit: int = 50, db=Depends(get_db), staff=Depends(require_role(DISPUTE_ROLES))):
    rows = await db.fetch("SELECT * FROM anomaly_alerts ORDER BY detected_at DESC LIMIT $1", limit)
    return {"disputes": [dict(r) for r in rows]}


@router.get("/stats")
async def dispute_stats(db=Depends(get_db), staff=Depends(require_role(DISPUTE_ROLES))):
    total   = await db.fetchval("SELECT COUNT(*) FROM anomaly_alerts") or 0
    pending = await db.fetchval("SELECT COUNT(*) FROM anomaly_alerts WHERE reviewed = FALSE") or 0
    return {"total": int(total), "pending": int(pending), "resolved": int(total - pending)}


@router.post("/submit-email")
async def submit_dispute_email(payload: DisputeEmailIngest, db=Depends(get_db)):
    """
    Agent 4 — Dispute Ingestion from Email.
    1. GLiNER extracts invoice reference, claim amount, dispute reason
    2. Classifies dispute type (damaged_goods / pricing_error / short_ship / pod_dispute / deduction_claim)
    3. Persists to anomaly_alerts for the Disputes queue
    """
    from ml.gliner_ner import extract_dispute_entities

    # Step 1: GLiNER NER extraction on the dispute email
    entities = extract_dispute_entities(payload.email_text)
    logger.info(f"Agent 4 Dispute NER result: {entities}")

    def get_val(key, default):
        val = entities.get(key)
        if isinstance(val, dict):
            return val.get("value", default)
        return val if val is not None else default

    invoice_ref   = get_val("invoice_reference", "UNKNOWN")
    claim_amount  = get_val("claim_amount", "0")
    dispute_reason = get_val("dispute_reason", payload.email_text[:100])
    contact       = get_val("contact_name", payload.email_from or "Unknown")

    # Parse claim amount — strip currency symbols, commas
    try:
        clean = ''.join(c for c in str(claim_amount) if c.isdigit() or c == '.')
        claim_inr = float(clean) if clean else 0.0
    except Exception:
        claim_inr = 0.0

    # Step 2: Classify dispute type from the reason text
    reason_lower = (dispute_reason + " " + payload.email_text).lower()
    if any(w in reason_lower for w in ["damag", "broken", "defect", "quality"]):
        dispute_type = "damaged_goods"
        severity = "HIGH"
    elif any(w in reason_lower for w in ["price", "pricing", "overcharg", "rate"]):
        dispute_type = "pricing_error"
        severity = "MEDIUM"
    elif any(w in reason_lower for w in ["short", "missing", "not received", "partial"]):
        dispute_type = "short_ship"
        severity = "HIGH"
    elif any(w in reason_lower for w in ["proof", "delivery", "pod", "not deliver"]):
        dispute_type = "pod_dispute"
        severity = "MEDIUM"
    elif any(w in reason_lower for w in ["deduction", "offset", "credit note", "discount"]):
        dispute_type = "deduction_claim"
        severity = "LOW"
    else:
        dispute_type = "general_dispute"
        severity = "MEDIUM"

    # Step 3: Build AI summary
    groq_summary = (
        f"{dispute_type.replace('_', ' ').title()} from {contact}: "
        f"Invoice {invoice_ref} — ₹{claim_inr:,.0f} disputed. "
        f"Reason: {dispute_reason[:120]}"
    )

    # Step 3b: Strict email-only customer authentication.
    #
    # SECURITY: Disputes are only accepted from registered email addresses.
    # We do NOT fall back to any name-based matching — the contact name and company
    # name are extracted from the email body, which is entirely attacker-controlled.
    #
    # If the sender is not registered → send a clear rejection email and stop.
    # The dispute is NOT persisted — there is no customer to link it to.
    customer_id = None
    if payload.email_from:
        row = await db.fetchrow(
            "SELECT customer_id, company_name, contact_name FROM customers WHERE LOWER(email) = $1 LIMIT 1",
            payload.email_from.lower().strip()
        )
        if row:
            customer_id = row["customer_id"]
            logger.info(f"Dispute customer authenticated via sender email: {customer_id}")
        else:
            # Unknown sender — reject and notify them
            logger.warning(f"Dispute from unregistered email {payload.email_from} — rejecting and notifying sender")
            from api.customer_portal import send_email
            send_email(
                to=payload.email_from,
                subject="Dispute Not Processed — Email Not Registered | MAQ Manufacturing",
                body=(
                    f"Dear Customer,\n\n"
                    f"We received your dispute email, but your email address ({payload.email_from}) "
                    f"is not registered in our system.\n\n"
                    f"We are unable to process dispute submissions from unregistered addresses as we "
                    f"cannot verify your identity or link your claim to an account.\n\n"
                    f"If you are a registered customer, please ensure you are writing from your "
                    f"registered email address.\n\n"
                    f"If you are new, please register at our portal first:\n"
                    f"   {settings.frontend_url}/portal/register\n\n"
                    f"We apologize for any inconvenience.\n\n"
                    f"Regards,\nMAQ Manufacturing — Disputes Team"
                )
            )
            return {
                "alert_id": None,
                "dispute_type": "rejected",
                "severity": "N/A",
                "invoice_reference": invoice_ref,
                "claim_amount_inr": 0.0,
                "contact": payload.email_from,
                "ner_entities": {},
                "summary": "Dispute rejected — sender email not registered.",
                "message": f"Dispute NOT processed. Sender {payload.email_from} is not a registered customer. Rejection email sent.",
            }
    else:
        # No email_from at all — cannot authenticate
        logger.warning("Dispute received with no email_from — rejecting")
        return {
            "alert_id": None,
            "dispute_type": "rejected",
            "severity": "N/A",
            "invoice_reference": invoice_ref,
            "claim_amount_inr": 0.0,
            "contact": "unknown",
            "ner_entities": {},
            "summary": "Dispute rejected — no sender email present.",
            "message": "Dispute NOT processed. No sender email address was present in the request.",
        }

    # Step 4: Persist to portal_disputes
    dispute_id = f"DISP-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    subject = payload.subject or f"Dispute regarding {invoice_ref}"
    
    try:
        async with db.transaction():
            order_ref = extract_order_id_from_text(f"{payload.subject or ''}\n{payload.email_text}")
            resolved_order_id = None
            if order_ref:
                order_row = await db.fetchrow(
                    "SELECT order_id FROM orders WHERE order_id=$1 AND customer_id=$2",
                    order_ref,
                    customer_id,
                )
                if order_row:
                    resolved_order_id = order_row["order_id"]
            if not resolved_order_id and invoice_ref != "UNKNOWN":
                invoice_row = await db.fetchrow(
                    "SELECT order_id FROM invoices WHERE invoice_id=$1 AND customer_id=$2",
                    invoice_ref,
                    customer_id,
                )
                if invoice_row:
                    resolved_order_id = invoice_row["order_id"]

            await db.execute(
                """INSERT INTO portal_disputes
                   (dispute_id, customer_id, invoice_id, order_id, dispute_type, subject,
                    ai_summary, ai_summary_status, status, next_actor, proof_count, source)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                dispute_id, customer_id, invoice_ref if invoice_ref != "UNKNOWN" else None,
                resolved_order_id, dispute_type, subject,
                groq_summary, "completed", "pending_admin", "admin", 0, "email"
            )
            
            # Insert the email body as the first customer message
            msg_id = f"DMSG-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            await db.execute(
                """INSERT INTO portal_dispute_messages
                   (message_id, dispute_id, sender_type, sender_id, body)
                   VALUES ($1,$2,$3,$4,$5)""",
                msg_id, dispute_id, "customer", customer_id or "email", payload.email_text
            )
            
            # Audit log
            await db.execute(
                """INSERT INTO audit_log (event_type, agent_name, customer_id, invoice_id, action, details)
                   VALUES ('DISPUTE_EMAIL_INGESTED', 'agent_4', $1, $2, 'email_ingested', $3)""",
                customer_id, invoice_ref if invoice_ref != "UNKNOWN" else None,
                json.dumps({"dispute_id": dispute_id, "dispute_type": dispute_type, "severity": severity, "order_id": resolved_order_id})
            )
            
        logger.info(f"Email Dispute {dispute_id} persisted as portal dispute: {dispute_type} customer={customer_id}")
    except Exception as e:
        logger.error(f"Email Dispute persist failed: {e}")
        raise HTTPException(500, f"Failed to save email dispute: {e}")

    return {
        "alert_id": dispute_id,
        "dispute_type": dispute_type,
        "severity": severity,
        "invoice_reference": invoice_ref,
        "claim_amount_inr": claim_inr,
        "contact": contact,
        "ner_entities": entities,
        "summary": groq_summary,
        "message": f"Dispute {dispute_id} logged successfully — AI classified as '{dispute_type}' (severity: {severity})",
    }


# ── AI Suggestion Endpoint ──────────────────────────────────────────────────
@router.get("/{alert_id}/ai-suggest")
async def ai_suggest_resolution(alert_id: str, db=Depends(get_db), staff=Depends(require_role(DISPUTE_ROLES))):
    """
    Groq analyzes the dispute and pre-fills all resolution fields:
    - Invoice ID (regex from summary + DB cross-check)
    - Customer name & email (from invoices + customers tables)
    - Suggested credit amount (LLM reasons from actual dispute text)
    - Resolution note for SOX audit trail
    - Full apology email draft
    """
    dispute = await db.fetchrow(
        "SELECT * FROM anomaly_alerts WHERE alert_id=$1", alert_id
    )
    if not dispute:
        raise HTTPException(404, "Dispute not found")

    d = dict(dispute)
    summary  = d.get("groq_alert_summary", "")
    action   = d.get("recommended_action", "")
    d_type   = d.get("alert_type", "general_dispute")
    severity = d.get("severity", "MEDIUM")

    # Step 1: Extract invoice ID — from DB first, then regex on text
    import re
    invoice = d.get("order_id") or ""
    if not invoice:
        m = re.search(r"(INV-[\w\-]+)", summary + " " + action, re.IGNORECASE)
        invoice = m.group(1).rstrip(".,;") if m else ""

    # Step 2: Look up invoice + customer from DB for real name & email
    customer_name  = ""
    customer_email = ""
    invoice_total  = 0.0
    if invoice:
        inv_row = await db.fetchrow(
            "SELECT * FROM invoices WHERE invoice_id=$1", invoice
        )
        if inv_row:
            invoice_total = float(inv_row.get("total_amount_inr") or inv_row.get("balance_due_inr") or 0)
            cust_id = inv_row.get("customer_id", "")
            if cust_id:
                cust_row = await db.fetchrow(
                    "SELECT * FROM customers WHERE customer_id=$1", cust_id
                )
                if cust_row:
                    customer_name  = cust_row.get("company_name") or cust_row.get("customer_name") or ""
                    customer_email = cust_row.get("email") or cust_row.get("contact_email") or ""

    # Step 3: Parse claim amount
    m_amt = re.search(r"₹([\d,]+)", action)
    claim_str = m_amt.group(1).replace(",", "") if m_amt else "0"
    claim_amt = float(claim_str) if claim_str else 0.0

    # Step 4: Let Groq reason from actual dispute text — no hardcoded rules
    prompt = f"""You are an experienced Accounts Receivable Controller at MAQ Manufacturing (India).

A customer has raised a dispute. Read the full context carefully and make a fair, well-reasoned decision.

=== DISPUTE CONTEXT ===
Alert ID: {alert_id}
Dispute Type: {d_type.replace('_', ' ')}
Severity: {severity}
Invoice: {invoice or 'Unknown'}
Invoice Total: ₹{invoice_total:,.0f}
Customer: {customer_name or 'Unknown'}
Full Dispute Summary: {summary}
Recommended Action (from initial AI triage): {action}
Customer's Claimed Amount: ₹{claim_amt:,.0f}

=== YOUR TASK ===
Read the dispute summary above carefully. Based on WHAT the customer actually says happened:
- If it is a clear billing error (wrong price, wrong quantity billed), the full claimed amount should be credited
- If goods were partially damaged, credit only the damaged portion — but base this on what is mentioned in the summary (not a default 50%)
- If it is unproven (no details given), you may suggest a conservative partial amount and ask for more documentation
- Never default to 50% without a real reason from the text

Think step by step:
1. What exactly happened according to the dispute summary?
2. Is this MAQ's fault or the customer's?
3. What is the right credit amount and why?
4. Write an internal audit note and a professional email to the customer

Return JSON only:
{{
  "invoice_id": "{invoice or '<extract from summary>'}",
  "suggested_amount": <number — must be justified by the dispute text, not a default percentage>,
  "rationale": "<2-3 sentences: what happened, why this credit amount is fair>",
  "resolution_note": "<1 sentence internal SOX audit note, e.g.: Full credit approved as pricing error confirmed — customer was billed ₹15,000/unit vs agreed ₹12,000/unit per PO-2024-089>",
  "email_subject": "<professional subject line mentioning invoice {invoice}>",
  "email_body": "<professional 3-4 paragraph email: address {customer_name or 'Customer'} by name, apologise specifically for what went wrong, state the credit amount and how/when it will be applied, close with Regards, MAQ Finance Disputes Team>"
}}"""

    try:
        raw = _call_groq([{"role": "user", "content": prompt}], json_mode=True)
        result = json.loads(raw)
        ai_invoice = result.get("invoice_id", "") or invoice
        logger.info(f"AI suggest for {alert_id}: amount={result.get('suggested_amount')}, invoice={ai_invoice}, customer_email={customer_email}")
        return {
            "alert_id":       alert_id,
            "invoice_id":     ai_invoice,
            "customer_email": customer_email,
            "customer_name":  customer_name,
            "suggested_amount": result.get("suggested_amount", claim_amt),
            "claim_amount":   claim_amt,
            "rationale":      result.get("rationale", ""),
            "resolution_note":result.get("resolution_note", ""),
            "email_subject":  result.get("email_subject", f"Dispute Resolution — {ai_invoice}"),
            "email_body":     result.get("email_body", ""),
        }

    except Exception as e:
        logger.error(f"AI suggest failed: {e}")
        return {
            "alert_id":       alert_id,
            "invoice_id":     invoice,
            "customer_email": customer_email,
            "customer_name":  customer_name,
            "suggested_amount": claim_amt,
            "claim_amount":   claim_amt,
            "rationale":      "Unable to auto-suggest — please review manually.",
            "resolution_note": f"Dispute {alert_id} reviewed manually — credit pending controller approval.",
            "email_subject":  f"Regarding Your Dispute {alert_id} — Invoice {invoice}",
            "email_body": (
                f"Dear {customer_name or 'Customer'},\n\n"
                f"Thank you for raising dispute {alert_id} regarding Invoice {invoice}.\n\n"
                f"We have reviewed your claim. A credit of ₹{claim_amt:,.0f} has been approved "
                f"and will be applied to your account within 5-7 business days.\n\n"
                f"We sincerely apologize for the inconvenience caused.\n\n"
                f"Regards,\nMAQ Finance Disputes Team"
            ),
        }



class ResolveDisputePayload(BaseModel):
    approved_amount: float
    resolution_note: Optional[str] = ""
    invoice_id: Optional[str] = None
    contact_email: Optional[str] = None        # customer email to notify
    email_subject: Optional[str] = None        # editable email subject
    email_body: Optional[str] = None           # editable email body to send

@router.post("/{alert_id}/resolve")
async def resolve_dispute(
    alert_id: str,
    payload: ResolveDisputePayload,
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "dispute_manager"])),
):
    """
    HITL Gate 6 — Resolve a dispute with a credit memo.
    Supports full OR partial credit:
      - Full credit:    approved_amount = full claim amount  → invoice fully cleared
      - Partial credit: approved_amount < claim amount       → invoice partially reduced
    """
    # 1. Fetch the dispute record
    dispute = await db.fetchrow(
        "SELECT * FROM anomaly_alerts WHERE alert_id=$1", alert_id
    )
    if not dispute:
        raise HTTPException(404, "Dispute not found")

    # 2. Resolve the dispute flag
    resolution_text = (
        f"Approved credit: ₹{payload.approved_amount:,.0f}. "
        f"{payload.resolution_note or 'Full resolution.'}"
    )
    await db.execute(
        "UPDATE anomaly_alerts SET reviewed=TRUE, resolution=$1 WHERE alert_id=$2",
        resolution_text, alert_id
    )

    # 3. Apply credit to the invoice if invoice_id is provided
    credit_applied = False
    if payload.invoice_id and payload.approved_amount > 0:
        inv = await db.fetchrow(
            "SELECT * FROM invoices WHERE invoice_id=$1", payload.invoice_id
        )
        if inv:
            current_balance = float(inv["balance_due_inr"] or 0)
            new_balance = max(0.0, current_balance - payload.approved_amount)
            new_status  = "paid" if new_balance == 0 else "partial"

            await db.execute(
                """UPDATE invoices
                   SET balance_due_inr = $1,
                       payment_status  = $2,
                       amount_paid_inr = amount_paid_inr + $3
                   WHERE invoice_id = $4""",
                new_balance, new_status, payload.approved_amount, payload.invoice_id
            )
            await db.execute(
                """UPDATE ar_ledger
                   SET outstanding_balance_inr = $1,
                       payment_status          = $2,
                       last_action             = 'credit_memo_applied'
                   WHERE invoice_id = $3""",
                new_balance, new_status, payload.invoice_id
            )
            credit_applied = True
            # Insert credit memo — permanent record of this human-approved credit
            memo_id = f"MEMO-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:22]}"
            try:
                await db.execute(
                    """INSERT INTO credit_memos
                       (memo_id, order_id, invoice_id, customer_id, dispute_id,
                        amount_inr, reason, approved_by, approved_by_role,
                        balance_before_inr, balance_after_inr, source)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                    memo_id,
                    inv.get("order_id"),
                    payload.invoice_id,
                    inv.get("customer_id"),
                    alert_id,
                    payload.approved_amount,
                    payload.resolution_note or "Credit memo via dispute resolution",
                    staff["username"],
                    staff["role"],
                    current_balance,
                    new_balance,
                    "dispute_resolution",
                )
                logger.info(f"Credit memo {memo_id} created: ₹{payload.approved_amount:,.0f} by {staff['username']}")
            except Exception as e:
                logger.error(f"Credit memo insert failed: {e}")

            logger.info(
                f"Credit memo ₹{payload.approved_amount:,.0f} applied to {payload.invoice_id}. "
                f"New balance: ₹{new_balance:,.0f} ({new_status})"
            )

    # 4. Audit trail with real human actor identity
    import json as _json
    try:
        await db.execute(
            """INSERT INTO audit_log
               (event_type, agent_name, order_id, invoice_id, action, details,
                actor_type, actor_username, actor_role,
                previous_value, new_value)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb,
                       'human',$7,$8,
                       $9::jsonb,$10::jsonb)""",
            "DISPUTE_RESOLVED",
            staff["username"],
            alert_id,
            payload.invoice_id or "",
            "credit_memo_applied" if credit_applied else "resolved_no_credit",
            _json.dumps({"approved_amount": payload.approved_amount, "note": payload.resolution_note}),
            staff["username"], staff["role"],
            _json.dumps({"reviewed": False, "balance_due_inr": current_balance if credit_applied else None}),
            _json.dumps({"reviewed": True, "balance_due_inr": (current_balance - payload.approved_amount) if credit_applied else None,
                         "approved_amount": payload.approved_amount}),
        )
    except Exception:
        pass

    # 5. Send resolution email to customer (graceful — logs to audit if SMTP not configured)
    email_sent = False
    email_logged = False
    if payload.contact_email and payload.email_body:
        from config import settings
        smtp_configured = bool(settings.smtp_user and settings.smtp_password)
        if smtp_configured:
            try:
                msg = MIMEText(payload.email_body)
                msg["Subject"] = payload.email_subject or f"Dispute {alert_id} — Resolution"
                msg["From"]    = settings.email_from
                msg["To"]      = payload.contact_email
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
                    if settings.smtp_tls:
                        s.starttls()
                    s.login(settings.smtp_user, settings.smtp_password)
                    s.sendmail(settings.email_from, [payload.contact_email], msg.as_string())
                email_sent = True
                logger.info(f"✅ Resolution email sent to {payload.contact_email} for {alert_id}")
            except Exception as e:
                logger.warning(f"Resolution email failed: {e}")
        else:
            # SMTP not configured — log the email to audit trail so it can be sent manually
            logger.info(f"SMTP not configured — resolution email for {alert_id} logged to audit trail")
        # Always log the email body to audit trail
        try:
            await db.execute(
                """INSERT INTO audit_log (event_type, agent_name, order_id, invoice_id, action, details)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                "RESOLUTION_EMAIL", "hitl_controller", alert_id,
                payload.invoice_id or "",
                "email_sent" if email_sent else "email_logged_smtp_not_configured",
                f'{{"to": "{payload.contact_email}", "subject": "{(payload.email_subject or "").replace(chr(34), "")}", "smtp_sent": {str(email_sent).lower()}}}'
            )
            email_logged = True
        except Exception:
            pass

    return {
        "alert_id": alert_id,
        "status": "resolved",
        "credit_applied": credit_applied,
        "approved_amount": payload.approved_amount,
        "invoice_id": payload.invoice_id,
        "resolution": resolution_text,
        "email_sent": email_sent,
        "email_logged": email_logged,
    }


class RequestInfoPayload(BaseModel):
    message: str        # HITL's custom message to customer
    contact_email: str = None  # optional override

@router.post("/{alert_id}/request-info")
async def request_more_info(alert_id: str, payload: RequestInfoPayload, db=Depends(get_db), staff=Depends(require_role(DISPUTE_ROLES))):
    """HITL Gate — Human controller asks customer for more evidence / proof."""
    import smtplib, os
    from email.mime.text import MIMEText
    from config import settings

    # Fetch dispute
    row = await db.fetchrow(
        "SELECT * FROM anomaly_alerts WHERE alert_id=$1", alert_id
    )
    if not row:
        raise HTTPException(404, "Dispute not found")

    to_email = payload.contact_email or "customer@example.com"
    subject  = f"[MAQ Finance] Additional Information Required — Dispute {alert_id}"
    body     = (
        f"Dear Customer,\n\n"
        f"Thank you for raising your dispute (Reference: {alert_id}).\n\n"
        f"Our Finance Controller has reviewed your case and requires the following additional information before we can proceed:\n\n"
        f"---\n{payload.message}\n---\n\n"
        f"Please reply to this email with the requested information as soon as possible so we can resolve your dispute promptly.\n\n"
        f"Regards,\nMAQ Finance Disputes Team"
    )

    sent = False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"]    = settings.email_from
        msg["To"]      = to_email
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
            if settings.smtp_tls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.sendmail(settings.email_from, [to_email], msg.as_string())
        sent = True
        logger.info(f"HITL request-info email sent for {alert_id} to {to_email}")
    except Exception as e:
        logger.warning(f"Email send failed: {e} — logging audit only")

    # Always log to audit trail
    try:
        await db.execute(
            """INSERT INTO audit_log (event_type, agent_name, order_id, action, details)
               VALUES ($1,$2,$3,$4,$5)""",
            "HITL_REQUEST_INFO", "human_controller", alert_id, "info_requested", payload.message[:200]
        )
    except Exception:
        pass

    return {
        "alert_id": alert_id,
        "status": "info_requested",
        "email_sent": sent,
        "to": to_email,
        "message": payload.message,
    }
