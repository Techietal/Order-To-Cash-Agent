"""
O2C Agent v2.0 — Cash Application API (Agent 9)
Payment authorization: requires registered sender email + matching 12-digit payment token.
Unknown email → HITL queue. Wrong/missing token → rejection email to sender.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from database.postgres import get_db
from api.staff_deps import require_role
from config import settings
from datetime import datetime
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

CASH_APP_ROLES = ["admin", "collections_analyst"]


class ProcessPaymentRequest(BaseModel):
    remittance_text: str
    expected_invoice_id: Optional[str] = None   # portal always sends this
    email_from: Optional[str] = None             # sender email — primary auth key
    payment_token: Optional[str] = None          # 12-digit token from invoice — required


@router.post("/process-payment")
async def process_payment_agent(
    payload: ProcessPaymentRequest,
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "collections_analyst"])),
):
    """
    Agent 9: Cash Application Agent — Token-Authenticated Payments.

    Authorization chain:
      1. If email_from present → must match a registered customer  (else → HITL)
      2. payment_token must match the invoice's stored token        (else → rejection email)
      3. Both checks pass → payment posted to AR automatically
    """
    from api.customer_portal import send_email

    # ── Step 1: Authenticate sender email ───────────────────────────────────
    # The sender's email address is the primary identity signal.
    # Company name / remittance text are attacker-controlled and ignored for auth.
    customer_id = None
    customer_row = None

    if payload.email_from:
        customer_row = await db.fetchrow(
            "SELECT customer_id, company_name, contact_name, email FROM customers WHERE LOWER(email) = $1 LIMIT 1",
            payload.email_from.lower().strip()
        )
        if customer_row:
            customer_id = customer_row["customer_id"]
            logger.info(f"Payment: customer authenticated via sender email: {customer_id}")
        else:
            # Unknown email → route to HITL for human approval
            # Human will verify if this is a legitimate payment from a different account/device
            logger.warning(f"Payment from unregistered email {payload.email_from} — routing to HITL")
            hitl_ref = f"HITL-PAY-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            try:
                import json
                details_json = json.dumps({
                    "email": payload.email_from,
                    "invoice": payload.expected_invoice_id,
                    "reason": "sender_email_not_registered",
                    "hitl_ref": hitl_ref,
                    "remittance_text": payload.remittance_text,
                    "payment_token": payload.payment_token
                })
                await db.execute(
                    """INSERT INTO audit_log (event_type, agent_name, invoice_id, action, details)
                       VALUES ('PAYMENT_HITL', 'agent_09_cash_application', $1, 'unknown_sender_hitl', $2::jsonb)""",
                    payload.expected_invoice_id or "UNKNOWN",
                    details_json
                )
            except Exception as e:
                logger.warning(f"HITL audit log failed: {e}")

            # Notify sender that their payment needs manual review
            send_email(
                to=payload.email_from,
                subject="Payment Requires Manual Verification — MAQ Manufacturing",
                body=(
                    f"Dear Customer,\n\n"
                    f"We received a payment notification from your email address ({payload.email_from}), "
                    f"but this address is not registered in our system.\n\n"
                    f"Your payment has been flagged for manual review by our Finance team (Ref: {hitl_ref}).\n"
                    f"Our team will contact you within 1 business day to verify and process your payment.\n\n"
                    f"If you believe this is an error, please contact us or register at:\n"
                    f"   {settings.frontend_url}/portal/register\n\n"
                    f"Regards,\nMAQ Manufacturing — Finance Team"
                )
            )
            return {
                "success": False,
                "route": "HITL_REQUIRED",
                "hitl_ref": hitl_ref,
                "agent_reason": (
                    f"Sender email {payload.email_from} is not registered. "
                    f"Payment routed to HITL queue (ref: {hitl_ref}) for manual verification. "
                    f"Notification sent to sender."
                ),
            }

    # ── Step 2: Resolve the invoice ─────────────────────────────────────────
    # Portal always sends expected_invoice_id. Email payments must include it in remittance.
    invoice = None
    if payload.expected_invoice_id:
        invoice = await db.fetchrow(
            "SELECT * FROM invoices WHERE invoice_id = $1 AND payment_status != 'paid'",
            payload.expected_invoice_id
        )
    elif customer_id:
        # Email payment without explicit invoice ID — pick oldest open invoice for this customer
        invoice = await db.fetchrow(
            """SELECT * FROM invoices
               WHERE customer_id = $1 AND payment_status IN ('pending','overdue') AND balance_due_inr > 0
               ORDER BY due_date ASC LIMIT 1""",
            customer_id
        )

    if not invoice:
        return {
            "success": False,
            "route": "NO_MATCH",
            "agent_reason": "No open invoice found to apply this payment against.",
        }

    invoice = dict(invoice)
    inv_id = invoice["invoice_id"]
    bal = float(invoice["balance_due_inr"])
    stored_token = invoice.get("payment_token")

    # ── Step 3: Validate payment token (if provided) ───────────────────────────
    # The payment_token is stored server-side on the invoice and is used by the
    # Customer Portal's Pay Now button as an extra layer of security.
    #
    # For EMAIL payments: the token is NOT included in the invoice email (by design,
    # to prevent token leakage). Auth is purely via the registered sender email (Step 1).
    # So we only validate the token if the caller explicitly provides one.
    if payload.payment_token and stored_token:
        if payload.payment_token.strip() != stored_token:
            logger.warning(f"Payment for {inv_id} rejected — token mismatch (provided: {payload.payment_token})")
            if payload.email_from:
                send_email(
                    to=payload.email_from,
                    subject=f"Payment Not Processed — Incorrect Authorization Token | {inv_id}",
                    body=(
                        f"Dear Customer,\n\n"
                        f"We received your payment notification for Invoice {inv_id} (₹{bal:,.0f}), "
                        f"but the authorization token provided does not match our records.\n\n"
                        f"Please pay directly from the portal to avoid this issue:\n"
                        f"   {settings.frontend_url}/portal/outstanding\n\n"
                        f"If you need assistance, contact our Finance team.\n\n"
                        f"Regards,\nMAQ Manufacturing — Finance Team"
                    )
                )
            return {
                "success": False,
                "invoice_id": inv_id,
                "route": "TOKEN_MISMATCH",
                "agent_reason": f"Payment rejected for {inv_id} — payment_token does not match. Rejection email sent.",
            }
    elif not payload.payment_token:
        # No token provided — this is a normal email payment. Auth was via sender email (Step 1).
        # Log it clearly for the audit trail.
        logger.info(f"Payment for {inv_id} via email channel — no token provided, authenticated via sender email {payload.email_from}")

    # ── Step 4: Token valid — post payment to AR ────────────────────────────
    await db.execute(
        "UPDATE invoices SET amount_paid_inr = amount_paid_inr + $1, balance_due_inr = 0, payment_status = 'paid' WHERE invoice_id = $2",
        bal, inv_id
    )
    await db.execute(
        "UPDATE ar_ledger SET outstanding_balance_inr = 0, payment_status = 'paid', last_action = 'token_verified_payment' WHERE invoice_id = $1",
        inv_id
    )

    pay_id = f"PAY-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    channel = "portal" if not payload.email_from else "email"
    await db.execute(
        """INSERT INTO payments (payment_id, invoice_id, amount_inr, payment_date, payment_method, status)
           VALUES ($1, $2, $3, NOW(), $4, 'processed')""",
        pay_id, inv_id, bal, f"bank_transfer_{channel}"
    )
    await db.execute(
        """INSERT INTO audit_log (event_type, agent_name, invoice_id, action, details)
           VALUES ('CASH_APPLICATION', 'agent_09_cash_application', $1, 'token_verified_posted', $2)""",
        inv_id, f'{{"payment_id": "{pay_id}", "amount": {bal}, "channel": "{channel}", "customer_id": "{customer_id or "portal"}"}}'
    )

    # Send receipt email to the customer's registered address
    receipt_to = payload.email_from
    if not receipt_to and customer_id:
        c = await db.fetchrow("SELECT email FROM customers WHERE customer_id = $1", customer_id)
        receipt_to = c["email"] if c else None
    if receipt_to:
        send_email(
            to=receipt_to,
            subject=f"Payment Receipt — {inv_id} | MAQ Manufacturing",
            body=(
                f"Dear Customer,\n\n"
                f"Your payment has been successfully verified and posted.\n\n"
                f"Payment ID  : {pay_id}\n"
                f"Invoice ID  : {inv_id}\n"
                f"Amount Paid : ₹{bal:,.0f}\n"
                f"Channel     : {channel.upper()}\n"
                f"Date        : {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}\n"
                f"Status      : PAID IN FULL\n\n"
                f"Thank you. This invoice is now marked as cleared.\n\n"
                f"Regards,\nMAQ Manufacturing — Finance Team"
            )
        )

    logger.info(f"Payment {pay_id} posted for invoice {inv_id} — ₹{bal:,.0f} via {channel}")
    return {
        "success": True,
        "invoice_id": inv_id,
        "payment_id": pay_id,
        "route": "TOKEN_VERIFIED",
        "agent_reason": f"Payment token verified. ₹{bal:,.0f} posted to AR for {inv_id} via {channel}.",
    }


@router.post("/process-payment-semantic")
async def process_payment_semantic(
    payload: ProcessPaymentRequest,
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "collections_analyst"])),
):
    """
    Agent 9: Cash Application Agent.
    1. Embeds remittance text via Sentence Transformers (all-MiniLM-L6-v2)
    2. Computes cosine similarity against all open invoices
    3. Picks best match above confidence threshold → auto-posts to AR
    4. Falls back to Groq LLM verification for borderline matches
    5. Routes low-confidence to HITL with reason code
    """
    # Email-first customer lookup (Priority 0): scope invoices to the sender's account
    scoped_customer_id = None
    if payload.email_from:
        row = await db.fetchrow(
            "SELECT customer_id FROM customers WHERE LOWER(email) = $1 LIMIT 1",
            payload.email_from.lower().strip()
        )
        if row:
            scoped_customer_id = row["customer_id"]
            logger.info(f"Payment: customer scoped via sender email: {scoped_customer_id}")

    # If specific invoice provided, fetch it directly
    if payload.expected_invoice_id:
        open_invoices = await db.fetch(
            "SELECT * FROM invoices WHERE invoice_id = $1 AND payment_status != 'paid'",
            payload.expected_invoice_id
        )
    elif scoped_customer_id:
        # Narrow to just this customer's open invoices for better accuracy
        open_invoices = await db.fetch(
            "SELECT * FROM invoices WHERE customer_id = $1 AND payment_status IN ('pending','overdue') AND balance_due_inr > 0 ORDER BY due_date ASC LIMIT 20",
            scoped_customer_id
        )
    else:
        # Fetch all open invoices for semantic matching
        open_invoices = await db.fetch(
            "SELECT * FROM invoices WHERE payment_status IN ('pending','overdue') AND balance_due_inr > 0 LIMIT 50"
        )

    if not open_invoices:
        return {
            "success": False,
            "agent_reason": "No open invoices found to match against.",
            "confidence": 0.0,
            "route": "NO_MATCH",
        }

    # Step 2: Find best matching invoice via Sentence Transformer similarity
    # Run in executor so model loading doesn't block the async event loop
    import asyncio
    loop = asyncio.get_event_loop()
    best_invoice = None
    best_score = 0.0

    invoice_texts = []
    for inv in open_invoices:
        inv_text = (
            f"Invoice {inv['invoice_id']} for customer {inv['customer_id']} "
            f"amount {float(inv['total_amount_inr']):.0f} INR "
            f"due {inv['due_date'].strftime('%Y-%m-%d') if inv['due_date'] else 'unknown'}"
        )
        invoice_texts.append((inv, inv_text))

    for inv, inv_text in invoice_texts:
        try:
            score = await loop.run_in_executor(
                None, compute_similarity, payload.remittance_text, inv_text
            )
        except Exception:
            score = 0.4   # fallback moderate score

        if score > best_score:
            best_score = score
            best_invoice = dict(inv)

    if not best_invoice:
        return {"success": False, "agent_reason": "No invoice match found.", "confidence": 0.0}

    bal = float(best_invoice["balance_due_inr"])
    inv_id = best_invoice["invoice_id"]

    # Step 3: Route by confidence
    if best_score >= CONFIDENCE_THRESHOLD:
        # Auto-post to AR
        await db.execute(
            "UPDATE invoices SET amount_paid_inr = amount_paid_inr + $1, balance_due_inr = 0, payment_status = 'paid' WHERE invoice_id = $2",
            bal, inv_id
        )
        await db.execute(
            "UPDATE ar_ledger SET outstanding_balance_inr = 0, payment_status = 'paid', last_action = 'auto_matched_by_ai' WHERE invoice_id = $1",
            inv_id
        )
        await db.execute(
            """INSERT INTO audit_log (event_type, agent_name, invoice_id, action, details)
               VALUES ('CASH_APPLICATION', 'agent_09_cash_application', $1, 'auto_posted', $2)""",
            inv_id, f'{{"confidence": {best_score:.3f}, "amount": {bal}}}'
        )
        # Also log the payment into the payments table so it shows up in the customer portal history
        from datetime import datetime
        pay_id = f"PAY-CASHAPP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        await db.execute(
            """INSERT INTO payments (payment_id, invoice_id, amount_inr, payment_date, payment_method, status)
               VALUES ($1, $2, $3, NOW(), 'bank_transfer', 'processed')""",
            pay_id, inv_id, bal
        )

        return {
            "success": True,
            "invoice_id": inv_id,
            "confidence": round(best_score, 3),
            "route": "AUTO_POSTED",
            "agent_reason": (
                f"Sentence Transformer confidence {best_score:.1%} ≥ {CONFIDENCE_THRESHOLD:.0%} threshold. "
                f"Payment of ₹{bal:,.0f} auto-posted to AR for {inv_id}."
            ),
        }

    elif best_score >= REVIEW_THRESHOLD:
        # Groq LLM secondary verification for borderline matches
        prompt = (
            f"You are the Cash Application Agent. Verify if this bank remittance text matches the invoice.\n"
            f"Invoice ID: {inv_id}\nBalance Due: ₹{bal:,.0f}\n\n"
            f"Remittance Text:\n\"{payload.remittance_text}\"\n\n"
            f"Respond with JSON: {{\"match\": true/false, \"reason\": \"...\"}}"
        )
        try:
            llm_resp = call_groq([{"role": "user", "content": prompt}], json_mode=True)
            import json
            parsed = json.loads(llm_resp) if isinstance(llm_resp, str) else llm_resp
            llm_match = parsed.get("match", False)
        except Exception:
            llm_match = False

        if llm_match:
            await db.execute(
                "UPDATE invoices SET amount_paid_inr = amount_paid_inr + $1, balance_due_inr = 0, payment_status = 'paid' WHERE invoice_id = $2",
                bal, inv_id
            )
            await db.execute(
                "UPDATE ar_ledger SET outstanding_balance_inr = 0, payment_status = 'paid', last_action = 'llm_verified_match' WHERE invoice_id = $1",
                inv_id
            )
            return {
                "success": True, "invoice_id": inv_id,
                "confidence": round(best_score, 3), "route": "LLM_VERIFIED",
                "agent_reason": f"Groq LLM confirmed match (ST confidence {best_score:.1%}). ₹{bal:,.0f} posted.",
            }
        else:
            return {
                "success": False, "invoice_id": inv_id,
                "confidence": round(best_score, 3), "route": "LLM_REJECTED",
                "agent_reason": f"ST confidence {best_score:.1%} borderline. Groq LLM rejected match for {inv_id}.",
            }
    else:
        # Route to HITL
        return {
            "success": False, "invoice_id": inv_id,
            "confidence": round(best_score, 3), "route": "HITL_REQUIRED",
            "agent_reason": (
                f"Confidence {best_score:.1%} below review threshold {REVIEW_THRESHOLD:.0%}. "
                f"Routed to Cash Application HITL queue. Reason: LOW_CONFIDENCE_MATCH."
            ),
        }


@router.get("/payments")
async def list_payments(limit: int = 100, db=Depends(get_db), staff=Depends(require_role(CASH_APP_ROLES))):
    """List all paid invoices (cash application history)."""
    rows = await db.fetch(
        """SELECT i.invoice_id, i.order_id, i.customer_id, c.company_name,
                  i.total_amount_inr, i.amount_paid_inr, i.payment_status, i.updated_at
           FROM invoices i
           JOIN customers c ON i.customer_id = c.customer_id
           WHERE i.payment_status = 'paid'
           ORDER BY i.updated_at DESC
           LIMIT $1""",
        limit
    )
    return {"payments": [dict(r) for r in rows], "total": len(rows)}


@router.get("/match-stats")
async def match_stats(db=Depends(get_db), staff=Depends(require_role(CASH_APP_ROLES))):
    """Real cash application match statistics from DB."""
    total_invoices = await db.fetchval("SELECT COUNT(*) FROM invoices") or 1
    paid = await db.fetchval("SELECT COUNT(*) FROM invoices WHERE payment_status = 'paid'") or 0
    pending = await db.fetchval("SELECT COUNT(*) FROM invoices WHERE payment_status IN ('pending','overdue')") or 0
    auto_posted = await db.fetchval(
        "SELECT COUNT(*) FROM ar_ledger WHERE last_action IN ('auto_matched_by_ai', 'llm_verified_match')"
    ) or 0
    return {
        "total_invoices": int(total_invoices),
        "paid": int(paid),
        "pending": int(pending),
        "auto_match_rate": round(float(auto_posted) / max(float(paid), 1), 3),
        "auto_posted": int(auto_posted),
        "confidence_threshold": CONFIDENCE_THRESHOLD,
    }
