"""
O2C Agent v2.0 — Orders API + Agent 1 (Order Ingestion)
Handles order submission, GLiNER NER extraction, validation, and pipeline triggering.
"""

import logging
import json
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from pydantic import BaseModel, Field
import asyncpg

from database.postgres import get_db
from database.chromadb_client import get_customers_collection
from services.inventory_service import (
    check_and_reserve,
    fulfill_reservation,
    release_reservation,
    FULLY_RESERVED,
    PARTIALLY_RESERVED,
    FULL_BACKORDER,
)
from ml.gliner_ner import extract_order_entities_with_llm_backup
from ml.embeddings import embed_text, compute_similarity
from ml.model_placeholders import predict_fraud, predict_credit_risk
from ml.isolation_forest import score_order
from policy.policy_engine import policy_engine, PolicyAction
from api.staff_deps import require_role

router = APIRouter()
logger = logging.getLogger(__name__)

ORDER_READ_ROLES = ["admin", "dispute_manager", "controller", "inventory_manager"]
ORDER_WRITE_ROLES = ["admin", "controller"]
ORDER_INVENTORY_ACTION_ROLES = ["admin", "controller", "inventory_manager"]


# ── Pydantic Models ──────────────────────────────────────────────────────

class OrderCreate(BaseModel):
    customer_id: Optional[str] = None
    sku_id: str
    quantity: int = Field(gt=0)
    unit_price_inr: Optional[float] = None
    delivery_address: Optional[str] = None
    requested_delivery_date: Optional[str] = None
    po_reference: Optional[str] = None
    channel: str = "api"
    raw_email_text: Optional[str] = None  # For Agent 1 NER parsing


class OrderEmailIngest(BaseModel):
    email_text: str
    email_from: Optional[str] = None
    subject: Optional[str] = None


class FulfillOrderRequest(BaseModel):
    quantity_to_fulfill: Optional[int] = Field(default=None, gt=0)
    idempotency_key: Optional[str] = None


class OrderResponse(BaseModel):
    order_id: str
    status: str
    message: str
    fraud_score: Optional[float] = None
    credit_risk: Optional[str] = None
    hitl_required: bool = False
    pipeline_events: List[str] = []
    inventory_verdict: Optional[str] = None
    quantity_reserved: Optional[int] = None
    quantity_backordered: Optional[int] = None
    reservation_id: Optional[str] = None
    expected_availability_date: Optional[str] = None
    eta_reliability: Optional[str] = None
    inventory_warning: Optional[str] = None


def _inventory_status(inventory_verdict: str, policy_action, current_status: str) -> str:
    if policy_action in (PolicyAction.REQUIRE_HITL, PolicyAction.BLOCK):
        return "hitl_required"
    if inventory_verdict == FULLY_RESERVED:
        return current_status
    if inventory_verdict == PARTIALLY_RESERVED:
        return "partially_reserved"
    if inventory_verdict == FULL_BACKORDER:
        return "backordered"
    return current_status


def _fraud_record_id(order_id: str) -> str:
    order_suffix = order_id[4:] if order_id.startswith("ORD-") else order_id
    return f"FR-{order_suffix}"[:20]


async def reserve_inventory_for_order(
    db,
    order_id: str,
    sku_id: str,
    quantity: int,
    customer_id: Optional[str],
    performed_by: str,
    actor_type: str,
    current_status: str = "approved",
) -> dict:
    """Shared inventory reservation path for every order creation channel."""
    reservation = await check_and_reserve(
        db,
        sku_id=sku_id,
        quantity_requested=quantity,
        order_id=order_id,
        performed_by=performed_by,
        actor_type=actor_type,
    )
    policy_result = await policy_engine.evaluate(
        agent_name="inventory_phase_3",
        tool_name="inventory_check",
        tool_args={"sku_id": sku_id, "quantity": quantity},
        context={
            "inventory_verdict": reservation["verdict"],
            "eta_reliability": reservation.get("eta_reliability"),
            "order_id": order_id,
            "sku_id": sku_id,
            "customer_id": customer_id or "",
        },
    )
    final_status = _inventory_status(reservation["verdict"], policy_result["action"], current_status)
    result = {
        "inventory_verdict": reservation["verdict"],
        "quantity_reserved": reservation["quantity_reserved"],
        "quantity_backordered": reservation["quantity_backordered"],
        "reservation_id": reservation["reservation_id"],
        "expected_availability_date": reservation["expected_availability_date"],
        "eta_reliability": reservation["eta_reliability"],
        "inventory_warning": reservation.get("warning"),
        "policy_action": policy_result["action"],
        "policy_flags": policy_result.get("flags", []),
        "hitl_reason": policy_result.get("hitl_reason", ""),
        "final_status": final_status,
        "hitl_required": final_status == "hitl_required",
    }
    if result["hitl_required"]:
        await db.execute(
            """INSERT INTO audit_log
               (event_type, agent_name, customer_id, order_id, action, details,
                policy_rule_id, outcome)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8)""",
            "INVENTORY_HITL",
            "inventory_phase_3",
            customer_id,
            order_id,
            "inventory_check",
            json.dumps(result, default=str),
            "RULE-008_FULL_BACKORDER",
            "hitl_required",
        )
    return result


def _inventory_response_fields(inventory_result: Optional[dict]) -> dict:
    if not inventory_result:
        return {}
    return {
        "inventory_verdict": inventory_result.get("inventory_verdict"),
        "quantity_reserved": inventory_result.get("quantity_reserved"),
        "quantity_backordered": inventory_result.get("quantity_backordered"),
        "reservation_id": inventory_result.get("reservation_id"),
        "expected_availability_date": inventory_result.get("expected_availability_date"),
        "eta_reliability": inventory_result.get("eta_reliability"),
        "inventory_warning": inventory_result.get("inventory_warning"),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("")
async def list_orders(
    status: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db=Depends(get_db),
    staff=Depends(require_role(ORDER_READ_ROLES)),
):
    """List orders with optional filters."""
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    if status:
        params.append(status)
        query += f" AND status = ${len(params)}"
    if customer_id:
        params.append(customer_id)
        query += f" AND customer_id = ${len(params)}"
    params.extend([limit, offset])
    query += f" ORDER BY created_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}"
    rows = await db.fetch(query, *params)
    return {"orders": [dict(r) for r in rows], "total": len(rows)}


@router.get("/{order_id}")
async def get_order(order_id: str, db=Depends(get_db), staff=Depends(require_role(ORDER_READ_ROLES))):
    """Get a single order by ID, including optional reservation details."""
    row = await db.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)
    if not row:
        raise HTTPException(404, f"Order {order_id} not found")
    result = dict(row)
    reservation = await db.fetchrow(
        "SELECT reservation_id, sku_id, quantity_requested, quantity_reserved, "
        "quantity_backordered, status, expected_availability_date, reserved_at, "
        "released_at, fulfilled_at FROM inventory_reservations WHERE order_id = $1 "
        "ORDER BY reserved_at DESC LIMIT 1",
        order_id,
    )
    result["reservation"] = dict(reservation) if reservation else None
    return result


@router.post("/ingest-email", response_model=OrderResponse)
async def ingest_order_email(
    payload: OrderEmailIngest,
    background: BackgroundTasks,
    db=Depends(get_db),
    staff=Depends(require_role(ORDER_WRITE_ROLES)),
):
    """
    Agent 1 — Order Ingestion from Email.
    1. GLiNER zero-shot NER extracts entities
    2. Customer deduplication via ChromaDB semantic search
    3. Pydantic validation
    4. Risk assessment (Isolation Forest + XGBoost)
    5. Policy Engine evaluation
    6. Persist to PostgreSQL + emit to MAF bus
    """
    events = []
    
    # Step 1: GLiNER + Groq NER pipeline
    # GLiNER extracts locally first, then Groq evaluates, corrects, and fills gaps
    entities = extract_order_entities_with_llm_backup(payload.email_text)
    corrections = entities.get("_groq_corrections", [])
    ner_confidence = entities.get("_ner_confidence", "MEDIUM")
    ner_sources = {k: v.get("source", "gliner") for k, v in entities.items() if isinstance(v, dict) and "source" in v}
    events.append(f"NER pipeline: {len(entities)} entities, confidence={ner_confidence}, Groq corrections={len(corrections)}")
    logger.info(f"Agent 1 NER result: {entities}")
    logger.info(f"NER sources: {ner_sources}")
    
    # Step 2: Customer lookup — email-first with hard-stop on unregistered senders
    #
    # SECURITY: When an email_from is present, it is the ONLY trusted identity signal.
    # Company name and other entities are extracted from the email BODY — attacker-controlled text.
    # Falling through to ChromaDB/ILIKE after an email miss would allow anyone to impersonate a
    # registered customer by simply writing "We are Satya Manufacturing Pvt Ltd" in their email.
    #
    # Rule:
    #   - email_from present & found in DB  → proceed (Priority 0, authenticated)
    #   - email_from present & NOT in DB    → STOP, KYC/registration invite (unregistered sender)
    #   - email_from absent (API/portal)    → fall through to name-based matching (no email to check)
    customer_id = None
    email_from_is_unregistered = False  # gate flag — True means hard-stop, skip name matching
    # company_text is strictly the NER-extracted company name — never the email address.
    company_text = entities.get("customer_name", {}).get("value", "")

    # Priority 0 — exact SQL lookup on registered sender email (instant, 100% accurate)
    if payload.email_from:
        row = await db.fetchrow(
            "SELECT customer_id FROM customers WHERE LOWER(email) = $1 LIMIT 1",
            payload.email_from.lower().strip()
        )
        if row:
            customer_id = row["customer_id"]
            events.append(f"Customer matched via sender email: {customer_id}")
        else:
            # Email present but NOT registered — flag for hard-stop below.
            # Do NOT fall through to company-name matching; that data is attacker-controlled.
            email_from_is_unregistered = True
            events.append(f"Sender email {payload.email_from} not registered — routing to KYC")
            logger.warning(
                f"Order from unregistered email {payload.email_from} — "
                f"skipping name-based matching to prevent impersonation"
            )

    # Priority 1 & 2 — name-based fallbacks (ChromaDB + ILIKE).
    # ONLY reached when there is no sender email at all (API / portal orders).
    # When email_from is present but unregistered, we skip this entirely.
    if not customer_id and not email_from_is_unregistered and company_text:
        # Priority 1 — ChromaDB cosine similarity on extracted company name
        try:
            col = get_customers_collection()
            emb = embed_text(company_text)
            results = col.query(query_embeddings=[emb], n_results=1, include=["metadatas", "distances"])
            if results["distances"][0] and results["distances"][0][0] < 0.3:
                customer_id = results["metadatas"][0][0].get("customer_id")
                events.append(f"Customer matched via vector search: {customer_id}")
        except Exception:
            pass

        # Priority 2 — fuzzy ILIKE match against DB company_name
        if not customer_id:
            row = await db.fetchrow(
                "SELECT customer_id FROM customers WHERE LOWER(company_name) LIKE $1 LIMIT 1",
                f"%{company_text.lower()[:20]}%"
            )
            if row:
                customer_id = row["customer_id"]
                events.append(f"Customer matched via DB name lookup: {customer_id}")

    if not customer_id:
        # ── Unregistered / anonymous sender: hold order and send KYC/registration invite ──
        if payload.email_from:
            import secrets
            from config import settings as app_settings
            token = secrets.token_urlsafe(32)
            try:
                await db.execute(
                    """INSERT INTO pending_order_emails
                       (invite_token, email_from, subject, email_text, status)
                       VALUES ($1, $2, $3, $4, 'awaiting_registration')
                       ON CONFLICT (invite_token) DO NOTHING""",
                    token, payload.email_from,
                    payload.subject or "", payload.email_text
                )
            except Exception as e:
                logger.warning(f"Could not store pending order: {e}")

            register_url = (
                f"{app_settings.frontend_url}/portal/register"
                f"?invite={token}&email={payload.email_from}"
            )
            from api.customer_portal import send_email
            sent, smtp_err = send_email(
                to=payload.email_from,
                subject="Complete Registration to Process Your Order — MAQ Manufacturing",
                body=(
                    f"Dear Customer,\n\n"
                    f"Thank you for your order request. We received your email but your address "
                    f"is not yet registered in our system.\n\n"
                    f"To process your order, please complete a quick registration using the link below:\n\n"
                    f"   {register_url}\n\n"
                    f"Once you register, your order will be processed automatically.\n\n"
                    f"This link is valid for 7 days.\n\n"
                    f"Regards,\nMAQ Manufacturing — Order Team"
                )
            )
            if sent:
                events.append(f"KYC registration invite sent to {payload.email_from} ✅")
            else:
                events.append(f"KYC invite SMTP FAILED for {payload.email_from}: {smtp_err}")
            logger.info(f"Registration invite sent={sent} to {payload.email_from}, token={token[:8]}...")

        return OrderResponse(
            order_id="PENDING-REG",
            status="awaiting_registration",
            message=f"Sender {payload.email_from or 'unknown'} is not registered. Registration invite emailed — order will auto-process after signup.",
            fraud_score=0.0,
            credit_risk="UNKNOWN",
            hitl_required=False,
            pipeline_events=events,
        )
    
    # Step 3: Build order dict from NER + fallbacks
    raw_sku = (
        entities.get("item_code", {}).get("value", "") or
        entities.get("product_name", {}).get("value", "") or
        entities.get("product", {}).get("value", "")
    )
    # Try to resolve extracted text to a real SKU via ILIKE on products table
    sku_row = None
    if raw_sku:
        sku_row = await db.fetchrow(
            "SELECT sku_id, base_price_inr AS unit_price_inr FROM products WHERE LOWER(sku_id) = $1 OR LOWER(product_name) LIKE $2 LIMIT 1",
            raw_sku.lower(), f"%{raw_sku.lower()[:15]}%"
        )
    if not sku_row:
        # Default to first available SKU
        sku_row = await db.fetchrow("SELECT sku_id, base_price_inr AS unit_price_inr FROM products LIMIT 1")
    sku_id = sku_row["sku_id"] if sku_row else "SKU-001"
    unit_price = float(sku_row["unit_price_inr"]) if sku_row else 1000.0

    qty_str = entities.get("quantity", {}).get("value", "1")
    try:
        qty = int(''.join(filter(str.isdigit, qty_str))) or 1
    except Exception:
        qty = 1

    subtotal = unit_price * qty
    gst_rate = 0.18
    total_amt = subtotal * (1 + gst_rate)

    # Load customer context for risk models
    customer = None
    if customer_id:
        customer = await db.fetchrow("SELECT * FROM customers WHERE customer_id = $1", customer_id)

    # Step 4: Isolation Forest anomaly score
    order_ctx = {
        "total_amount_inr": total_amt,
        "quantity": qty,
        "unit_price_inr": unit_price,
        "avg_dso_days": float(customer["avg_dso_days"]) if customer else 30,
        "missed_payments_12m": int(customer["missed_payments_12m"]) if customer else 0,
        "open_ar_balance_inr": float(customer["open_ar_balance_inr"]) if customer else 0,
        "account_age_months": int(customer["account_age_months"]) if customer else 12,
        "channel": "email",
    }
    if_result = score_order(order_ctx)
    events.append(f"Isolation Forest score: {if_result['anomaly_score']:.3f} ({if_result['interpretation']})")

    # Step 5: Fraud probability (XGBoost — real model if trained)
    fraud_result = predict_fraud({
        "amount_inr": total_amt,
        "customer_age_months": int(customer["account_age_months"]) if customer else 12,
        "avg_days_late": float(customer["avg_dso_days"] or 30) - 30 if customer else 0,
        "missed_payments": int(customer["missed_payments_12m"]) if customer else 0,
        "open_ar_ratio": float(customer["open_ar_balance_inr"] or 0) / max(float(customer["credit_limit_inr"] or 100000), 1) if customer else 0.0,
        "is_new_customer": customer_id is None,
        "hour_of_day": datetime.now().hour,
        "channel": "email",
    })
    events.append(f"Fraud probability: {fraud_result['fraud_probability']:.3f} — {fraud_result['fraud_verdict']}")

    # Step 6: Credit check using model
    credit_result = predict_credit_risk({
        "order_value_inr": total_amt,
        "credit_limit_inr": float(customer["credit_limit_inr"]) if customer else 100000,
        "open_ar_balance_inr": float(customer["open_ar_balance_inr"]) if customer else 0,
        "avg_days_late": float(customer["avg_dso_days"] or 30) - 30 if customer else 0,
        "missed_payment_count": int(customer["missed_payments_12m"]) if customer else 0,
        "account_age_months": int(customer["account_age_months"]) if customer else 12,
        "credit_tier": customer["credit_tier"] if customer else "C",
    })
    events.append(f"Credit risk: {credit_result['credit_risk_class']} (PD={credit_result['pd_score']:.3f})")

    # Step 7: Policy Engine evaluation
    policy_result = await policy_engine.evaluate(
        agent_name="agent_01_order_ingestion",
        tool_name="persist_order",
        tool_args={"sku_id": sku_id, "quantity": qty},
        context={
            "fraud_probability": fraud_result["fraud_probability"],
            "order_amount_inr": total_amt,
            "credit_limit_inr": float(customer["credit_limit_inr"]) if customer else 100000,
            "open_ar_balance_inr": float(customer["open_ar_balance_inr"]) if customer else 0,
            "customer_id": customer_id or "",
            "order_id": "",
        }
    )
    events.append(f"Policy Engine: {policy_result['action']} flags={policy_result['flags']}")

    # Step 8: Generate order ID and persist
    order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-E"
    hitl_required = policy_result["action"] in (PolicyAction.REQUIRE_HITL, PolicyAction.BLOCK)
    status = "fraud_review" if fraud_result["fraud_verdict"] == "FRAUD" else (
        "hitl_required" if hitl_required else "approved"
    )
    inventory_result = None

    try:
        async with db.transaction():
            await db.execute(
            """INSERT INTO orders (order_id, customer_id, sku_id, quantity, unit_price_inr,
               subtotal_inr, gst_pct, gst_amount_inr, total_amount_inr, channel, status,
               fraud_score, isolation_forest_score, hitl_required)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
            order_id, customer_id, sku_id, qty, unit_price,
            subtotal, gst_rate * 100, subtotal * gst_rate, total_amt,
            "email", "pending_inventory",
            fraud_result["fraud_probability"], if_result["anomaly_score"], hitl_required
            )
            events.append(f"Order persisted to PostgreSQL: {order_id}")

            # Insert into fraud_records for Agent 3 / Fraud Detection page
            await db.execute(
            """INSERT INTO fraud_records (fraud_id, order_id, customer_id, isolation_forest_score,
               xgboost_fraud_probability, fraud_verdict, anomaly_flag, shap_explanation, detected_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())""",
            _fraud_record_id(order_id), order_id, customer_id,
            if_result["anomaly_score"],
            fraud_result["fraud_probability"],
            fraud_result["fraud_verdict"],
            if_result["anomaly_flag"],
            f"IF={if_result['interpretation']} | Fraud={fraud_result['fraud_verdict']}"
            )

            inventory_result = await reserve_inventory_for_order(
                db, order_id, sku_id, qty, customer_id,
                performed_by=staff["username"], actor_type="human",
                current_status=status,
            )
            status = inventory_result["final_status"]
            hitl_required = hitl_required or inventory_result["hitl_required"]
            await db.execute(
                "UPDATE orders SET status=$1, hitl_required=$2, updated_at=NOW() WHERE order_id=$3",
                status, hitl_required, order_id,
            )
            events.append(
                f"Inventory: {inventory_result['inventory_verdict']} "
                f"reserved={inventory_result['quantity_reserved']} backordered={inventory_result['quantity_backordered']}"
            )

            if status == "approved":
                from datetime import timedelta
                import random as _random
                invoice_id = f"INV-{order_id.split('-')[1]}-{order_id.split('-')[2]}"
                due_date = datetime.now() + timedelta(days=30)
                # Generate a unique 12-digit payment authorization token
                payment_token = f"{_random.randint(0, 999_999_999_999):012d}"

                await db.execute(
                """INSERT INTO invoices (invoice_id, order_id, customer_id, due_date, subtotal_inr,
                   total_amount_inr, balance_due_inr, payment_status, payment_token)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                invoice_id, order_id, customer_id, due_date,
                subtotal, total_amt, total_amt, "pending", payment_token
                )
                await db.execute(
                """INSERT INTO ar_ledger (ar_id, invoice_id, customer_id, amount_inr, outstanding_balance_inr, aging_bucket, payment_status, last_action)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                f"AR-{invoice_id}", invoice_id, customer_id, total_amt, total_amt,
                "0-30", "pending", "invoice_generated"
                )
                events.append(f"Agent 6: Auto-generated invoice {invoice_id} with payment token")

    except Exception as e:
        logger.error(f"DB persist failed: {e}")
        raise HTTPException(500, f"Order ingestion failed: {e}")

    # ── Send confirmation email back to the customer ───────────────────────
    if customer and customer.get("email"):
        from api.customer_portal import send_email
        from config import settings as app_settings
        if status == "approved":
            # Include the payment token and a direct payment link in the invoice email
            pay_link = f"{app_settings.frontend_url}/portal/outstanding"
            send_email(
                to=customer["email"],
                subject=f"Invoice Generated — {invoice_id} | MAQ Manufacturing",
                body=(
                    f"Dear {customer.get('contact_name') or customer.get('company_name')},\n\n"
                    f"Thank you for your order. Your order has been approved and an invoice has been raised.\n\n"
                    f"Order ID       : {order_id}\n"
                    f"Invoice ID     : {invoice_id}\n"
                    f"Product        : {sku_id}\n"
                    f"Quantity       : {qty}\n"
                    f"Total (GST)    : ₹{total_amt:,.0f}\n"
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
            status_desc = {
                "hitl_required": "received and flagged for Finance Controller review",
                "fraud_review": "received and placed under security review",
            }.get(status, f"processed (status: {status})")
            send_email(
                to=customer["email"],
                subject=f"Order Received — {order_id}",
                body=(
                    f"Dear {customer.get('contact_name') or customer.get('company_name')},\n\n"
                    f"Your order has been {status_desc}.\n\n"
                    f"Order ID : {order_id}\n"
                    f"Product  : {sku_id}\n"
                    f"Quantity : {qty}\n"
                    f"Total    : ₹{total_amt:,.0f}\n\n"
                    f"Our team will be in touch if any additional information is required.\n\n"
                    f"Regards,\nMAQ Manufacturing — Order Team"
                )
            )
        events.append(f"Confirmation email sent to {customer['email']}")

    return OrderResponse(
        order_id=order_id,
        status=status,
        message=f"Order ingested via GLiNER NER. SKU: {sku_id} @ ₹{unit_price:,.0f}. Customer: {customer_id or 'unmatched'}",
        fraud_score=fraud_result["fraud_probability"],
        credit_risk=credit_result["credit_risk_class"],
        hitl_required=hitl_required,
        pipeline_events=events,
        **_inventory_response_fields(inventory_result),
    )


@router.post("", response_model=OrderResponse)
async def create_order(
    order: OrderCreate,
    background: BackgroundTasks,
    db=Depends(get_db),
    staff=Depends(require_role(ORDER_WRITE_ROLES)),
):
    """Create a new order via API (structured payload)."""
    events = []
    order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Get customer info for context
    customer = await db.fetchrow("SELECT * FROM customers WHERE customer_id = $1", order.customer_id) if order.customer_id else None
    
    # Isolation Forest
    if_ctx = {
        "total_amount_inr": (order.unit_price_inr or 1000) * order.quantity,
        "quantity": order.quantity,
        "unit_price_inr": order.unit_price_inr or 1000,
        "avg_dso_days": customer["avg_dso_days"] if customer else 30,
        "missed_payments_12m": customer["missed_payments_12m"] if customer else 0,
        "open_ar_balance_inr": float(customer["open_ar_balance_inr"]) if customer else 0,
        "account_age_months": customer["account_age_months"] if customer else 12,
        "channel": order.channel,
    }
    if_result = score_order(if_ctx)
    
    # Fraud check — pass full customer features to real XGBoost model
    fraud_result = predict_fraud({
        "amount_inr": if_ctx["total_amount_inr"],
        "customer_age_months": int(customer["account_age_months"]) if customer else 12,
        "avg_days_late": float(customer["avg_dso_days"] or 30) - 30 if customer else 0,
        "missed_payments": if_ctx["missed_payments_12m"],
        "open_ar_ratio": if_ctx["open_ar_balance_inr"] / max(float(customer["credit_limit_inr"]) if customer else 100000, 1),
        "is_new_customer": customer is None,
        "hour_of_day": datetime.now().hour,
        "channel": order.channel,
    })
    events.append(f"Fraud: {fraud_result['fraud_probability']:.3f} — {fraud_result['fraud_verdict']}")
    
    # Policy Engine
    policy_result = await policy_engine.evaluate(
        agent_name="agent_01_order_ingestion",
        tool_name="persist_order",
        tool_args={"sku_id": order.sku_id, "quantity": order.quantity},
        context={
            "fraud_probability": fraud_result["fraud_probability"],
            "order_amount_inr": if_ctx["total_amount_inr"],
            "credit_limit_inr": float(customer["credit_limit_inr"]) if customer else 100000,
            "open_ar_balance_inr": if_ctx["open_ar_balance_inr"],
            "customer_id": order.customer_id,
        }
    )
    
    hitl_required = policy_result["action"] in (PolicyAction.REQUIRE_HITL, PolicyAction.BLOCK)
    status = "fraud_review" if fraud_result["fraud_verdict"] == "FRAUD" else (
        "hitl_required" if hitl_required else "approved"
    )
    subtotal = (order.unit_price_inr or 1000) * order.quantity
    gst_rate = 0.18
    inventory_result = None
    
    try:
        total_amt = subtotal * (1 + gst_rate)
        async with db.transaction():
            await db.execute(
            """INSERT INTO orders (order_id, customer_id, sku_id, quantity, unit_price_inr,
               subtotal_inr, gst_pct, gst_amount_inr, total_amount_inr, channel, po_reference,
               delivery_address, status, fraud_score, isolation_forest_score, hitl_required)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
            order_id, order.customer_id, order.sku_id, order.quantity,
            order.unit_price_inr or 1000, subtotal, gst_rate * 100,
            subtotal * gst_rate, total_amt,
            order.channel, order.po_reference or "",
            order.delivery_address or "", "pending_inventory",
            fraud_result["fraud_probability"], if_result["anomaly_score"], hitl_required
            )
            # Insert into fraud_records so Fraud Detection page shows real data
            await db.execute(
            """INSERT INTO fraud_records (fraud_id, order_id, customer_id, isolation_forest_score,
               xgboost_fraud_probability, fraud_verdict, anomaly_flag, shap_explanation, detected_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())""",
            _fraud_record_id(order_id), order_id, order.customer_id,
            if_result["anomaly_score"], fraud_result["fraud_probability"],
            fraud_result["fraud_verdict"], if_result["anomaly_flag"],
            f"IF={if_result['interpretation']} | Channel={order.channel}"
            )

            inventory_result = await reserve_inventory_for_order(
                db, order_id, order.sku_id, order.quantity, order.customer_id,
                performed_by=staff["username"], actor_type="human",
                current_status=status,
            )
            status = inventory_result["final_status"]
            hitl_required = hitl_required or inventory_result["hitl_required"]
            await db.execute(
                "UPDATE orders SET status=$1, hitl_required=$2, updated_at=NOW() WHERE order_id=$3",
                status, hitl_required, order_id,
            )
            events.append(
                f"Inventory: {inventory_result['inventory_verdict']} "
                f"reserved={inventory_result['quantity_reserved']} backordered={inventory_result['quantity_backordered']}"
            )
        
            if status == "approved":
                from datetime import timedelta
                invoice_id = f"INV-{order_id.split('-')[-1]}"
                due_date = datetime.now() + timedelta(days=30)
            
                await db.execute(
                """INSERT INTO invoices (invoice_id, order_id, customer_id, due_date, subtotal_inr, total_amount_inr, balance_due_inr, payment_status)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                invoice_id, order_id, order.customer_id, due_date,
                subtotal, total_amt, total_amt, "pending"
                )
                await db.execute(
                """INSERT INTO ar_ledger (ar_id, invoice_id, customer_id, amount_inr, outstanding_balance_inr, aging_bucket, payment_status, last_action)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                f"AR-{invoice_id}", invoice_id, order.customer_id, total_amt, total_amt,
                "0-30", "pending", "invoice_generated"
                )

                events.append(f"Agent 5 Auto-generated invoice: {invoice_id}")
            
    except Exception as e:
        raise HTTPException(500, f"Order creation failed: {e}")
    
    return OrderResponse(
        order_id=order_id,
        status=status,
        message="Order created and submitted to O2C pipeline",
        fraud_score=fraud_result["fraud_probability"],
        credit_risk=None,
        hitl_required=hitl_required,
        pipeline_events=events,
        **_inventory_response_fields(inventory_result),
    )


BLOCKED_STATUSES = {"fulfilled", "cancelled"}

@router.patch("/{order_id}/status")
async def update_order_status(
    order_id: str,
    status: str,
    db=Depends(get_db),
    staff=Depends(require_role(ORDER_WRITE_ROLES)),
):
    """Update order status (used by agents during pipeline execution).
    
    Blocked statuses that must use dedicated endpoints:
      - 'fulfilled'  → POST /{order_id}/fulfill
      - 'cancelled'  → POST /{order_id}/cancel
    """
    if status.lower() in BLOCKED_STATUSES:
        if status.lower() == "fulfilled":
            raise HTTPException(
                400,
                f"Setting status to 'fulfilled' is blocked — use POST /api/orders/{order_id}/fulfill instead",
            )
        if status.lower() == "cancelled":
            raise HTTPException(
                400,
                f"Setting status to 'cancelled' is blocked — use POST /api/orders/{order_id}/cancel instead",
            )
    row = await db.fetchrow("SELECT order_id FROM orders WHERE order_id = $1", order_id)
    if not row:
        raise HTTPException(404, f"Order {order_id} not found")
    await db.execute(
        "UPDATE orders SET status = $1, updated_at = NOW() WHERE order_id = $2",
        status, order_id
    )
    return {"order_id": order_id, "status": status, "updated": True}


@router.post("/{order_id}/fulfill")
async def fulfill_order(
    order_id: str,
    payload: FulfillOrderRequest,
    db=Depends(get_db),
    staff=Depends(require_role(ORDER_INVENTORY_ACTION_ROLES)),
):
    """Fulfill reserved inventory for an order."""
    try:
        result = await fulfill_reservation(
            db,
            order_id=order_id,
            quantity_to_fulfill=payload.quantity_to_fulfill,
            performed_by=staff["username"],
            actor_type="human",
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"order_id": order_id, **result}


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    db=Depends(get_db),
    staff=Depends(require_role(ORDER_INVENTORY_ACTION_ROLES)),
):
    """Cancel an order and release any active reservation without touching stock_on_hand.

    Verifies the order exists (with row lock) *before* releasing inventory,
    and both operations happen inside the same transaction so a rollback on
    error never leaves stock in an inconsistent state.
    """
    async with db.transaction():
        order = await db.fetchrow(
            "SELECT order_id, status FROM orders WHERE order_id = $1 FOR UPDATE",
            order_id,
        )
        if not order:
            raise HTTPException(404, f"Order {order_id} not found")
        if order["status"] == "cancelled":
            return {"order_id": order_id, "status": "cancelled", "message": "Already cancelled"}

        active_reservation = await db.fetchrow(
            "SELECT reservation_id FROM inventory_reservations "
            "WHERE order_id = $1 AND status = 'active' LIMIT 1",
            order_id,
        )
        result = {"released": False, "quantity_released": 0, "reservation_id": None, "warning": "no_active_reservation"}
        if active_reservation:
            result = await release_reservation(
                db,
                order_id=order_id,
                performed_by=staff["username"],
                actor_type="human",
            )

        await db.execute(
            "UPDATE orders SET status='cancelled', updated_at=NOW() WHERE order_id=$1",
            order_id,
        )

    return {"order_id": order_id, "status": "cancelled", **result}


@router.get("/stats/summary")
async def orders_summary(db=Depends(get_db), staff=Depends(require_role(ORDER_READ_ROLES))):
    """Dashboard summary stats for orders including channel breakdown."""
    total = await db.fetchval("SELECT COUNT(*) FROM orders")
    pending = await db.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'pending_credit'")
    fraud_review = await db.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'fraud_review'")
    hitl = await db.fetchval("SELECT COUNT(*) FROM orders WHERE hitl_required = TRUE")
    total_value = await db.fetchval("SELECT COALESCE(SUM(total_amount_inr),0) FROM orders") or 0
    # Channel breakdown for pie chart
    channel_rows = await db.fetch(
        "SELECT channel, COUNT(*) as cnt FROM orders GROUP BY channel ORDER BY cnt DESC"
    )
    total_count = int(total) or 1
    by_channel = {r['channel']: round(int(r['cnt']) / total_count * 100, 1) for r in channel_rows}
    return {
        "total_orders": total,
        "pending_credit": pending,
        "fraud_review": fraud_review,
        "hitl_required": hitl,
        "total_value_inr": float(total_value),
        "by_channel": by_channel,
    }
