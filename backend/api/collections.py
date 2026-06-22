"""
O2C Agent v2.0 — Collections API (Agent 8)
Dunning email generation via Groq LLaMA 3.3 70B + Gmail SMTP delivery.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from database.postgres import get_db
from api.staff_deps import require_role
from config import settings
import logging, smtplib, uuid
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

router = APIRouter()
logger = logging.getLogger(__name__)

COLLECTIONS_ROLES = ["admin", "collections_analyst"]


# ── List dunning log ──────────────────────────────────────────────

@router.get("")
async def list_dunning(customer_id: str = None, limit: int = 100, db=Depends(get_db), staff=Depends(require_role(COLLECTIONS_ROLES))):
    q = """SELECT d.*, c.company_name, c.email as customer_email
           FROM dunning_log d
           JOIN customers c ON d.customer_id = c.customer_id
           WHERE 1=1"""
    params = []
    if customer_id:
        params.append(customer_id)
        q += f" AND d.customer_id = ${len(params)}"
    params.append(limit)
    q += f" ORDER BY d.created_at DESC LIMIT ${len(params)}"
    rows = await db.fetch(q, *params)
    return {"dunning_log": [dict(r) for r in rows]}


@router.get("/segments")
async def customer_segments(db=Depends(get_db), staff=Depends(require_role(COLLECTIONS_ROLES))):
    rows = await db.fetch(
        "SELECT account_segment, COUNT(*) as count FROM dunning_log GROUP BY account_segment"
    )
    return {"segments": [dict(r) for r in rows]}


# ── Generate + Send Dunning Email ─────────────────────────────────

class DunningRequest(BaseModel):
    invoice_id: str
    send_email: bool = False   # True = actually send via Gmail SMTP


@router.post("/generate-dunning")
async def generate_dunning(
    payload: DunningRequest,
    db=Depends(get_db),
    staff=Depends(require_role(["admin", "collections_analyst"])),
):
    """
    Agent 8 — Dunning email generation via Groq LLaMA 3.3 70B.
    Optionally sends via Gmail SMTP.
    """
    # Fetch invoice + customer details
    inv = await db.fetchrow(
        """SELECT i.*, c.company_name, c.contact_name, c.email as customer_email,
                  c.payment_terms_days
           FROM invoices i
           JOIN customers c ON i.customer_id = c.customer_id
           WHERE i.invoice_id = $1""",
        payload.invoice_id
    )
    if not inv:
        raise HTTPException(404, f"Invoice {payload.invoice_id} not found")

    inv = dict(inv)
    days_overdue = max(0, inv.get("days_overdue", 0) or 0)

    # ── Agent 8: k-means customer segmentation → drives dunning tone ──
    from ml.model_placeholders import predict_customer_segment
    customer_row = await db.fetchrow("SELECT * FROM customers WHERE customer_id=$1", inv["customer_id"])
    if customer_row:
        seg_result = predict_customer_segment(dict(customer_row))
        segment    = seg_result["segment"]    # Premium / Standard / At-Risk / Problem
    else:
        segment = "Standard"

    tone_map = {
        "Premium":  "gentle_reminder",   # valued customer — polite, relationship-first
        "Standard": "firm",              # standard overdue notice
        "At-Risk":  "urgent",            # escalated, payment plan offered
        "Problem":  "legal_warning",     # final notice, mention collections agency
    }
    forced_tone = tone_map.get(segment, "firm")

    # Determine dunning level
    dunning_level = (
        1 if days_overdue <= 15 else
        2 if days_overdue <= 30 else
        3
    )

    # Generate email with Groq — pass k-means segment tone
    from ml.groq_client import generate_dunning_email
    email_content = generate_dunning_email(
        customer_name=inv["company_name"],
        invoice_id=payload.invoice_id,
        amount_inr=float(inv["total_amount_inr"]),
        days_overdue=days_overdue,
        payment_terms=inv.get("payment_terms_days", 30),
        contact_name=inv.get("contact_name", ""),
        tone=forced_tone,
    )

    subject = email_content.get("subject", f"Payment Reminder - {payload.invoice_id}")
    body    = email_content.get("body", "")
    tone    = email_content.get("tone", forced_tone)

    email_sent = False
    send_error = None

    # Send via Gmail SMTP if requested and credentials available
    if payload.send_email and settings.smtp_user and settings.smtp_password:
        try:
            customer_email = inv.get("customer_email", "")
            if not customer_email:
                send_error = "Customer has no email address on record"
            else:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = settings.smtp_user
                msg["To"]      = customer_email
                msg.attach(MIMEText(body, "plain"))
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(settings.smtp_user, customer_email, msg.as_string())
                email_sent = True
                logger.info(f"Dunning email sent to {customer_email} for {payload.invoice_id}")
        except Exception as e:
            send_error = str(e)
            logger.error(f"SMTP send failed: {e}")

    # Log to dunning_log table
    dunning_id = f"DUNN-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        await db.execute(
            """INSERT INTO dunning_log
               (dunning_id, customer_id, invoice_id, dunning_level, channel,
                message_subject, message_body_preview, sent_at, groq_generated, account_segment)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
            dunning_id,
            inv["customer_id"],
            payload.invoice_id,
            f"LEVEL_{dunning_level}",
            "email" if email_sent else "draft",
            subject,
            body[:500],
            datetime.utcnow(),
            True,
            segment,   # real k-means segment label
        )
    except Exception as e:
        logger.warning(f"Could not log dunning to DB: {e}")

    return {
        "dunning_id": dunning_id,
        "invoice_id": payload.invoice_id,
        "customer": inv["company_name"],
        "days_overdue": days_overdue,
        "dunning_level": dunning_level,
        "customer_segment": segment,
        "tone": tone,
        "subject": subject,
        "body": body,
        "email_sent": email_sent,
        "send_error": send_error,
        "model": "groq_llama-3.3-70b + kmeans_segmentation",
    }


@router.get("/overdue-invoices")
async def get_overdue_invoices(db=Depends(get_db), staff=Depends(require_role(COLLECTIONS_ROLES))):
    """Get all overdue invoices eligible for dunning + their customer segments."""
    rows = await db.fetch(
        """SELECT i.invoice_id, i.customer_id, c.company_name, c.email,
                  i.total_amount_inr, i.balance_due_inr, i.days_overdue,
                  i.payment_terms_days, i.reminder_count,
                  c.open_ar_balance_inr, c.avg_dso_days, c.missed_payments_12m,
                  c.credit_limit_inr, c.account_age_months, c.credit_tier
           FROM invoices i
           JOIN customers c ON i.customer_id = c.customer_id
           WHERE i.payment_status IN ('overdue', 'pending')
             AND i.days_overdue > 0
           ORDER BY i.days_overdue DESC"""
    )
    
    from ml.model_placeholders import predict_customer_segment
    invoices_with_segments = []
    for r in rows:
        inv_dict = dict(r)
        # Use K-Means to predict segment for the UI display
        seg_result = predict_customer_segment(inv_dict)
        inv_dict["customer_segment"] = seg_result["segment"]
        invoices_with_segments.append(inv_dict)
        
    return {"overdue_invoices": invoices_with_segments}


# ── MAF Collections Agent (autonomous, in-process — no Celery) ─────────────────

class AgentRunRequest(BaseModel):
    invoice_id: str


class ResumePayload(BaseModel):
    decision: str = "continue"          # e.g. write_off | payment_plan | agency | continue
    notes: str = ""


async def _run_agent_bg(invoice_id: str, triggered_by: str):
    """Background entrypoint — isolates agent failures from the request."""
    from agents_maf.collections.agent import run_collections_agent
    try:
        await run_collections_agent(invoice_id, triggered_by=triggered_by)
    except Exception as exc:  # noqa: BLE001 — already persisted to agent_runs
        logger.exception("Background collections agent failed for %s: %s", invoice_id, exc)


@router.post("/agent/run")
async def run_agent(
    payload: AgentRunRequest,
    background: BackgroundTasks,
    db=Depends(get_db),
    staff=Depends(require_role(COLLECTIONS_ROLES)),
):
    """Kick off the autonomous Collections Agent for one invoice.

    Returns immediately; the agent runs in-process via BackgroundTasks. Poll
    GET /agent/runs (or /agent/runs/{run_id}) for status.
    """
    if not await db.fetchrow("SELECT 1 FROM invoices WHERE invoice_id = $1", payload.invoice_id):
        raise HTTPException(404, f"Invoice {payload.invoice_id} not found")
    background.add_task(_run_agent_bg, payload.invoice_id, staff["username"])
    return {"status": "accepted", "invoice_id": payload.invoice_id}


@router.post("/agent/resume")
async def resume_agent(
    thread_id: str,
    payload: ResumePayload,
    staff=Depends(require_role(COLLECTIONS_ROLES)),
):
    """Resume a HITL-paused agent run with a human decision."""
    from agents_maf.collections.agent import resume_collections_agent
    result = await resume_collections_agent(thread_id, payload.model_dump())
    if result["status"] == "error":
        raise HTTPException(400, result["summary"])
    return result


@router.get("/agent/runs")
async def list_agent_runs(
    status: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_db),
    staff=Depends(require_role(COLLECTIONS_ROLES)),
):
    """List collections agent runs, optionally filtered by status."""
    q = "SELECT * FROM agent_runs WHERE agent_name = 'collections_agent'"
    params: list = []
    if status:
        params.append(status)
        q += f" AND status = ${len(params)}"
    params.append(limit)
    q += f" ORDER BY started_at DESC LIMIT ${len(params)}"
    rows = await db.fetch(q, *params)
    return {"runs": [dict(r) for r in rows]}


@router.get("/agent/runs/{run_id}")
async def get_agent_run(
    run_id: str,
    db=Depends(get_db),
    staff=Depends(require_role(COLLECTIONS_ROLES)),
):
    """Fetch a single agent run by its run_id."""
    row = await db.fetchrow("SELECT * FROM agent_runs WHERE run_id = $1", run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    return dict(row)
