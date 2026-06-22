"""Customer-facing portal dispute APIs.

Creates and manages customer-created dispute threads with strict turn-taking:
customer -> admin -> customer -> admin. Customer replies are blocked until Admin
responds. Withdrawal is customer-controlled until a final decision is made.
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.customer_portal import get_current_customer
from database.postgres import get_db
from services.email_service import send_optional_email
from services.portal_dispute_summary import refresh_portal_dispute_summary
from services.portal_dispute_extraction import extract_portal_dispute_preview

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_ROOT = Path("uploads/disputes")
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}
ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_FILES = 5
MAX_FILE_BYTES = 10 * 1024 * 1024
FINAL_STATUSES = {"resolved", "rejected", "closed", "withdrawn"}


def now_id(prefix: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def safe_filename(filename: str) -> str:
    name = Path(filename or "proof").name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")
    return name or "proof"


def row_to_dict(row):
    return dict(row) if row else None


async def validate_and_save_attachments(
    files: Optional[List[UploadFile]],
    dispute_id: str,
    message_id: str,
    uploaded_by: str,
    db,
) -> int:
    if not files:
        return 0

    clean_files = [f for f in files if f and f.filename]
    if len(clean_files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FILES} proof files are allowed")

    target_dir = UPLOAD_ROOT / dispute_id
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_count = 0

    for file in clean_files:
        original_name = safe_filename(file.filename)
        suffix = Path(original_name).suffix.lower()
        content_type = file.content_type or "application/octet-stream"

        if suffix not in ALLOWED_SUFFIXES or content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Only PDF, PNG, JPG, and JPEG proof files are allowed",
            )

        attachment_id = now_id("DATT")
        stored_name = f"{attachment_id}-{original_name}"
        file_path = target_dir / stored_name

        size = 0
        async with aiofiles.open(file_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    try:
                        file_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise HTTPException(status_code=400, detail="Each proof file must be 10 MB or smaller")
                await out.write(chunk)

        await db.execute(
            """
            INSERT INTO portal_dispute_attachments
                (attachment_id, dispute_id, message_id, filename, content_type, file_path, size_bytes, uploaded_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """,
            attachment_id,
            dispute_id,
            message_id,
            original_name,
            content_type,
            str(file_path),
            size,
            uploaded_by,
        )
        saved_count += 1

    return saved_count


async def ensure_customer_owns_invoice_or_order(db, customer_id: str, invoice_id: Optional[str], order_id: Optional[str]):
    resolved_order_id = order_id or None

    if invoice_id:
        inv = await db.fetchrow(
            "SELECT invoice_id, order_id FROM invoices WHERE invoice_id=$1 AND customer_id=$2",
            invoice_id,
            customer_id,
        )
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found for this customer")
        resolved_order_id = resolved_order_id or inv["order_id"]

    if resolved_order_id:
        order = await db.fetchrow(
            "SELECT order_id FROM orders WHERE order_id=$1 AND customer_id=$2",
            resolved_order_id,
            customer_id,
        )
        if not order:
            raise HTTPException(status_code=404, detail="Order not found for this customer")

    return resolved_order_id


class WithdrawPayload(BaseModel):
    reason: Optional[str] = ""


class DisputeAIPreviewRequest(BaseModel):
    text: str


@router.get("")
async def list_my_disputes(customer=Depends(get_current_customer), db=Depends(get_db)):
    rows = await db.fetch(
        """
        SELECT d.*, i.total_amount_inr, i.balance_due_inr
        FROM portal_disputes d
        LEFT JOIN invoices i ON i.invoice_id = d.invoice_id
        WHERE d.customer_id = $1
        ORDER BY d.updated_at DESC, d.created_at DESC
        """,
        customer["customer_id"],
    )
    return {"disputes": [dict(r) for r in rows]}


@router.post("/ai/preview")
async def ai_dispute_preview(
    payload: DisputeAIPreviewRequest,
    customer=Depends(get_current_customer),
    db=Depends(get_db),
):
    """Extract editable dispute fields from a natural-language customer note.

    This endpoint only prepares a preview. It does not create a dispute, does not
    notify Admin, and does not save attachments. The customer must review and
    submit the final form through POST /api/customer-portal/disputes.
    """
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Describe the dispute before running AI extraction")

    invoices = await db.fetch(
        """
        SELECT
            invoice_id,
            order_id,
            payment_status AS status,
            total_amount_inr,
            balance_due_inr,
            due_date
        FROM invoices
        WHERE customer_id = $1
        ORDER BY invoice_date DESC NULLS LAST, due_date DESC NULLS LAST
        LIMIT 25
        """,
        customer["customer_id"],
    )

    orders = await db.fetch(
        """
        SELECT
            order_id,
            status,
            total_amount_inr,
            requested_delivery_date,
            created_at
        FROM orders
        WHERE customer_id = $1
        ORDER BY created_at DESC NULLS LAST
        LIMIT 25
        """,
        customer["customer_id"],
    )

    preview = extract_portal_dispute_preview(
        text,
        [dict(r) for r in invoices],
        [dict(r) for r in orders],
    )
    return preview


@router.post("")
async def create_dispute(
    background_tasks: BackgroundTasks,
    invoice_id: Optional[str] = Form(None),
    order_id: Optional[str] = Form(None),
    dispute_type: str = Form("general"),
    subject: str = Form(...),
    message: str = Form(...),
    attachments: Optional[List[UploadFile]] = File(None),
    customer=Depends(get_current_customer),
    db=Depends(get_db),
):
    subject = (subject or "").strip()
    message = (message or "").strip()
    dispute_type = (dispute_type or "general").strip().lower()

    if not subject:
        raise HTTPException(status_code=400, detail="Subject is required")
    if not message:
        raise HTTPException(status_code=400, detail="First message is required")

    resolved_order_id = await ensure_customer_owns_invoice_or_order(
        db,
        customer["customer_id"],
        invoice_id,
        order_id,
    )

    dispute_id = now_id("DISP")
    message_id = now_id("DMSG")

    async with db.transaction():
        await db.execute(
            """
            INSERT INTO portal_disputes
                (dispute_id, customer_id, invoice_id, order_id, dispute_type, subject,
                 ai_summary, ai_summary_status, status, next_actor, proof_count)
            VALUES ($1,$2,$3,$4,$5,$6,$7,'pending','pending_admin','admin',0)
            """,
            dispute_id,
            customer["customer_id"],
            invoice_id or None,
            resolved_order_id,
            dispute_type,
            subject,
            "AI summary is being generated for Admin review.",
        )
        await db.execute(
            """
            INSERT INTO portal_dispute_messages
                (message_id, dispute_id, sender_type, sender_id, body)
            VALUES ($1,$2,'customer',$3,$4)
            """,
            message_id,
            dispute_id,
            customer["customer_id"],
            message,
        )
        saved_count = await validate_and_save_attachments(
            attachments,
            dispute_id,
            message_id,
            customer["customer_id"],
            db,
        )
        await db.execute(
            """
            UPDATE portal_disputes
            SET proof_count = $1, updated_at = NOW()
            WHERE dispute_id = $2
            """,
            saved_count,
            dispute_id,
        )
        await db.execute(
            """
            INSERT INTO audit_log (event_type, agent_name, user_id, customer_id, order_id, invoice_id, action, details, outcome)
            VALUES ('PORTAL_DISPUTE_CREATED', 'customer_portal', $1, $2, $3, $4, $5, $6::jsonb, 'pending_admin')
            """,
            customer["customer_id"],
            customer["customer_id"],
            resolved_order_id,
            invoice_id or None,
            f"Customer created dispute {dispute_id}",
            json.dumps({"dispute_id": dispute_id, "subject": subject, "proof_count": saved_count}),
        )

    background_tasks.add_task(refresh_portal_dispute_summary, dispute_id)

    admin_email = os.getenv("DISPUTE_ADMIN_EMAIL") or os.getenv("SMTP_FROM") or ""
    if admin_email:
        background_tasks.add_task(
            send_optional_email,
            admin_email,
            f"New customer dispute {dispute_id}",
            f"A new dispute was submitted by {customer.get('company_name')} ({customer.get('customer_id')}).\n\nSubject: {subject}\nInvoice: {invoice_id or 'N/A'}\nOrder: {resolved_order_id or 'N/A'}\n\nPlease review it in the O2C admin portal.",
        )

    return {
        "dispute_id": dispute_id,
        "status": "pending_admin",
        "next_actor": "admin",
        "message": "Dispute created. Waiting for Admin response.",
    }


@router.get("/{dispute_id}")
async def get_my_dispute(dispute_id: str, customer=Depends(get_current_customer), db=Depends(get_db)):
    dispute = await db.fetchrow(
        """
        SELECT d.*, c.company_name, c.contact_name, c.email, i.total_amount_inr, i.balance_due_inr
        FROM portal_disputes d
        JOIN customers c ON c.customer_id = d.customer_id
        LEFT JOIN invoices i ON i.invoice_id = d.invoice_id
        WHERE d.dispute_id=$1 AND d.customer_id=$2
        """,
        dispute_id,
        customer["customer_id"],
    )
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")

    messages = await db.fetch(
        """
        SELECT * FROM portal_dispute_messages
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
async def customer_reply(
    dispute_id: str,
    background_tasks: BackgroundTasks,
    message: str = Form(...),
    attachments: Optional[List[UploadFile]] = File(None),
    customer=Depends(get_current_customer),
    db=Depends(get_db),
):
    message = (message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    message_id = now_id("DMSG")

    async with db.transaction():
        dispute = await db.fetchrow(
            """
            SELECT * FROM portal_disputes
            WHERE dispute_id=$1 AND customer_id=$2
            FOR UPDATE
            """,
            dispute_id,
            customer["customer_id"],
        )
        if not dispute:
            raise HTTPException(status_code=404, detail="Dispute not found")
        if dispute["status"] in FINAL_STATUSES:
            raise HTTPException(status_code=409, detail="This dispute is closed and cannot receive messages")
        if dispute["next_actor"] != "customer":
            raise HTTPException(status_code=409, detail="Please wait for Admin response before sending another message")

        await db.execute(
            """
            INSERT INTO portal_dispute_messages
                (message_id, dispute_id, sender_type, sender_id, body)
            VALUES ($1,$2,'customer',$3,$4)
            """,
            message_id,
            dispute_id,
            customer["customer_id"],
            message,
        )
        saved_count = await validate_and_save_attachments(
            attachments,
            dispute_id,
            message_id,
            customer["customer_id"],
            db,
        )
        await db.execute(
            """
            UPDATE portal_disputes
            SET status='pending_admin', next_actor='admin', proof_count = proof_count + $1, updated_at=NOW()
            WHERE dispute_id=$2
            """,
            saved_count,
            dispute_id,
        )
        await db.execute(
            """
            INSERT INTO audit_log (event_type, agent_name, user_id, customer_id, order_id, invoice_id, action, details, outcome)
            VALUES ('PORTAL_DISPUTE_CUSTOMER_MESSAGE', 'customer_portal', $1, $2, $3, $4, $5, $6::jsonb, 'pending_admin')
            """,
            customer["customer_id"],
            customer["customer_id"],
            dispute["order_id"],
            dispute["invoice_id"],
            f"Customer replied to dispute {dispute_id}",
            json.dumps({"dispute_id": dispute_id, "proof_count_added": saved_count}),
        )

    background_tasks.add_task(refresh_portal_dispute_summary, dispute_id)

    # Notify admin that customer has replied
    admin_email = os.getenv("DISPUTE_ADMIN_EMAIL") or os.getenv("SMTP_FROM") or ""
    if admin_email:
        background_tasks.add_task(
            send_optional_email,
            admin_email,
            f"Customer replied to dispute {dispute_id}",
            (
                f"Customer {customer.get('company_name')} ({customer.get('customer_id')}) "
                f"has replied to dispute {dispute_id}.\n\n"
                f"Message: {message[:300]}{'...' if len(message) > 300 else ''}\n\n"
                f"Please review and respond in the O2C admin portal."
            ),
        )

    return {"message_id": message_id, "status": "pending_admin", "next_actor": "admin"}


@router.post("/{dispute_id}/withdraw")
async def withdraw_dispute(
    dispute_id: str,
    payload: WithdrawPayload,
    background_tasks: BackgroundTasks,
    customer=Depends(get_current_customer),
    db=Depends(get_db),
):
    reason = (payload.reason or "").strip()
    system_message_id = now_id("DMSG")

    async with db.transaction():
        dispute = await db.fetchrow(
            """
            SELECT * FROM portal_disputes
            WHERE dispute_id=$1 AND customer_id=$2
            FOR UPDATE
            """,
            dispute_id,
            customer["customer_id"],
        )
        if not dispute:
            raise HTTPException(status_code=404, detail="Dispute not found")
        if dispute["status"] in FINAL_STATUSES:
            raise HTTPException(status_code=409, detail="This dispute is already final and cannot be withdrawn")

        await db.execute(
            """
            UPDATE portal_disputes
            SET status='withdrawn', next_actor='none', withdrawn_at=NOW(), withdrawn_reason=$1, updated_at=NOW()
            WHERE dispute_id=$2
            """,
            reason,
            dispute_id,
        )
        await db.execute(
            """
            INSERT INTO portal_dispute_messages (message_id, dispute_id, sender_type, sender_id, body)
            VALUES ($1,$2,'system',$3,$4)
            """,
            system_message_id,
            dispute_id,
            customer["customer_id"],
            f"Customer withdrew this dispute.{(' Reason: ' + reason) if reason else ''}",
        )
        await db.execute(
            """
            INSERT INTO audit_log (event_type, agent_name, user_id, customer_id, order_id, invoice_id, action, details, outcome)
            VALUES ('PORTAL_DISPUTE_WITHDRAWN', 'customer_portal', $1, $2, $3, $4, $5, $6::jsonb, 'withdrawn')
            """,
            customer["customer_id"],
            customer["customer_id"],
            dispute["order_id"],
            dispute["invoice_id"],
            f"Customer withdrew dispute {dispute_id}",
            json.dumps({"dispute_id": dispute_id, "reason": reason}),
        )

    admin_email = os.getenv("DISPUTE_ADMIN_EMAIL") or os.getenv("SMTP_FROM") or ""
    if admin_email:
        background_tasks.add_task(
            send_optional_email,
            admin_email,
            f"Customer withdrew dispute {dispute_id}",
            f"Customer {customer.get('company_name')} withdrew dispute {dispute_id}.\n\nReason: {reason or 'No reason provided'}",
        )

    return {"dispute_id": dispute_id, "status": "withdrawn", "next_actor": "none"}


@router.get("/{dispute_id}/attachments/{attachment_id}")
async def download_my_attachment(
    dispute_id: str,
    attachment_id: str,
    customer=Depends(get_current_customer),
    db=Depends(get_db),
):
    attachment = await db.fetchrow(
        """
        SELECT a.*
        FROM portal_dispute_attachments a
        JOIN portal_disputes d ON d.dispute_id = a.dispute_id
        WHERE a.dispute_id=$1 AND a.attachment_id=$2 AND d.customer_id=$3
        """,
        dispute_id,
        attachment_id,
        customer["customer_id"],
    )
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    path = Path(attachment["file_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file is missing on server")

    return FileResponse(path, media_type=attachment["content_type"] or "application/octet-stream", filename=attachment["filename"])
