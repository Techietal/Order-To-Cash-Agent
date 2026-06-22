"""
O2C Agent v2.0 — HITL (Human-in-the-Loop) API
Handles two queues:
  1. order_hold — Orders flagged for manual review (fraud, credit, policy)
  2. customer_kyc — New customer background-check approvals
"""
import random
import string
import logging
import smtplib
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database.postgres import get_db
from api.staff_deps import require_role, create_service_token
from config import settings
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from passwords import hash_password

router = APIRouter()
logger = logging.getLogger(__name__)

HELPDESK_EMAIL = "helpdesk@maqsoftware.com"
HITL_ROLES = ["admin", "controller"]


def _send_email(to: str, subject: str, body: str):
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP not configured — email not sent")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = settings.smtp_user
        msg["To"]      = to
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, to, msg.as_string())
        logger.info(f"HITL email sent → {to}")
    except Exception as e:
        logger.error(f"HITL email failed: {e}")


class HITLDecision(BaseModel):
    decision: str   # "approved" | "rejected" | "fulfilled" etc.
    reviewer: str
    notes: str = ""


class KYCDecision(BaseModel):
    decision: str      # "approved" | "rejected"
    reviewer: str
    notes: str = ""
    rejection_reason: str = ""


class PaymentHoldDecision(BaseModel):
    decision: str
    reviewer: str
    customer_id: str = ""
    invoice_id: str = ""
    notes: str = ""

@router.get("/payment-queue")
async def payment_queue(db=Depends(get_db), staff=Depends(require_role(HITL_ROLES))):
    rows = await db.fetch("""
        SELECT log_id, created_at, details
        FROM audit_log
        WHERE event_type = 'PAYMENT_HITL' AND action = 'unknown_sender_hitl'
          AND details->>'hitl_ref' NOT IN (
              SELECT details->>'hitl_ref' FROM audit_log
              WHERE event_type = 'PAYMENT_HITL' AND action IN ('approved', 'rejected')
          )
        ORDER BY created_at DESC
    """)
    queue = []
    for r in rows:
        import json
        details = r['details']
        if isinstance(details, str):
            details = json.loads(details)
        queue.append({
            "log_id": r["log_id"],
            "created_at": r["created_at"],
            **details
        })
    return {"queue": queue, "total": len(queue)}

@router.post("/payment/{hitl_ref}/decide")
async def decide_payment(
    hitl_ref: str,
    d: PaymentHoldDecision,
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "controller"])),
):
    row = await db.fetchrow(
        "SELECT details FROM audit_log WHERE event_type='PAYMENT_HITL' AND action='unknown_sender_hitl' AND details->>'hitl_ref'=$1", hitl_ref
    )
    if not row:
        raise HTTPException(404, "Payment hold not found")
        
    details = row['details']
    if isinstance(details, str): import json; details = json.loads(details)

    if d.decision == "approved":
        inv = await db.fetchrow("SELECT balance_due_inr FROM invoices WHERE invoice_id=$1", d.invoice_id)
        if not inv: raise HTTPException(400, "Invoice not found or already paid")
        bal = float(inv["balance_due_inr"])
        
        await db.execute(
            "UPDATE invoices SET amount_paid_inr = amount_paid_inr + $1, balance_due_inr = 0, payment_status = 'paid' WHERE invoice_id = $2",
            bal, d.invoice_id
        )
        await db.execute(
            "UPDATE ar_ledger SET outstanding_balance_inr = 0, payment_status = 'paid', last_action = 'hitl_approved_payment' WHERE invoice_id = $1",
            d.invoice_id
        )
        pay_id = f"PAY-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        await db.execute(
            "INSERT INTO payments (payment_id, invoice_id, amount_inr, payment_date, payment_method, status) VALUES ($1, $2, $3, NOW(), 'bank_transfer_email', 'processed')",
            pay_id, d.invoice_id, bal
        )
        import json
        await db.execute(
            """INSERT INTO audit_log
               (event_type, agent_name, invoice_id, customer_id, action, details,
                actor_type, actor_username, actor_role,
                previous_value, new_value)
               VALUES ('PAYMENT_HITL', $1, $2, $3, 'approved', $4::jsonb,
                       'human', $5, $6,
                       $7::jsonb, $8::jsonb)""",
            staff["username"], d.invoice_id, d.customer_id,
            json.dumps({"hitl_ref": hitl_ref, "payment_id": pay_id, "notes": d.notes}),
            staff["username"], staff["role"],
            json.dumps({"balance_due_inr": float(inv["balance_due_inr"] or 0), "payment_status": "pending"}),
            json.dumps({"balance_due_inr": 0, "payment_status": "paid"})
        )
        _send_email(
            to=details.get("email"),
            subject=f"Payment Processed — {d.invoice_id}",
            body=(f"Your payment has been manually reviewed and applied to invoice {d.invoice_id}.\nPayment ID: {pay_id}\n")
        )
    else:
        import json
        await db.execute(
            """INSERT INTO audit_log
               (event_type, agent_name, action, details,
                actor_type, actor_username, actor_role)
               VALUES ('PAYMENT_HITL', $1, 'rejected', $2::jsonb,
                       'human', $3, $4)""",
            staff["username"],
            json.dumps({"hitl_ref": hitl_ref, "notes": d.notes}),
            staff["username"], staff["role"]
        )
        _send_email(
            to=details.get("email"),
            subject=f"Payment Rejected — {details.get('invoice', 'Unknown')}",
            body=(f"Your payment request was reviewed but could not be processed.\nReason: {d.notes}\n")
        )

    return {"success": True, "hitl_ref": hitl_ref, "decision": d.decision}


# ══════════════════════════════════════════════════════════════════
# ORDER HOLD QUEUE
# ══════════════════════════════════════════════════════════════════

@router.get("/queue")
async def hitl_queue(db=Depends(get_db), staff=Depends(require_role(HITL_ROLES))):
    """Orders pending human review."""
    rows = await db.fetch(
        """SELECT o.*, c.company_name, c.email as customer_email
           FROM orders o
           JOIN customers c ON o.customer_id = c.customer_id
           WHERE o.hitl_required = TRUE AND (o.hitl_resolved_by = '' OR o.hitl_resolved_by IS NULL)
           ORDER BY o.created_at DESC"""
    )
    return {"queue": [dict(r) for r in rows], "total": len(rows)}


@router.post("/{order_id}/decide")
async def hitl_decide(
    order_id: str,
    decision: HITLDecision,
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "controller"])),
):
    """Approve or reject an order in the HITL queue."""
    order = await db.fetchrow("SELECT * FROM orders WHERE order_id=$1", order_id)
    if not order:
        raise HTTPException(404, "Order not found")
        
    prev_status = order["status"]
    await db.execute(
        "UPDATE orders SET hitl_resolved_by=$1, status=$2, updated_at=NOW() WHERE order_id=$3",
        staff["username"], decision.decision, order_id
    )
    import json as _json
    await db.execute(
        """INSERT INTO audit_log
           (event_type, agent_name, order_id, action, details,
            actor_type, actor_username, actor_role,
            previous_value, new_value)
           VALUES ($1,$2,$3,$4,$5,
                   'human',$6,$7,
                   $8::jsonb,$9::jsonb)""",
        "HITL_DECISION", staff["username"], order_id, decision.decision,
        _json.dumps({"notes": decision.notes}),
        staff["username"], staff["role"],
        _json.dumps({"status": prev_status, "hitl_resolved_by": ""}),
        _json.dumps({"status": decision.decision, "hitl_resolved_by": staff["username"]})
    )
    
    if decision.decision == "approved":
        from datetime import timedelta
        # Agent 5: Auto-generate Invoice and AR Ledger entry
        invoice_id = f"INV-{order_id.split('-')[-1]}"
        due_date = datetime.now() + timedelta(days=30)
        
        await db.execute(
            """INSERT INTO invoices (invoice_id, order_id, customer_id, due_date, subtotal_inr, total_amount_inr, balance_due_inr, payment_status)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            invoice_id, order_id, order["customer_id"], due_date,
            order["subtotal_inr"], order["total_amount_inr"], order["total_amount_inr"], "pending"
        )
        await db.execute(
            """INSERT INTO ar_ledger (ar_id, invoice_id, customer_id, amount_inr, outstanding_balance_inr, aging_bucket, payment_status, last_action)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            f"AR-{invoice_id}", invoice_id, order["customer_id"], order["total_amount_inr"], order["total_amount_inr"],
            "0-30", "pending", "invoice_generated"
        )
        # Log approval in audit trail with real actor identity
        await db.execute(
            """INSERT INTO audit_log
               (event_type, agent_name, order_id, customer_id, action, details,
                actor_type, actor_username, actor_role)
               VALUES ($1,$2,$3,$4,$5,$6,'human',$7,$8)""",
            "HITL_APPROVED", staff["username"], order_id, order["customer_id"],
            "invoice_generated",
            '{"source": "hitl_approval"}',
            staff["username"], staff["role"]
        )
        # Write credit_decisions for ECOA compliance (Agent 2 — human override path)
        try:
            customer_row = await db.fetchrow("SELECT * FROM customers WHERE customer_id=$1", order["customer_id"])
            if customer_row:
                await db.execute(
                    """INSERT INTO credit_decisions
                       (decision_id, customer_id, order_id, decision_type, credit_tier,
                        credit_limit_inr, pd_score, credit_risk_class, decision, decision_reason,
                        model_used, created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,NOW())""",
                    f"CD-HITL-{order_id}",
                    order["customer_id"],
                    order_id,
                    "hitl_override",
                    customer_row.get("credit_tier", "B"),
                    float(customer_row.get("credit_limit_inr", 100000)),
                    0.0,   # PD not recomputed on HITL — human judgment overrides model
                    "HUMAN_OVERRIDE",
                    "approved",
                     f"HITL approved by {staff['username']} ({staff['role']})",
                     staff["username"],
                )
        except Exception as e:
            logger.warning(f"credit_decisions HITL insert (non-critical): {e}")

    # ── Notify the customer of the HITL decision via email ───────────────
    try:
        cust_email_row = await db.fetchrow(
            "SELECT email, contact_name, company_name FROM customers WHERE customer_id=$1",
            order["customer_id"]
        )
        if cust_email_row and cust_email_row.get("email"):
            from api.customer_portal import send_email
            cust_name = cust_email_row.get("contact_name") or cust_email_row.get("company_name") or "Customer"
            if decision.decision == "approved":
                _send_email(
                    to=cust_email_row["email"],
                    subject=f"Order Approved — {order_id}",
                    body=(
                        f"Dear {cust_name},\n\n"
                        f"Great news! Your order {order_id} has been reviewed and approved by our Finance Controller.\n\n"
                        f"An invoice has been raised against your account.\n"
                        f"Please log in to the portal to view and pay your invoice:\n"
                        f"  Portal URL: http://localhost:5173/portal/login\n\n"
                        f"Reviewer Notes: {decision.notes or 'Approved after manual review.'}\n\n"
                        f"Regards,\nMAQ Manufacturing — Finance Team"
                    )
                )
            else:
                _send_email(
                    to=cust_email_row["email"],
                    subject=f"Order Update — {order_id}",
                    body=(
                        f"Dear {cust_name},\n\n"
                        f"Unfortunately, your order {order_id} could not be processed at this time "
                        f"after our Finance Controller's review.\n\n"
                        f"Decision: {decision.decision.upper()}\n"
                        f"Reason: {decision.notes or 'Did not meet our current approval criteria.'}\n\n"
                        f"If you have questions, please contact our helpdesk at {HELPDESK_EMAIL} "
                        f"quoting Order ID {order_id}.\n\n"
                        f"Regards,\nMAQ Manufacturing — Finance Team"
                    )
                )
            logger.info(f"HITL decision email sent to {cust_email_row['email']} for {order_id}")
    except Exception as e:
        logger.warning(f"HITL notification email failed (non-critical): {e}")

    return {"order_id": order_id, "decision": decision.decision, "reviewer": decision.reviewer}


@router.get("/stats")
async def hitl_stats(db=Depends(get_db), staff=Depends(require_role(HITL_ROLES))):
    """Summary stats for both queues."""
    order_pending  = await db.fetchval("SELECT COUNT(*) FROM orders WHERE hitl_required=TRUE AND (hitl_resolved_by='' OR hitl_resolved_by IS NULL)")
    order_resolved = await db.fetchval("SELECT COUNT(*) FROM orders WHERE hitl_required=TRUE AND hitl_resolved_by != ''")
    try:
        kyc_pending  = await db.fetchval("SELECT COUNT(*) FROM customer_kyc_requests WHERE status='pending'")
        kyc_approved = await db.fetchval("SELECT COUNT(*) FROM customer_kyc_requests WHERE status='approved'")
        kyc_rejected = await db.fetchval("SELECT COUNT(*) FROM customer_kyc_requests WHERE status='rejected'")
    except Exception:
        kyc_pending = kyc_approved = kyc_rejected = 0

    try:
        payment_pending = await db.fetchval("""
            SELECT COUNT(*) FROM audit_log
            WHERE event_type = 'PAYMENT_HITL' AND action = 'unknown_sender_hitl'
              AND details->>'hitl_ref' NOT IN (
                  SELECT details->>'hitl_ref' FROM audit_log
                  WHERE event_type = 'PAYMENT_HITL' AND action IN ('approved', 'rejected')
              )
        """)
    except Exception:
        payment_pending = 0

    return {
        "orders": {"pending": order_pending, "resolved": order_resolved},
        "kyc": {"pending": kyc_pending, "approved": kyc_approved, "rejected": kyc_rejected},
        "payment": {"pending": payment_pending},
        "total_pending": (order_pending or 0) + (kyc_pending or 0) + (payment_pending or 0),
    }


# ══════════════════════════════════════════════════════════════════
# KYC QUEUE
# ══════════════════════════════════════════════════════════════════

@router.get("/kyc-queue")
async def kyc_queue(db=Depends(get_db), staff=Depends(require_role(HITL_ROLES))):
    """List all pending new-customer KYC requests."""
    rows = await db.fetch(
        "SELECT * FROM customer_kyc_requests ORDER BY submitted_at DESC"
    )
    return {"queue": [dict(r) for r in rows], "total": len(rows)}


@router.post("/kyc/{kyc_id}/decide")
async def kyc_decide(kyc_id: str, decision: KYCDecision, db=Depends(get_db), staff=Depends(require_role(HITL_ROLES))):
    """
    Approve or reject a KYC application.
    - Approve: Creates customer record, sets password, sends welcome email.
    - Reject: Sends rejection email with helpdesk contact.
    """
    kyc = await db.fetchrow(
        "SELECT * FROM customer_kyc_requests WHERE kyc_id = $1", kyc_id
    )
    if not kyc:
        raise HTTPException(404, f"KYC request {kyc_id} not found")
    kyc = dict(kyc)

    if kyc["status"] != "pending":
        raise HTTPException(400, f"KYC {kyc_id} already {kyc['status']}")

    # Update KYC record status
    await db.execute(
        """UPDATE customer_kyc_requests
           SET status=$1, reviewer=$2, review_notes=$3, rejection_reason=$4, reviewed_at=NOW()
           WHERE kyc_id=$5""",
        decision.decision, decision.reviewer, decision.notes,
        decision.rejection_reason, kyc_id
    )

    if decision.decision == "approved":
        # Generate customer ID and temporary password
        cust_id  = f"CUST-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        temp_pwd = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        pwd_hash = hash_password(temp_pwd)

        # Assign credit tier based on annual turnover (Tier A for > ₹1Cr turnover)
        tier_map = {"< 10L": "D", "10L-1Cr": "C", "> 1Cr": "A"}
        credit_tier  = tier_map.get(kyc.get("annual_turnover", ""), "C")
        credit_limit = {"A": 2000000, "B": 500000, "C": 200000, "D": 100000}[credit_tier]

        await db.execute(
            """INSERT INTO customers
               (customer_id, company_name, contact_name, email, phone, gstin,
                billing_address, city, state, credit_tier, credit_limit_inr,
                is_active, portal_active, password_hash, kyc_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,TRUE,TRUE,$12,$13)
               ON CONFLICT (customer_id) DO NOTHING""",
            cust_id, kyc["company_name"], kyc["contact_name"], kyc["email"],
            kyc.get("phone",""), kyc.get("gstin",""), kyc.get("address",""),
            kyc.get("city",""), kyc.get("state",""), credit_tier, credit_limit,
            pwd_hash, kyc_id
        )

        # Welcome email with credentials
        _send_email(
            to=kyc["email"],
            subject="Welcome to MAQ Manufacturing Portal — Account Approved!",
            body=(
                f"Dear {kyc['contact_name']},\n\n"
                f"Great news! Your application for {kyc['company_name']} has been approved.\n\n"
                f"Your customer portal account is now active:\n"
                f"  Portal URL: http://localhost:5173/portal/login\n"
                f"  Email: {kyc['email']}\n"
                f"  Temporary Password: {temp_pwd}\n\n"
                f"Please login and change your password immediately.\n"
                f"Your Account ID: {cust_id} | Credit Tier: {credit_tier} | Limit: ₹{credit_limit:,}\n\n"
                f"Regards,\nMAQ Manufacturing — Onboarding Team"
            )
        )

        # Add new customer to ChromaDB so email NER can match them in future orders
        try:
            from database.chromadb_client import get_customers_collection
            from ml.embeddings import embed_text
            col = get_customers_collection()
            emb = embed_text(kyc["company_name"])
            col.upsert(
                ids=[cust_id],
                embeddings=[emb],
                metadatas=[{"customer_id": cust_id, "company_name": kyc["company_name"],
                             "email": kyc["email"], "credit_tier": credit_tier}],
                documents=[kyc["company_name"]],
            )
            logger.info(f"New customer {cust_id} added to ChromaDB vector store")
        except Exception as e:
            logger.warning(f"ChromaDB upsert for new customer failed (non-critical): {e}")

        logger.info(f"KYC {kyc_id} approved → customer {cust_id} created")

        # Process any pending order emails held for this customer's email address
        pending_orders = await db.fetch(
            "SELECT * FROM pending_order_emails WHERE LOWER(email_from)=$1 AND status='awaiting_registration'",
            kyc["email"].lower()
        )
        processed_count = 0
        if pending_orders:
            import httpx
            from config import settings as app_settings
            for po in pending_orders:
                try:
                    resp = httpx.post(
                        f"http://localhost:{app_settings.app_port}/api/orders/ingest-email",
                        json={"email_text": po["email_text"], "email_from": kyc["email"],
                              "subject": po["subject"]},
                        headers={"Authorization": f"Bearer {create_service_token()}"},
                        timeout=120.0
                    )
                    await db.execute(
                        "UPDATE pending_order_emails SET status='processed', processed_at=NOW() WHERE id=$1",
                        po["id"]
                    )
                    processed_count += 1
                    logger.info(f"Processed pending order id={po['id']} for new customer {cust_id}")
                except Exception as e:
                    logger.warning(f"Failed to process pending order id={po['id']}: {e}")

            if processed_count:
                _send_email(
                    to=kyc["email"],
                    subject="Your Order Has Been Processed — MAQ Manufacturing",
                    body=(
                        f"Dear {kyc['contact_name']},\n\n"
                        f"Your account has been approved and your pending order request "
                        f"has been processed automatically.\n\n"
                        f"Login to the portal to track your order:\n"
                        f"  Portal URL: http://localhost:5173/portal/login\n"
                        f"  Email: {kyc['email']}\n"
                        f"  Temporary Password: {temp_pwd}\n\n"
                        f"Regards,\nMAQ Manufacturing — Order Team"
                    )
                )

        return {
            "kyc_id": kyc_id, "decision": "approved",
            "customer_id": cust_id, "temp_password": temp_pwd,
            "pending_orders_processed": processed_count,
            "message": f"Customer account created. Welcome email sent to {kyc['email']}"
        }

    else:
        # Rejection email
        reason = decision.rejection_reason or "Did not meet our current onboarding criteria."
        _send_email(
            to=kyc["email"],
            subject="O2C Portal — Application Status Update",
            body=(
                f"Dear {kyc['contact_name']},\n\n"
                f"Thank you for your interest in MAQ Manufacturing's B2B portal.\n\n"
                f"After reviewing your application for {kyc['company_name']}, "
                f"we are unable to approve your account at this time.\n\n"
                f"Reason: {reason}\n\n"
                f"If you believe this is an error or have questions, please contact our helpdesk:\n"
                f"  Email: {HELPDESK_EMAIL}\n"
                f"  Reference: {kyc_id}\n\n"
                f"Regards,\nMAQ Manufacturing — Onboarding Team"
            )
        )

        logger.info(f"KYC {kyc_id} rejected")
        return {
            "kyc_id": kyc_id, "decision": "rejected",
            "message": f"Rejection email sent to {kyc['email']}"
        }
