"""Admin-facing APIs for customer portal disputes.

These routes are separate from the existing /api/disputes email-ingestion demo so
that the current implementation remains stable.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.staff_deps import get_current_staff, require_admin
from database.postgres import get_db
from ml.llm_client import call_llm
from services.email_service import send_optional_email
from services.inventory_service import RETURN_RECEIPT, record_adjustment

router = APIRouter()
logger = logging.getLogger(__name__)

FINAL_STATUSES = {"resolved", "rejected", "closed", "withdrawn"}


class AdminMessagePayload(BaseModel):
    message: str


class DecisionPayload(BaseModel):
    status: str
    decision_note: str = ""
    customer_message: str = ""
    credit_amount_inr: float = 0.0  # Amount to credit on the invoice (0 = no credit / rejection)
    return_quantity: int = 0  # Saleable returned units to add back to stock
    return_sku_id: Optional[str] = None  # Required when the dispute is not linked to an order/invoice


def is_return_resolution(dispute, decision_note: str, customer_message: str) -> bool:
    dispute_data = dict(dispute)
    text = " ".join([
        str(dispute_data.get("dispute_type") or ""),
        str(dispute_data.get("subject") or ""),
        str(dispute_data.get("ai_summary") or ""),
        decision_note or "",
        customer_message or "",
    ]).lower()
    return any(term in text for term in ["return", "returned", "excess quantity", "wrong item", "replacement"])


def extract_order_id_from_text(text: str) -> Optional[str]:
    match = re.search(r"\bORD-[A-Za-z0-9-]+\b", text or "", re.IGNORECASE)
    return match.group(0).upper() if match else None


def now_msg_id(prefix: str) -> str:
    from datetime import datetime
    import uuid

    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6].upper()}"


@router.get("")
async def list_portal_disputes(
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    staff=Depends(get_current_staff),
    db=Depends(get_db),
):
    where = ""
    args = []
    if status:
        where = "WHERE d.status = $1"
        args.append(status)
    args.append(limit)
    limit_param = f"${len(args)}"

    rows = await db.fetch(
        f"""
        SELECT d.*,
               c.company_name,
               c.contact_name,
               c.email AS customer_email,
               i.total_amount_inr,
               i.balance_due_inr,
               lm.last_message_at
        FROM portal_disputes d
        JOIN customers c ON c.customer_id = d.customer_id
        LEFT JOIN invoices i ON i.invoice_id = d.invoice_id
        LEFT JOIN (
            SELECT dispute_id, MAX(created_at) AS last_message_at
            FROM portal_dispute_messages
            GROUP BY dispute_id
        ) lm ON lm.dispute_id = d.dispute_id
        {where}
        ORDER BY d.updated_at DESC, d.created_at DESC
        LIMIT {limit_param}
        """,
        *args,
    )
    return {"disputes": [dict(r) for r in rows]}


@router.get("/stats")
async def portal_dispute_stats(staff=Depends(get_current_staff), db=Depends(get_db)):
    rows = await db.fetch(
        """
        SELECT status, COUNT(*) AS count
        FROM portal_disputes
        GROUP BY status
        """
    )
    by_status = {r["status"]: int(r["count"]) for r in rows}
    total = sum(by_status.values())
    pending = by_status.get("pending_admin", 0)
    awaiting_customer = by_status.get("awaiting_customer", 0)
    final_count = sum(by_status.get(s, 0) for s in FINAL_STATUSES)
    return {
        "total": total,
        "pending_admin": pending,
        "awaiting_customer": awaiting_customer,
        "final": final_count,
        "by_status": by_status,
    }


@router.get("/{dispute_id}/ai-suggest")
async def portal_dispute_ai_suggest(dispute_id: str, staff=Depends(get_current_staff), db=Depends(get_db)):
    """Ollama Cloud LLM analyzes the portal dispute thread and pre-fills resolution fields."""
    dispute = await db.fetchrow(
        """
        SELECT d.*,
               c.company_name, c.contact_name, c.email AS customer_email,
               i.total_amount_inr, i.balance_due_inr
        FROM portal_disputes d
        JOIN customers c ON c.customer_id = d.customer_id
        LEFT JOIN invoices i ON i.invoice_id = d.invoice_id
        WHERE d.dispute_id = $1
        """,
        dispute_id,
    )
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")

    d = dict(dispute)
    messages = await db.fetch(
        "SELECT sender_type, body FROM portal_dispute_messages WHERE dispute_id=$1 ORDER BY created_at ASC",
        dispute_id,
    )
    thread = "\n".join(f"[{m['sender_type'].upper()}]: {m['body']}" for m in messages)

    invoice_id = d.get("invoice_id") or ""
    invoice_total = float(d.get("total_amount_inr") or d.get("balance_due_inr") or 0)
    customer_name = d.get("company_name") or d.get("contact_name") or ""
    customer_email = d.get("customer_email") or ""
    dispute_type = (d.get("dispute_type") or "general").replace("_", " ")
    ai_summary = d.get("ai_summary") or d.get("subject") or ""

    prompt = f"""You are an Accounts Receivable Controller at MAQ Manufacturing (India).
A customer raised a portal dispute. Review the context and thread, then make a fair resolution.

DISPUTE: {dispute_id} | Type: {dispute_type} | Invoice: {invoice_id or 'N/A'} (₹{invoice_total:,.0f}) | Customer: {customer_name}
AI SUMMARY: {ai_summary}
THREAD:
{thread or "(No messages yet)"}

Rules:
- Billing errors → full credit
- Partial damage → credit only the damaged portion mentioned in the thread
- Unproven claim → conservative partial, note documentation needed
- Never default to 50% without a real reason

Return JSON only:
{{
  "suggested_amount": <number>,
  "rationale": "<2-3 sentences: what happened, why this credit is fair>",
  "resolution_note": "<1 sentence SOX audit note>",
  "email_subject": "<professional subject mentioning invoice {invoice_id}>",
  "email_body": "<professional 3-4 paragraph email to {customer_name}, apologise, state credit and timeline, close with Regards, MAQ Finance Disputes Team>"
}}"""

    try:
        raw = call_llm([{"role": "user", "content": prompt}], json_mode=True)
        result = json.loads(raw)
        return {
            "dispute_id": dispute_id,
            "invoice_id": invoice_id,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "suggested_amount": result.get("suggested_amount", 0),
            "claim_amount": invoice_total,
            "rationale": result.get("rationale", ""),
            "resolution_note": result.get("resolution_note", ""),
            "email_subject": result.get("email_subject", f"Resolution — {invoice_id}"),
            "email_body": result.get("email_body", ""),
        }
    except Exception as e:
        logger.error(f"Portal dispute AI suggest failed for {dispute_id}: {e}")
        fallback_amt = invoice_total * 0.5
        return {
            "dispute_id": dispute_id, "invoice_id": invoice_id,
            "customer_email": customer_email, "customer_name": customer_name,
            "suggested_amount": fallback_amt, "claim_amount": invoice_total,
            "rationale": "Unable to auto-suggest — please review manually.",
            "resolution_note": f"Dispute {dispute_id} reviewed manually.",
            "email_subject": f"Regarding Your Dispute — Invoice {invoice_id}",
            "email_body": (
                f"Dear {customer_name or 'Customer'},\n\nThank you for raising dispute {dispute_id}. "
                f"We have reviewed your claim and will process the appropriate credit within 5-7 business days.\n\n"
                f"Regards,\nMAQ Finance Disputes Team"
            ),
        }


@router.get("/{dispute_id}")
async def get_portal_dispute(dispute_id: str, staff=Depends(get_current_staff), db=Depends(get_db)):
    dispute = await db.fetchrow(
        """
        SELECT d.*,
               c.company_name,
               c.contact_name,
               c.email AS customer_email,
               c.phone AS customer_phone,
               i.total_amount_inr,
               i.balance_due_inr,
               i.payment_status
        FROM portal_disputes d
        JOIN customers c ON c.customer_id = d.customer_id
        LEFT JOIN invoices i ON i.invoice_id = d.invoice_id
        WHERE d.dispute_id = $1
        """,
        dispute_id,
    )
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")

    messages = await db.fetch(
        """
        SELECT *
        FROM portal_dispute_messages
        WHERE dispute_id=$1
        ORDER BY created_at ASC
        """,
        dispute_id,
    )
    attachments = await db.fetch(
        """
        SELECT attachment_id, dispute_id, message_id, filename, content_type, size_bytes, uploaded_by, created_at
        FROM portal_dispute_attachments
        WHERE dispute_id=$1
        ORDER BY created_at ASC
        """,
        dispute_id,
    )
    return {
        "dispute": dict(dispute),
        "messages": [dict(r) for r in messages],
        "attachments": [dict(r) for r in attachments],
    }


@router.post("/{dispute_id}/messages")
async def admin_reply(
    dispute_id: str,
    payload: AdminMessagePayload,
    background_tasks: BackgroundTasks,
    staff=Depends(require_admin),
    db=Depends(get_db),
):
    body = (payload.message or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message is required")

    message_id = now_msg_id("DMSG")

    async with db.transaction():
        dispute = await db.fetchrow(
            """
            SELECT d.*, c.email AS customer_email, c.company_name
            FROM portal_disputes d
            JOIN customers c ON c.customer_id = d.customer_id
            WHERE d.dispute_id=$1
            FOR UPDATE
            """,
            dispute_id,
        )
        if not dispute:
            raise HTTPException(status_code=404, detail="Dispute not found")
        if dispute["status"] in FINAL_STATUSES:
            raise HTTPException(status_code=409, detail="This dispute is final and cannot receive messages")
        if dispute["next_actor"] != "admin":
            raise HTTPException(status_code=409, detail="Waiting for customer response")

        await db.execute(
            """
            INSERT INTO portal_dispute_messages (message_id, dispute_id, sender_type, sender_id, body)
            VALUES ($1,$2,'admin',$3,$4)
            """,
            message_id,
            dispute_id,
            staff["username"],
            body,
        )
        await db.execute(
            """
            UPDATE portal_disputes
            SET status='awaiting_customer', next_actor='customer', updated_at=NOW()
            WHERE dispute_id=$1
            """,
            dispute_id,
        )
        await db.execute(
            """
            INSERT INTO audit_log (event_type, agent_name, user_id, customer_id, order_id, invoice_id, action, details, outcome)
            VALUES ('PORTAL_DISPUTE_ADMIN_MESSAGE', 'admin_portal', $1, $2, $3, $4, $5, $6::jsonb, 'awaiting_customer')
            """,
            staff["username"],
            dispute["customer_id"],
            dispute["order_id"],
            dispute["invoice_id"],
            f"Admin replied to dispute {dispute_id}",
            json.dumps({"dispute_id": dispute_id}),
        )

    if dispute["customer_email"]:
        background_tasks.add_task(
            send_optional_email,
            dispute["customer_email"],
            f"Update on your dispute {dispute_id}",
            f"Dear {dispute['company_name']},\n\nAdmin has replied to your dispute {dispute_id}. Please sign in to the customer portal to view and respond.\n\nRegards,\nMAQ Finance Disputes Team",
        )

    return {"message_id": message_id, "status": "awaiting_customer", "next_actor": "customer"}


@router.patch("/{dispute_id}/decision")
async def decide_dispute(
    dispute_id: str,
    payload: DecisionPayload,
    background_tasks: BackgroundTasks,
    staff=Depends(require_admin),
    db=Depends(get_db),
):
    new_status = (payload.status or "").strip().lower()
    if new_status not in {"resolved", "rejected", "closed"}:
        raise HTTPException(status_code=400, detail="Decision status must be resolved, rejected, or closed")

    decision_note = (payload.decision_note or "").strip()
    customer_message = (payload.customer_message or "").strip()
    credit_amount = max(0.0, float(payload.credit_amount_inr or 0))
    return_quantity = max(0, int(payload.return_quantity or 0))
    return_sku_id = (payload.return_sku_id or "").strip() or None

    if not decision_note:
        raise HTTPException(status_code=400, detail="Decision note is required")
    if not customer_message:
        raise HTTPException(status_code=400, detail="Customer-visible decision message is required")
    if new_status != "resolved" and return_quantity > 0:
        raise HTTPException(status_code=400, detail="Returned inventory can only be recorded when resolving a dispute")

    message_id = now_msg_id("DMSG")

    async with db.transaction():
        dispute = await db.fetchrow(
            """
            SELECT d.*, c.email AS customer_email, c.company_name
            FROM portal_disputes d
            JOIN customers c ON c.customer_id = d.customer_id
            WHERE d.dispute_id=$1
            FOR UPDATE
            """,
            dispute_id,
        )
        if not dispute:
            raise HTTPException(status_code=404, detail="Dispute not found")
        if dispute["status"] in FINAL_STATUSES:
            raise HTTPException(status_code=409, detail="This dispute is already final")

        # ── 1. Add the admin closing message ──────────────────────────────────
        await db.execute(
            """
            INSERT INTO portal_dispute_messages (message_id, dispute_id, sender_type, sender_id, body)
            VALUES ($1,$2,'admin',$3,$4)
            """,
            message_id,
            dispute_id,
            staff["username"],
            customer_message,
        )

        # ── 2. Update the dispute itself ───────────────────────────────────────
        await db.execute(
            """
            UPDATE portal_disputes
            SET status=$1,
                next_actor='none',
                closed_at=NOW(),
                decided_by=$2,
                decision_note=$3,
                updated_at=NOW()
            WHERE dispute_id=$4
            """,
            new_status,
            staff["username"],
            decision_note,
            dispute_id,
        )

        # ── 3. Financial cascade if credit is being applied ────────────────────
        credit_note_id = None
        if new_status == "resolved" and credit_amount > 0 and dispute["invoice_id"]:
            invoice_id = dispute["invoice_id"]
            customer_id = dispute["customer_id"]

            # a) Fetch current invoice to avoid going negative
            inv = await db.fetchrow(
                "SELECT balance_due_inr, total_amount_inr, order_id FROM invoices WHERE invoice_id=$1",
                invoice_id,
            )
            if inv:
                current_balance = float(inv["balance_due_inr"] or 0)
                applied_credit = min(credit_amount, current_balance)  # never credit more than owed
                new_balance = max(0.0, current_balance - applied_credit)
                new_pay_status = "paid" if new_balance <= 0 else "partial"
                credit_note_id = f"CN-{dispute_id}"

                # b) Reduce invoice balance
                await db.execute(
                    """
                    UPDATE invoices
                    SET balance_due_inr = $1,
                        payment_status  = $2,
                        credit_note_id  = $3,
                        updated_at      = NOW()
                    WHERE invoice_id = $4
                    """,
                    new_balance,
                    new_pay_status,
                    credit_note_id,
                    invoice_id,
                )

                # c) Insert credit memo into AR ledger
                import uuid as _uuid
                ar_id = f"AR-CM-{_uuid.uuid4().hex[:10].upper()}"
                await db.execute(
                    """
                    INSERT INTO ar_ledger
                        (ar_id, customer_id, invoice_id, order_id, transaction_type,
                         transaction_date, amount_inr, outstanding_balance_inr,
                         payment_status, last_action)
                    VALUES ($1,$2,$3,$4,'credit_memo',NOW(),$5,$6,$7,'credit_applied')
                    """,
                    ar_id,
                    customer_id,
                    invoice_id,
                    inv["order_id"],
                    -applied_credit,           # negative = money going back to customer
                    0,                         # outstanding_balance_inr is 0 since it is applied
                    "paid",                    # payment_status is 'paid' since it is fully applied
                )

                # d) Insert into payments table as credit payment record
                pay_id = f"PAY-CN-{_uuid.uuid4().hex[:14].upper()}"  # max 30 chars
                await db.execute(
                    """
                    INSERT INTO payments (payment_id, invoice_id, amount_inr, payment_date,
                                          payment_method, bank_ref_number, status)
                    VALUES ($1,$2,$3,NOW(),'credit_note',$4,'processed')
                    ON CONFLICT (payment_id) DO NOTHING
                    """,
                    pay_id,
                    invoice_id,
                    applied_credit,
                    credit_note_id,
                )

                # d2) Permanent Credit History entry for the approved dispute credit.
                await db.execute(
                    """
                    INSERT INTO credit_memos
                        (memo_id, order_id, invoice_id, customer_id, dispute_id,
                         amount_inr, reason, approved_by, approved_by_role,
                         balance_before_inr, balance_after_inr, source, payment_ref)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'dispute_resolution',$12)
                    ON CONFLICT (memo_id) DO NOTHING
                    """,
                    now_msg_id("MEMO"),
                    inv["order_id"],
                    invoice_id,
                    customer_id,
                    dispute_id,
                    applied_credit,
                    decision_note or "Credit approved from portal dispute resolution",
                    staff["username"],
                    staff["role"],
                    current_balance,
                    new_balance,
                    credit_note_id,
                )

                # e) Reduce customer open AR balance
                await db.execute(
                    """
                    UPDATE customers
                    SET open_ar_balance_inr = GREATEST(0, open_ar_balance_inr - $1),
                        updated_at = NOW()
                    WHERE customer_id = $2
                    """,
                    applied_credit,
                    customer_id,
                )

                # f) Update AR ledger entry for this invoice (outstanding balance sync)
                await db.execute(
                    """
                    UPDATE ar_ledger
                    SET outstanding_balance_inr = $1,
                        payment_status          = $2,
                        last_action             = 'credit_applied',
                        last_action_date        = NOW()
                    WHERE invoice_id = $3 AND transaction_type != 'credit_memo'
                    """,
                    new_balance,
                    new_pay_status,
                    invoice_id,
                )

        inventory_return = None
        if new_status == "resolved" and return_quantity > 0:
            if not is_return_resolution(dispute, decision_note, customer_message):
                raise HTTPException(
                    status_code=400,
                    detail="Returned units can only be recorded for return/replacement/excess-quantity disputes",
                )
            message_rows = await db.fetch(
                "SELECT body FROM portal_dispute_messages WHERE dispute_id = $1 ORDER BY created_at ASC",
                dispute_id,
            )
            extracted_order_id = extract_order_id_from_text(
                "\n".join([dispute["subject"] or "", dispute["ai_summary"] or ""] + [m["body"] or "" for m in message_rows])
            )
            order = await db.fetchrow(
                """
                SELECT o.order_id, o.sku_id, o.quantity
                FROM orders o
                WHERE o.customer_id = $3
                  AND o.order_id = COALESCE(NULLIF($1, ''), (SELECT order_id FROM invoices WHERE invoice_id = $2), $4)
                FOR UPDATE
                """,
                dispute["order_id"],
                dispute["invoice_id"],
                dispute["customer_id"],
                extracted_order_id,
            )
            if not order and not return_sku_id:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot record returned inventory because the dispute is not linked to an order. Select a return SKU.",
                )
            if order and not (dispute["order_id"] or "").strip():
                await db.execute(
                    "UPDATE portal_disputes SET order_id = $1, updated_at = NOW() WHERE dispute_id = $2",
                    order["order_id"],
                    dispute_id,
                )
            if order and return_quantity > int(order["quantity"] or 0):
                raise HTTPException(status_code=400, detail="Returned quantity cannot exceed the original order quantity")

            restock_sku_id = order["sku_id"] if order else return_sku_id
            restock_order_id = order["order_id"] if order else "unlinked"

            inventory_return = await record_adjustment(
                db,
                sku_id=restock_sku_id,
                quantity_delta=return_quantity,
                txn_type=RETURN_RECEIPT,
                reason=(
                    f"Return received from resolved dispute {dispute_id}; "
                    f"order {restock_order_id}; invoice {dispute['invoice_id'] or 'N/A'}"
                ),
                performed_by=staff["username"],
                actor_type="human",
            )

        # ── 4. Audit log ───────────────────────────────────────────────────────
        await db.execute(
            """
            INSERT INTO audit_log (event_type, agent_name, user_id, customer_id, order_id, invoice_id, action, details, outcome)
            VALUES ('PORTAL_DISPUTE_DECIDED', 'admin_portal', $1, $2, $3, $4, $5, $6::jsonb, $7)
            """,
            staff["username"],
            dispute["customer_id"],
            dispute["order_id"],
            dispute["invoice_id"],
            f"Admin marked dispute {dispute_id} as {new_status}",
            json.dumps({
                "dispute_id": dispute_id,
                "decision_note": decision_note,
                "credit_amount_inr": credit_amount,
                "credit_note_id": credit_note_id,
                "return_quantity": return_quantity,
                "return_sku_id": return_sku_id,
                "inventory_return": inventory_return,
            }),
            new_status,
        )

    if dispute["customer_email"]:
        background_tasks.add_task(
            send_optional_email,
            dispute["customer_email"],
            f"Decision on your dispute {dispute_id}",
            f"Dear {dispute['company_name']},\n\n{customer_message}\n\nStatus: {new_status.title()}\n\nRegards,\nMAQ Finance Disputes Team",
        )

    return {
        "dispute_id": dispute_id,
        "status": new_status,
        "next_actor": "none",
        "credit_applied_inr": credit_amount if new_status == "resolved" else 0,
        "credit_note_id": credit_note_id,
        "inventory_return": inventory_return,
    }


@router.get("/{dispute_id}/attachments/{attachment_id}")
async def download_admin_attachment(
    dispute_id: str,
    attachment_id: str,
    staff=Depends(get_current_staff),
    db=Depends(get_db),
):
    attachment = await db.fetchrow(
        """
        SELECT *
        FROM portal_dispute_attachments
        WHERE dispute_id=$1 AND attachment_id=$2
        """,
        dispute_id,
        attachment_id,
    )
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    path = Path(attachment["file_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file is missing on server")

    return FileResponse(path, media_type=attachment["content_type"] or "application/octet-stream", filename=attachment["filename"])
