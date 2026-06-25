"""
O2C Agent v2.0 — Customer Portal API
Handles new customer KYC registration, customer authentication,
order history, outstanding invoices, and order placement (form + NLP).
"""
import logging
import uuid
import smtplib
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from jose import JWTError, ExpiredSignatureError, jwt

from database.postgres import get_db
from config import settings
from passwords import hash_password, is_legacy_sha256_hash, verify_password
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from api.orders import reserve_inventory_for_order, _inventory_response_fields

router = APIRouter()
logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

HELPDESK_EMAIL = "helpdesk@maqsoftware.com"


# ── Auth helpers ─────────────────────────────────────────────────────────

def create_customer_token(customer_id: str, email: str, company: str) -> str:
    payload = {
        "sub": customer_id,
        "email": email,
        "company": company,
        "role": "customer",
        "exp": datetime.utcnow() + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def decode_customer_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("role") != "customer":
            raise HTTPException(status_code=403, detail="Not a customer token")
        return payload
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_customer(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db=Depends(get_db),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_customer_token(credentials.credentials)
    row = await db.fetchrow(
        "SELECT * FROM customers WHERE customer_id = $1 AND portal_active = TRUE",
        payload["sub"]
    )
    if not row:
        raise HTTPException(status_code=401, detail="Customer account not found or inactive")
    return dict(row)


# ── Email helper ─────────────────────────────────────────────────────────

def send_email(
    to: str,
    subject: str,
    body: str,
    attachments: Optional[List[tuple]] = None,
) -> tuple[bool, str]:
    """Send email via Gmail SMTP. Returns (success, error_message).

    ``attachments`` is an optional list of ``(filename, content_bytes, mime_subtype)``
    tuples; each is attached to the outgoing message (e.g. a PDF invoice).
    """
    if not settings.smtp_user or not settings.smtp_password:
        msg = "SMTP not configured (SMTP_USER/SMTP_PASSWORD missing in .env)"
        logger.warning(msg)
        return False, msg
    try:
        email_msg = MIMEMultipart("mixed")
        email_msg["Subject"] = subject
        email_msg["From"]    = settings.email_from
        email_msg["To"]      = to
        email_msg.attach(MIMEText(body, "plain"))
        for attachment in attachments or []:
            filename, content_bytes, mime_subtype = attachment
            part = MIMEApplication(content_bytes, _subtype=mime_subtype)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            email_msg.attach(part)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_tls:
                server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.email_from, to, email_msg.as_string())
        logger.info(f"Email sent to {to}: {subject}")
        return True, ""
    except Exception as e:
        err = str(e)
        logger.error(f"Email send failed to {to}: {err}")
        return False, err


# ══════════════════════════════════════════════════════════════════════════
# KYC REGISTRATION (New Customer)
# ══════════════════════════════════════════════════════════════════════════

import random

# In-memory OTP cache mapping: email -> {"code": "123456", "expires_at": datetime}
# For production, this should be in Redis or Postgres `otp_codes` table.
_otp_cache = {}

class SendOTPRequest(BaseModel):
    email: str
    contact_name: str = "Customer"

@router.post("/kyc-send-otp")
async def send_kyc_otp(payload: SendOTPRequest):
    """Generates a 6-digit OTP and sends it via email."""
    code = f"{random.randint(0, 999999):06d}"
    
    _otp_cache[payload.email.lower()] = {
        "code": code,
        "expires_at": datetime.utcnow() + timedelta(minutes=10)
    }

    body = (
        f"Dear {payload.contact_name},\n\n"
        f"Your verification code for MAQ Manufacturing B2B Portal registration is:\n\n"
        f"   {code}\n\n"
        f"This code will expire in 10 minutes.\n\n"
        f"Regards,\nMAQ Manufacturing Team"
    )
    
    # We use send_email which gracefully falls back if SMTP is not configured
    send_email(
        to=payload.email,
        subject="Your O2C Portal Verification Code",
        body=body
    )
    
    return {"message": "OTP sent successfully"}


class KYCRequest(BaseModel):
    company_name: str
    contact_name: str
    email: str
    phone: str
    gstin: str
    pan_number: str
    business_type: str            # Manufacturer | Distributor | Retailer | Trader | Other
    state: str
    city: str
    address: str
    annual_turnover: str = ""     # "< 10L" | "10L-1Cr" | "> 1Cr"
    otp_code: str


@router.post("/register")
async def submit_kyc(payload: KYCRequest, db=Depends(get_db)):
    """New customer submits KYC form. Creates a pending KYC request for HITL review."""
    # Check if email already registered as a customer
    existing = await db.fetchrow(
        "SELECT customer_id FROM customers WHERE LOWER(email) = LOWER($1)", payload.email
    )
    if existing:
        raise HTTPException(400, detail="An account with this email already exists. Please login instead.")

    # Validate OTP
    cached = _otp_cache.get(payload.email.lower())
    if not cached:
        raise HTTPException(400, detail="No OTP requested or OTP expired. Please request a new one.")
    if cached["expires_at"] < datetime.utcnow():
        raise HTTPException(400, detail="OTP has expired. Please request a new one.")
    if cached["code"] != payload.otp_code:
        raise HTTPException(400, detail="Invalid OTP code.")


    # Check if KYC already pending
    pending = await db.fetchrow(
        "SELECT kyc_id FROM customer_kyc_requests WHERE LOWER(email) = LOWER($1) AND status = 'pending'",
        payload.email
    )
    if pending:
        raise HTTPException(400, detail="A KYC application for this email is already under review.")

    kyc_id = f"KYC-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    await db.execute(
        """INSERT INTO customer_kyc_requests
           (kyc_id, company_name, contact_name, email, phone, gstin, pan_number,
            business_type, state, city, address, annual_turnover, status)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'pending')""",
        kyc_id, payload.company_name, payload.contact_name, payload.email,
        payload.phone, payload.gstin, payload.pan_number, payload.business_type,
        payload.state, payload.city, payload.address, payload.annual_turnover
    )

    # Clear OTP after successful consumption
    _otp_cache.pop(payload.email.lower(), None)

    # Send confirmation email
    send_email(
        to=payload.email,
        subject="O2C Portal — We received your application",
        body=(
            f"Dear {payload.contact_name},\n\n"
            f"Thank you for applying to MAQ Manufacturing's B2B Customer Portal.\n\n"
            f"Your application (ID: {kyc_id}) for {payload.company_name} is under review.\n"
            f"Our team typically completes background verification within 1-2 business days.\n\n"
            f"You will receive a confirmation email once a decision has been made.\n\n"
            f"If you have questions, email: {HELPDESK_EMAIL}\n\n"
            f"Regards,\nMAQ Manufacturing — Onboarding Team"
        )
    )

    return {
        "kyc_id": kyc_id,
        "status": "pending",
        "message": "Application submitted successfully. You will hear from us within 1-2 business days.",
        "email_sent_to": payload.email
    }


# ══════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def customer_login(payload: LoginRequest, db=Depends(get_db)):
    """Customer login — returns JWT for portal access."""
    row = await db.fetchrow(
        "SELECT * FROM customers WHERE LOWER(email) = LOWER($1)", payload.email
    )
    if not row:
        raise HTTPException(401, detail="No account found with this email.")

    row = dict(row)
    stored_hash = row.get("password_hash", "")
    password_valid = verify_password(payload.password, stored_hash)
    if not password_valid and is_legacy_sha256_hash(stored_hash):
        import hashlib
        password_valid = hashlib.sha256(payload.password.encode()).hexdigest() == stored_hash
        if password_valid:
            await db.execute(
                "UPDATE customers SET password_hash = $1, updated_at = NOW() WHERE customer_id = $2",
                hash_password(payload.password),
                row["customer_id"],
            )

    if not password_valid:
        raise HTTPException(401, detail="Incorrect password.")

    if not row.get("portal_active", True):
        raise HTTPException(403, detail="Your account is currently inactive. Contact " + HELPDESK_EMAIL)

    token = create_customer_token(row["customer_id"], row["email"], row["company_name"])
    return {
        "token": token,
        "customer_id": row["customer_id"],
        "company_name": row["company_name"],
        "contact_name": row.get("contact_name", ""),
        "email": row["email"],
        "credit_tier": row.get("credit_tier", "B"),
    }


# ══════════════════════════════════════════════════════════════════════════
# CUSTOMER PROFILE
# ══════════════════════════════════════════════════════════════════════════

@router.get("/me")
async def get_profile(customer=Depends(get_current_customer)):
    """Return customer profile (excludes password hash)."""
    safe = {k: v for k, v in customer.items() if k != "password_hash"}
    return safe


# ══════════════════════════════════════════════════════════════════════════
# ORDER HISTORY
# ══════════════════════════════════════════════════════════════════════════

@router.get("/orders")
async def get_my_orders(
    limit: int = 50,
    customer=Depends(get_current_customer),
    db=Depends(get_db)
):
    """Customer's own order history."""
    rows = await db.fetch(
        """SELECT o.*, p.product_name FROM orders o
           LEFT JOIN products p ON o.sku_id = p.sku_id
           WHERE o.customer_id = $1
           ORDER BY o.created_at DESC LIMIT $2""",
        customer["customer_id"], limit
    )
    return {"orders": [dict(r) for r in rows], "total": len(rows)}


@router.get("/orders/{order_id}")
async def get_my_order(
    order_id: str,
    customer=Depends(get_current_customer),
    db=Depends(get_db)
):
    """Get details of a specific order, including reservation details."""
    row = await db.fetchrow(
        """SELECT o.*, p.product_name FROM orders o
           LEFT JOIN products p ON o.sku_id = p.sku_id
           WHERE o.order_id = $1 AND o.customer_id = $2""",
        order_id, customer["customer_id"]
    )
    if not row:
        raise HTTPException(404, "Order not found")
    result = dict(row)
    reservations = await db.fetch(
        "SELECT reservation_id, sku_id, quantity_requested, quantity_reserved, "
        "quantity_backordered, status, expected_availability_date, reserved_at, "
        "released_at, fulfilled_at FROM inventory_reservations WHERE order_id = $1 "
        "ORDER BY reserved_at DESC",
        order_id,
    )
    result["reservations"] = [dict(r) for r in reservations]
    return result


# ══════════════════════════════════════════════════════════════════════════
# PAYMENT HISTORY
# ══════════════════════════════════════════════════════════════════════════

@router.get("/payments")
async def get_my_payments(
    limit: int = 50,
    customer=Depends(get_current_customer),
    db=Depends(get_db)
):
    """Customer's payment history."""
    try:
        rows = await db.fetch(
            """SELECT pay.*, inv.total_amount_inr as invoice_total
               FROM payments pay
               JOIN invoices inv ON pay.invoice_id = inv.invoice_id
               WHERE inv.customer_id = $1
               ORDER BY pay.payment_date DESC LIMIT $2""",
            customer["customer_id"], limit
        )
        return {"payments": [dict(r) for r in rows], "total": len(rows)}
    except Exception as e:
        logger.warning(f"Payments table may not exist yet: {e}")
        return {"payments": [], "total": 0}


# ══════════════════════════════════════════════════════════════════════════
# OUTSTANDING INVOICES
# ══════════════════════════════════════════════════════════════════════════

@router.get("/outstanding")
async def get_outstanding(
    customer=Depends(get_current_customer),
    db=Depends(get_db)
):
    """Unpaid invoices for current customer — includes payment_token for Pay Now."""
    rows = await db.fetch(
        """SELECT invoice_id, order_id, invoice_date, due_date,
                  total_amount_inr, balance_due_inr, payment_status, days_overdue,
                  payment_token
           FROM invoices
           WHERE customer_id = $1 AND payment_status IN ('pending', 'overdue', 'partial')
           ORDER BY days_overdue DESC""",
        customer["customer_id"]
    )
    total_outstanding = sum(float(r["balance_due_inr"] or 0) for r in rows)
    return {
        "invoices": [dict(r) for r in rows],
        "total": len(rows),
        "total_outstanding_inr": total_outstanding
    }


@router.post("/outstanding/{invoice_id}/pay")
async def pay_invoice_mock(
    invoice_id: str,
    customer=Depends(get_current_customer),
    db=Depends(get_db)
):
    """Mock endpoint to instantly pay an invoice for testing."""
    inv = await db.fetchrow(
        "SELECT * FROM invoices WHERE invoice_id = $1 AND customer_id = $2",
        invoice_id, customer["customer_id"]
    )
    if not inv:
        raise HTTPException(404, "Invoice not found")
        
    bal = float(inv["balance_due_inr"])
    if bal <= 0:
        return {"message": "Already paid"}

    # Insert payment record
    pay_id = f"PAY-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    await db.execute(
        """INSERT INTO payments (payment_id, invoice_id, amount_inr, payment_date, payment_method, status)
           VALUES ($1, $2, $3, NOW(), 'bank_transfer', 'completed')""",
        pay_id, invoice_id, bal
    )
    
    # Update invoice
    await db.execute(
        """UPDATE invoices 
           SET amount_paid_inr = amount_paid_inr + $1, balance_due_inr = 0, payment_status = 'paid'
           WHERE invoice_id = $2""",
        bal, invoice_id
    )
    
    # Update AR Ledger
    await db.execute(
        """UPDATE ar_ledger 
           SET outstanding_balance_inr = 0, payment_status = 'paid', last_action = 'payment_received'
           WHERE invoice_id = $1""",
        invoice_id
    )

    # ── Credit History entry — source='customer_portal' ──────────────────────
    # Every portal payment appears in Credit History so admin/collections can
    # see the full balance adjustment timeline per customer and per invoice.
    import datetime as _dt
    memo_id = f"MEMO-PAY-{_dt.datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:22]}"
    # Look up order_id for this invoice
    inv_row = await db.fetchrow("SELECT order_id FROM invoices WHERE invoice_id = $1", invoice_id)
    order_id_for_memo = inv_row["order_id"] if inv_row else None
    try:
        await db.execute(
            """INSERT INTO credit_memos
               (memo_id, order_id, invoice_id, customer_id,
                amount_inr, reason, approved_by, approved_by_role,
                balance_before_inr, balance_after_inr,
                source, payment_ref)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            memo_id,
            order_id_for_memo,
            invoice_id,
            customer["customer_id"],
            bal,
            f"Customer portal payment — {pay_id}",
            customer.get("contact_name") or customer.get("company_name") or customer["customer_id"],
            "customer",
            bal,         # balance_before = full outstanding
            0.0,         # balance_after  = 0 (fully paid)
            "customer_portal",
            pay_id,      # payment_ref = the payment record ID
        )
    except Exception as e:
        logger.warning(f"credit_memo insert for portal payment failed (non-critical): {e}")

    # Send payment receipt email
    send_email(
        to=customer["email"],
        subject=f"Payment Receipt — {invoice_id}",
        body=(
            f"Dear {customer.get('contact_name') or customer.get('company_name')},\n\n"
            f"This is a confirmation that your payment has been successfully processed.\n\n"
            f"Payment ID  : {pay_id}\n"
            f"Invoice ID  : {invoice_id}\n"
            f"Amount Paid : ₹{bal:,.0f}\n"
            f"Method      : Bank Transfer\n"
            f"Date        : {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}\n"
            f"Status      : PAID IN FULL\n\n"
            f"Thank you for your prompt payment. This invoice is now marked as cleared.\n"
            f"Please retain this email as your payment receipt for your records.\n\n"
            f"Regards,\nMAQ Manufacturing — Finance Team"
        )
    )

    return {"message": f"Successfully paid ₹{bal} for invoice {invoice_id}"}



# ══════════════════════════════════════════════════════════════════════════
# PLACE ORDER — Structured Form
# ══════════════════════════════════════════════════════════════════════════

class PortalOrderRequest(BaseModel):
    sku_id: str
    quantity: int
    delivery_address: Optional[str] = None
    requested_delivery_date: Optional[str] = None
    po_reference: Optional[str] = None


@router.post("/orders")
async def place_order(
    payload: PortalOrderRequest,
    customer=Depends(get_current_customer),
    db=Depends(get_db)
):
    """Place a new order via the structured portal form."""
    # Get product
    product = await db.fetchrow(
        "SELECT * FROM products WHERE sku_id = $1 AND is_active = TRUE", payload.sku_id
    )
    if not product:
        raise HTTPException(404, f"Product {payload.sku_id} not found")

    product = dict(product)
    unit_price = float(product["base_price_inr"])
    subtotal = unit_price * payload.quantity
    gst_pct = float(product.get("gst_rate_pct", 18))
    gst_amount = subtotal * gst_pct / 100
    total = subtotal + gst_amount

    # Parse delivery date safely
    parsed_date = None
    if payload.requested_delivery_date:
        try:
            parsed_date = datetime.fromisoformat(payload.requested_delivery_date.replace('Z', '+00:00'))
        except ValueError:
            pass  # Leave as None if it's free-text like 'next Monday'

    order_id = f"ORD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-P"

    # ── Agent 3: Fraud Check ────────────────────────────────────────────
    from ml.isolation_forest import score_order
    from ml.model_placeholders import predict_fraud
    from policy.policy_engine import policy_engine, PolicyAction

    ar_sum = await db.fetchval(
        "SELECT SUM(outstanding_balance_inr) FROM ar_ledger WHERE customer_id = $1",
        customer["customer_id"]
    )
    dynamic_open_ar = float(ar_sum or 0)

    if_ctx = {
        "total_amount_inr": total,
        "quantity": payload.quantity,
        "unit_price_inr": unit_price,
        "avg_dso_days": float(customer.get("avg_dso_days", 30)),
        "missed_payments_12m": int(customer.get("missed_payments_12m", 0)),
        "open_ar_balance_inr": dynamic_open_ar,
        "account_age_months": int(customer.get("account_age_months", 12)),
        "channel": "portal",
    }
    if_result = score_order(if_ctx)
    fraud_result = predict_fraud({
        "amount_inr": total,
        "customer_age_months": int(customer.get("account_age_months", 12)),
        "avg_days_late": max(0, float(customer.get("avg_dso_days", 30)) - 30),
        "missed_payments": if_ctx["missed_payments_12m"],
        "open_ar_ratio": if_ctx["open_ar_balance_inr"] / max(float(customer.get("credit_limit_inr", 100000)), 1),
        "is_new_customer": False,
        "hour_of_day": datetime.utcnow().hour,
        "channel": "portal",
    })

    # ── Agent 2: Credit Policy — XGBoost 3-class + PD Model ────────────
    from ml.model_placeholders import predict_credit_risk
    credit_result = predict_credit_risk({
        "order_value_inr":       total,
        "credit_limit_inr":      float(customer.get("credit_limit_inr", 100000)),
        "open_ar_balance_inr":   if_ctx["open_ar_balance_inr"],
        "avg_days_late":         max(0.0, float(customer.get("avg_dso_days", 30)) - 30),
        "missed_payment_count":  if_ctx["missed_payments_12m"],
        "account_age_months":    if_ctx["account_age_months"],
        "industry_segment":      customer.get("industry_segment", "Manufacturing"),
        "payment_tier":          {"A": 1, "B": 2, "C": 3, "D": 4}.get(
                                     customer.get("credit_tier", "B"), 2),
        "credit_tier":           customer.get("credit_tier", "B"),
    })

    # ── Agent 2: Rule Engine + Policy Check ────────────────────────────
    policy_result = await policy_engine.evaluate(
        agent_name="agent_01_order_ingestion",
        tool_name="persist_order",
        tool_args={"sku_id": payload.sku_id, "quantity": payload.quantity},
        context={
            "fraud_probability":    fraud_result["fraud_probability"],
            "order_amount_inr":     total,
            "credit_limit_inr":     float(customer.get("credit_limit_inr", 100000)),
            "open_ar_balance_inr":  if_ctx["open_ar_balance_inr"],
            "customer_id":          customer["customer_id"],
        }
    )

    hitl_required = policy_result["action"] in (PolicyAction.REQUIRE_HITL, PolicyAction.BLOCK)
    status = "fraud_review" if fraud_result["fraud_verdict"] == "FRAUD" else (
        "hitl_required" if hitl_required else "approved"
    )

    async with db.transaction():
        await db.execute(
            """INSERT INTO orders
               (order_id, customer_id, sku_id, quantity, unit_price_inr, subtotal_inr,
                gst_pct, gst_amount_inr, total_amount_inr, delivery_address,
                requested_delivery_date, po_reference, channel, status,
                fraud_score, isolation_forest_score, hitl_required)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'portal',$13,$14,$15,$16)""",
            order_id, customer["customer_id"], payload.sku_id, payload.quantity,
            unit_price, subtotal, gst_pct, gst_amount, total,
            payload.delivery_address or customer.get("shipping_address", ""),
            parsed_date,
            payload.po_reference or "",
            "pending_inventory",
            fraud_result["fraud_probability"],
            if_result["anomaly_score"],
            hitl_required,
        )

        inventory_result = await reserve_inventory_for_order(
            db, order_id, payload.sku_id, payload.quantity, customer["customer_id"],
            performed_by=customer.get("email") or customer["customer_id"],
            actor_type="customer",
            current_status=status,
        )
        status = inventory_result["final_status"]
        hitl_required = hitl_required or inventory_result["hitl_required"]
        await db.execute(
            "UPDATE orders SET status=$1, hitl_required=$2, updated_at=NOW() WHERE order_id=$3",
            status, hitl_required, order_id,
        )

    import json
    # ── Insert Audit Logs for the steps executed ──
    await db.executemany(
        """INSERT INTO audit_log (event_type, agent_name, order_id, action, details) VALUES ($1,$2,$3,$4,$5)""",
        [
            (
                "ORDER_INGESTED", "agent_01_order_ingestion", order_id, "persist_order", 
                json.dumps({"input": {"text": getattr(payload, 'text', 'Form Submission'), "channel": "portal"}, "output": {"sku": payload.sku_id, "qty": payload.quantity, "amount": total}})
            ),
            (
                "CREDIT_SCORED", "agent_02_credit_assessment", order_id, "evaluate_credit", 
                json.dumps({"input": {"credit_limit": float(customer.get("credit_limit_inr", 100000)), "open_ar": if_ctx["open_ar_balance_inr"]}, "output": {"risk_class": credit_result['credit_risk_class'], "pd_score": round(credit_result['pd_score'], 3)}})
            ),
            (
                "FRAUD_SCORED", "agent_03_fraud_detection", order_id, "evaluate_fraud", 
                json.dumps({"input": {"amount": total, "channel": "portal"}, "output": {"fraud_probability": round(fraud_result['fraud_probability']*100, 1), "verdict": fraud_result['fraud_verdict']}})
            ),
            (
                "POLICY_DECISION", "policy_engine", order_id, "evaluate", 
                json.dumps({"input": {"fraud_verdict": fraud_result['fraud_verdict'], "credit_risk": credit_result['credit_risk_class']}, "output": {"action": policy_result['action'].name, "final_status": status}})
            )
        ]
    )

    # — Insert into fraud_records so Fraud Detection page captures portal orders —
    try:
        await db.execute(
            """INSERT INTO fraud_records (fraud_id, order_id, customer_id, isolation_forest_score,
               xgboost_fraud_probability, fraud_verdict, anomaly_flag, shap_explanation, detected_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())""",
            f"FR-{order_id}", order_id, customer["customer_id"],
            if_result["anomaly_score"],
            fraud_result["fraud_probability"],
            fraud_result["fraud_verdict"],
            if_result["anomaly_flag"],
            f"Portal order | IF={if_result['interpretation']} | Fraud={fraud_result['fraud_verdict']}"
        )
    except Exception as e:
        logger.warning(f"fraud_records insert failed (non-critical): {e}")

    # — Insert into credit_decisions for ECOA audit trail (Agent 2) —
    try:
        await db.execute(
            """INSERT INTO credit_decisions
               (decision_id, customer_id, order_id, decision_type, credit_tier,
                credit_limit_inr, pd_score, credit_risk_class, decision, decision_reason,
                model_used, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,NOW())""",
            f"CD-{order_id}",
            customer["customer_id"],
            order_id,
            "order_credit_check",
            customer.get("credit_tier", "B"),
            float(customer.get("credit_limit_inr", 100000)),
            credit_result["pd_score"],
            credit_result["credit_risk_class"],
            "approved" if status == "approved" else "referred",
            f"Portal order | Risk={credit_result['credit_risk_class']} PD={credit_result['pd_score']:.3f}",
            credit_result["model"],
        )
    except Exception as e:
        logger.warning(f"credit_decisions insert failed (non-critical): {e}")

    # ── Agent 5: Auto-generate Invoice if approved ──────────────────────
    payment_token = None
    if status == "approved":
        import random as _random
        invoice_id = f"INV-{order_id.split('-')[1]}"
        due_date = datetime.utcnow() + timedelta(days=30)
        payment_token = f"{_random.randint(0, 999_999_999_999):012d}"
        await db.execute(
            """INSERT INTO invoices (invoice_id, order_id, customer_id, due_date,
               subtotal_inr, total_amount_inr, balance_due_inr, payment_status, payment_token)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8)""",
            invoice_id, order_id, customer["customer_id"], due_date,
            subtotal, total, total, payment_token
        )
        await db.execute(
            """INSERT INTO ar_ledger (ar_id, invoice_id, customer_id, amount_inr,
               outstanding_balance_inr, aging_bucket, payment_status, last_action)
               VALUES ($1, $2, $3, $4, $5, '0-30', 'pending', 'invoice_generated')""",
            f"AR-{invoice_id}", invoice_id, customer["customer_id"], total, total
        )
        await db.execute(
            "INSERT INTO audit_log (event_type, agent_name, order_id, action, details) VALUES ($1,$2,$3,$4,$5)",
            "INVOICE_GENERATED", "agent_05_fulfillment", order_id, "generate_invoice", json.dumps({"output": {"invoice_id": invoice_id, "status": "Auto-generated"}})
        )
        logger.info(f"Agent 5: Auto-generated invoice {invoice_id} with payment token for portal order {order_id}")

    # Send confirmation email — include payment token if invoice generated
    if status == "approved" and payment_token:
        pay_link = f"{settings.frontend_url}/portal/outstanding"
        # Build a structured PDF tax invoice to attach to the email.
        invoice_attachments = None
        try:
            from services.invoice_pdf import build_invoice_pdf_attachment
            invoice_attachments = [build_invoice_pdf_attachment(
                invoice_id=invoice_id,
                order_id=order_id,
                customer_name=customer["company_name"],
                customer_email=customer.get("email", ""),
                customer_gstin=customer.get("gstin", "") or "",
                billing_address=customer.get("address", "") or "",
                line_items=[{
                    "description": product["product_name"],
                    "quantity": payload.quantity,
                    "unit_price_inr": unit_price,
                    "amount_inr": subtotal,
                }],
                subtotal_inr=subtotal,
                gst_pct=gst_pct,
                gst_amount_inr=gst_amount,
                total_inr=total,
                invoice_date=datetime.utcnow(),
                due_date=due_date,
            )]
        except Exception as e:
            logger.warning(f"Invoice PDF generation failed (sending text-only): {e}")

        send_email(
            to=customer["email"],
            subject=f"Invoice Generated — {invoice_id} | MAQ Manufacturing",
            attachments=invoice_attachments,
            body=(
                f"Dear {customer.get('contact_name', customer['company_name'])},\n\n"
                f"Your order has been approved and an invoice has been raised.\n\n"
                f"A detailed tax invoice is attached to this email as a PDF.\n\n"
                f"Order ID       : {order_id}\n"
                f"Invoice ID     : {invoice_id}\n"
                f"Product        : {product['product_name']}\n"
                f"Quantity       : {payload.quantity}\n"
                f"Total (GST)    : ₹{total:,.0f}\n"
                f"Due Date       : {due_date.strftime('%d %b %Y')}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"HOW TO PAY\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Option 1 — Customer Portal (Recommended):\n"
                f"   {pay_link}\n"
                f"   Log in → Outstanding Invoices → click Pay Now\n\n"
                f"Option 2 — NEFT / RTGS via Email:\n"
                f"   Reply to this email with your remittance advice and\n"
                f"   include your Invoice ID: {invoice_id}\n"
                f"   Payments sent from your registered email are auto-processed.\n\n"
                f"Regards,\nMAQ Manufacturing — Finance Team"
            )
        )
    else:
        send_email(
            to=customer["email"],
            subject=f"Order Update — {order_id}",
            body=(
                f"Dear {customer.get('contact_name', customer['company_name'])},\n\n"
                f"Your order status: {status.upper()}\n\n"
                f"Order ID: {order_id}\nProduct: {product['product_name']}\n"
                f"Quantity: {payload.quantity}\nTotal: ₹{total:,.0f}\n\n"
                f"Regards,\nMAQ Manufacturing"
            )
        )

    return {
        "order_id": order_id,
        "status": status,
        "product": product["product_name"],
        "quantity": payload.quantity,
        "total_amount_inr": total,
        "fraud_score": round(fraud_result["fraud_probability"], 3),
        "hitl_required": hitl_required,
        "message": "Order placed and processed through O2C pipeline." if status == "approved"
                   else f"Order placed. Status: {status}. Review required.",
        **_inventory_response_fields(inventory_result),
    }



# ══════════════════════════════════════════════════════════════════════════
# PLACE ORDER — NLP Free Text
# ══════════════════════════════════════════════════════════════════════════

class NLPOrderRequest(BaseModel):
    text: str


@router.post("/orders/nlp/preview")
async def nlp_order_preview(
    payload: NLPOrderRequest,
    customer=Depends(get_current_customer),
):
    """
    Extract order fields from free-text using GLiNER + Ollama Cloud LLM.
    Returns a preview for customer to confirm before submitting.
    """
    from ml.gliner_ner import extract_order_entities_with_llm_backup
    extracted = extract_order_entities_with_llm_backup(payload.text)

    # Clean up metadata fields
    clean = {k: v for k, v in extracted.items() if not k.startswith("_") and isinstance(v, dict)}

    # Try to match SKU by product name
    sku_hint = None
    product_val = (clean.get("product_name") or {}).get("value", "")
    item_code_val = (clean.get("item_code") or {}).get("value", "")

    return {
        "extracted": clean,
        "ner_confidence": extracted.get("_ner_confidence", "MEDIUM"),
        "groq_corrections": extracted.get("_groq_corrections", []),
        "prefilled_form": {
            "sku_hint": item_code_val or product_val,
            "quantity": (clean.get("quantity") or {}).get("value"),
            "delivery_address": (clean.get("shipping_address") or {}).get("value") or customer.get("shipping_address"),
            "requested_delivery_date": (clean.get("delivery_date") or {}).get("value"),
            "po_reference": (clean.get("order_reference") or {}).get("value"),
        },
        "message": "Review the extracted details below and confirm to place the order."
    }


# ══════════════════════════════════════════════════════════════════════════
# REPEAT / EDIT AND REPEAT ORDER
# ══════════════════════════════════════════════════════════════════════════

class RepeatOrderRequest(BaseModel):
    quantity: Optional[int] = None               # Override quantity (else use original)
    delivery_address: Optional[str] = None
    requested_delivery_date: Optional[str] = None
    po_reference: Optional[str] = None


@router.post("/orders/{order_id}/repeat")
async def repeat_order(
    order_id: str,
    payload: RepeatOrderRequest,
    customer=Depends(get_current_customer),
    db=Depends(get_db)
):
    """Repeat a past order with optional modifications."""
    original = await db.fetchrow(
        "SELECT * FROM orders WHERE order_id = $1 AND customer_id = $2",
        order_id, customer["customer_id"]
    )
    if not original:
        raise HTTPException(404, "Original order not found")

    original = dict(original)

    # Get latest price (may have changed)
    product = await db.fetchrow(
        "SELECT * FROM products WHERE sku_id = $1", original["sku_id"]
    )
    if not product:
        raise HTTPException(404, "Product no longer available")

    product = dict(product)
    qty = payload.quantity or original["quantity"]
    unit_price = float(product["base_price_inr"])
    subtotal = unit_price * qty
    gst_pct = float(product.get("gst_rate_pct", 18))
    gst_amount = subtotal * gst_pct / 100
    total = subtotal + gst_amount

    new_order_id = f"ORD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-R"

    # Parse delivery date safely
    parsed_date = None
    if payload.requested_delivery_date:
        try:
            parsed_date = datetime.fromisoformat(payload.requested_delivery_date.replace('Z', '+00:00'))
        except ValueError:
            pass

    async with db.transaction():
        await db.execute(
            """INSERT INTO orders
               (order_id, customer_id, sku_id, quantity, unit_price_inr, subtotal_inr,
                gst_pct, gst_amount_inr, total_amount_inr, delivery_address,
                requested_delivery_date, po_reference, channel, status, agent_notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'portal','pending_inventory',$13)""",
            new_order_id, customer["customer_id"], original["sku_id"], qty,
            unit_price, subtotal, gst_pct, gst_amount, total,
            payload.delivery_address or original.get("delivery_address", ""),
            parsed_date,
            payload.po_reference or original.get("po_reference", ""),
            f"Repeat of {order_id}",
)

        inventory_result = await reserve_inventory_for_order(
            db, new_order_id, original["sku_id"], qty, customer["customer_id"],
            performed_by=customer.get("email") or customer["customer_id"],
            actor_type="customer",
            # Repeat orders are authenticated customer actions for previously accepted SKUs.
            # They skip full fraud/credit recomputation here, so fully reserved repeats can proceed.
            current_status="approved",
        )
        status = inventory_result["final_status"]
        await db.execute(
            "UPDATE orders SET status=$1, hitl_required=$2, updated_at=NOW() WHERE order_id=$3",
            status, inventory_result["hitl_required"], new_order_id,
        )

    return {
        "order_id": new_order_id,
        "original_order_id": order_id,
        "status": status,
        "quantity": qty,
        "unit_price_inr": unit_price,
        "total_amount_inr": total,
        "message": f"Order repeated successfully from {order_id}.",
        **_inventory_response_fields(inventory_result),
    }


# ══════════════════════════════════════════════════════════════════════════
# PRODUCTS LIST (for portal order form dropdown)
# ══════════════════════════════════════════════════════════════════════════

@router.get("/products")
async def list_products(customer=Depends(get_current_customer), db=Depends(get_db)):
    """List available products for the portal order form."""
    rows = await db.fetch(
        """SELECT sku_id, product_name, base_price_inr, unit_of_measure, category, available_stock
           FROM product_stock_summary
           WHERE is_active = TRUE
           ORDER BY product_name"""
    )
    return {"products": [dict(r) for r in rows]}
