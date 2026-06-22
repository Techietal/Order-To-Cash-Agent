"""
O2C Agent v2.0 — Main FastAPI Application
Full O2C lifecycle with 11 specialist agents, Policy Engine, and real-time WebSocket dashboard.
"""

import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from database.postgres import get_pool, init_schema, close_pool
from database.chromadb_client import init_collections

# API Routers
from api.orders import router as orders_router
from api.invoices import router as invoices_router
from api.ar_ledger import router as ar_router
from api.fraud import router as fraud_router
from api.hitl import router as hitl_router
from api.collections import router as collections_router
from api.disputes import router as disputes_router
from api.cash_application import router as cash_app_router
from api.analytics import router as analytics_router
from api.ml_monitor import router as ml_router
from api.portal import router as portal_router
from api.compliance import router as compliance_router
from api.auth import router as auth_router
from api.customer_portal import router as customer_portal_router
from api.customers import router as customers_router
from api.customer_disputes import router as customer_disputes_router
from api.portal_disputes import router as portal_disputes_router
from api.credit_memos import router as credit_memos_router
from api.inventory import router as inventory_router
from api.purchase_orders import router as purchase_orders_router
from api.products import router as products_router
from api.agents import router as agents_router

logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        import json
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                dead.append(connection)
        for c in dead:
            self.active_connections.remove(c)

ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    logger.info("O2C Agent v2.0 starting up...")
    # Initialize databases
    await init_schema()
    await init_collections()
    # Pre-warm AI models in background threads (non-blocking — models load while server accepts requests)
    import asyncio
    from ml.gliner_ner import get_gliner_model
    from ml.embeddings import get_embedding_model
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, get_gliner_model)
    loop.run_in_executor(None, get_embedding_model)
    logger.info("AI model pre-warm started in background threads.")

    # Train Isolation Forest on existing orders from DB
    try:
        from database.postgres import get_pool
        from ml.isolation_forest import train_order_isolation_forest
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT o.total_amount_inr, o.quantity, o.unit_price_inr, o.channel,
                          c.avg_dso_days, c.missed_payments_12m, c.open_ar_balance_inr, c.account_age_months
                   FROM orders o
                   LEFT JOIN customers c ON o.customer_id = c.customer_id
                   WHERE o.total_amount_inr > 0
                   ORDER BY o.created_at DESC LIMIT 500"""
            )
            if len(rows) >= 10:
                orders_data = [
                    {
                        "total_amount_inr": float(r["total_amount_inr"] or 0),
                        "quantity": int(r["quantity"] or 1),
                        "unit_price_inr": float(r["unit_price_inr"] or 0),
                        "channel": r["channel"] or "email",
                        "avg_dso_days": float(r["avg_dso_days"] or 30),
                        "missed_payments_12m": int(r["missed_payments_12m"] or 0),
                        "open_ar_balance_inr": float(r["open_ar_balance_inr"] or 0),
                        "account_age_months": int(r["account_age_months"] or 12),
                    }
                    for r in rows
                ]
                train_order_isolation_forest(orders_data)
                logger.info(f"Isolation Forest trained on {len(rows)} historical orders at startup")
            else:
                logger.warning(f"Only {len(rows)} orders in DB — Isolation Forest will train when more data arrives")
    except Exception as e:
        logger.error(f"Isolation Forest startup training failed: {e}")

    # Train k-means customer segmentation on existing customers
    try:
        from database.postgres import get_pool
        from ml.model_placeholders import train_kmeans
        pool = await get_pool()
        async with pool.acquire() as conn:
            cust_rows = await conn.fetch(
                """SELECT open_ar_balance_inr, avg_dso_days, missed_payments_12m,
                          credit_limit_inr, account_age_months
                   FROM customers WHERE is_active = TRUE LIMIT 500"""
            )
            if len(cust_rows) >= 4:
                custs = [
                    {
                        "open_ar_balance_inr": float(r["open_ar_balance_inr"] or 0),
                        "avg_dso_days": float(r["avg_dso_days"] or 30),
                        "missed_payments_12m": int(r["missed_payments_12m"] or 0),
                        "credit_limit_inr": float(r["credit_limit_inr"] or 100000),
                        "account_age_months": int(r["account_age_months"] or 12),
                    }
                    for r in cust_rows
                ]
                train_kmeans(custs)
                logger.info(f"k-means segmentation trained on {len(cust_rows)} customers at startup")
    except Exception as e:
        logger.error(f"k-means startup training failed: {e}")

    # Start Agent 7 — Payment Monitor background scheduler (every 15 min)
    import asyncio

    async def _payment_monitor_loop():
        """Agent 7: XGBoost payment delay scoring on all open invoices every 15 min."""
        await asyncio.sleep(30)   # initial delay so DB pool is fully ready
        while True:
            try:
                from database.postgres import get_pool
                from ml.model_placeholders import predict_payment_delay
                pool = await get_pool()
                async with pool.acquire() as conn:
                    open_invs = await conn.fetch(
                        """SELECT i.invoice_id, i.total_amount_inr, i.payment_terms_days,
                                  i.days_overdue, c.avg_dso_days, c.missed_payments_12m,
                                  i.customer_id, c.credit_limit_inr, c.open_ar_balance_inr,
                                  c.account_age_months
                           FROM invoices i
                           JOIN customers c ON i.customer_id = c.customer_id
                           WHERE i.payment_status IN ('pending', 'overdue')
                             AND i.balance_due_inr > 0
                           LIMIT 200"""
                    )
                    updated = 0
                    for inv in open_invs:
                        features = {
                            "invoice_amount_inr":       float(inv["total_amount_inr"] or 0),
                            "payment_terms_days":        int(inv["payment_terms_days"] or 30),
                            "customer_avg_days_late":    max(0, float(inv["avg_dso_days"] or 30) - 30),
                            "customer_missed_payments":  int(inv["missed_payments_12m"] or 0),
                            "open_ar_ratio":             float(inv["open_ar_balance_inr"] or 0) /
                                                          max(float(inv["credit_limit_inr"] or 100000), 1),
                            "account_age_months":        int(inv["account_age_months"] or 12),
                            "quarter":                   ((datetime.now().month - 1) // 3) + 1,
                            "promise_to_pay":            False,
                        }
                        result = predict_payment_delay(features)
                        bucket_map = {"GREEN": "current", "AMBER": "0-30", "RED": "31-60"}
                        bucket = bucket_map.get(result["bucket"], "0-30")
                        priority = 'HIGH' if result["late_probability"] > 0.7 else ('MEDIUM' if result["late_probability"] > 0.4 else 'LOW')
                        await conn.execute(
                            """UPDATE ar_ledger
                               SET xgboost_delay_score = $1,
                                   collection_priority = $2,
                                   aging_bucket = CASE WHEN days_overdue > 90 THEN '90+' WHEN days_overdue > 60 THEN '61-90' ELSE $3 END
                               WHERE invoice_id = $4""",
                            result["late_probability"],
                            priority,
                            bucket,
                            inv["invoice_id"],
                        )
                        updated += 1
                logger.info(f"Agent 7 Payment Monitor: scored {updated} open invoices")
            except Exception as e:
                logger.error(f"Agent 7 Payment Monitor error: {e}")
            await asyncio.sleep(900)   # 15 minutes

    asyncio.create_task(_payment_monitor_loop())
    logger.info("Agent 7 Payment Monitor scheduler started (15-min interval)")

    # Start Email Intake Poller — wraps the blocking Gmail OAuth poller in a thread
    # so it doesn't block the async event loop
    async def _email_intake_loop():
        try:
            from email_intake import config as intake_cfg
            from email_intake.poller import run_cycle
            import functools
            loop = asyncio.get_event_loop()
            logger.info("Email intake poller: running initial cycle...")
            await loop.run_in_executor(None, run_cycle)
            logger.info("Email intake poller: initial cycle complete. Polling every %d min.", intake_cfg.POLL_INTERVAL_MINUTES)
            while True:
                await asyncio.sleep(intake_cfg.POLL_INTERVAL_MINUTES * 60)
                logger.info("Email intake poller: starting scheduled cycle...")
                await loop.run_in_executor(None, run_cycle)
        except Exception as e:
            logger.error(f"Email intake poller failed to start: {e}. Check Gmail credentials in email_intake/")

    asyncio.create_task(_email_intake_loop())
    logger.info("Email intake scheduler started (Gmail OAuth poller)")

    # MAF agentic layer — durable checkpoint store + no-Celery follow-up sweeper
    try:
        from agents_maf.storage import setup_storage
        await setup_storage()
        logger.info("✅ MAF PostgresCheckpointStorage ready")
    except Exception as e:
        logger.error(f"MAF checkpoint storage init failed: {e}")

    try:
        from agents_maf.collections.scheduler import followup_sweeper
        app.state.followup_sweeper = asyncio.create_task(followup_sweeper())
        logger.info("Collections follow-up sweeper started (in-process, no Celery)")
    except Exception as e:
        logger.error(f"Follow-up sweeper failed to start: {e}")

    try:
        from agents_maf.monitor import proactive_monitor
        app.state.proactive_monitor = asyncio.create_task(proactive_monitor())
        logger.info("Proactive agent monitor + handoff processor started")
    except Exception as e:
        logger.error(f"Proactive monitor failed to start: {e}")

    logger.info("All systems initialized. O2C Agent v2.0 ready.")
    yield
    # Shutdown
    sweeper = getattr(app.state, "followup_sweeper", None)
    if sweeper is not None:
        sweeper.cancel()
    monitor = getattr(app.state, "proactive_monitor", None)
    if monitor is not None:
        monitor.cancel()
    try:
        from agents_maf.storage import close_storage
        await close_storage()
    except Exception:
        pass
    await close_pool()
    logger.info("O2C Agent v2.0 shut down cleanly.")


app = FastAPI(
    title="O2C Agent v2.0 API",
    description="Order-to-Cash Agentic AI System — MAQ Software",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    redirect_slashes=False,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Routers ──────────────────────────────────────────────────────────
app.include_router(auth_router,        prefix="/api/auth",           tags=["Auth"])
app.include_router(orders_router,      prefix="/api/orders",         tags=["Orders"])
app.include_router(invoices_router,    prefix="/api/invoices",       tags=["Invoices"])
app.include_router(ar_router,          prefix="/api/ar-ledger",      tags=["AR Ledger"])
app.include_router(fraud_router,       prefix="/api/fraud",          tags=["Fraud"])
app.include_router(hitl_router,        prefix="/api/hitl",           tags=["HITL"])
app.include_router(collections_router, prefix="/api/collections",    tags=["Collections"])
app.include_router(agents_router,       prefix="/api/agents",         tags=["Agents"])
app.include_router(disputes_router,    prefix="/api/disputes",       tags=["Disputes"])
app.include_router(cash_app_router,    prefix="/api/cash-app",       tags=["Cash Application"])
app.include_router(analytics_router,  prefix="/api/analytics",      tags=["Analytics"])
app.include_router(ml_router,          prefix="/api/ml",             tags=["ML Monitor"])
app.include_router(portal_router,      prefix="/api/portal",         tags=["Customer Portal (Legacy)"])
app.include_router(compliance_router,  prefix="/api/compliance",     tags=["Compliance"])
app.include_router(customer_portal_router, prefix="/api/customer-portal", tags=["Customer Portal"])
app.include_router(customers_router,   prefix="/api/customers",      tags=["Customers"])
app.include_router(customer_disputes_router, prefix="/api/customer-portal/disputes", tags=["Customer Portal Disputes"])
app.include_router(portal_disputes_router, prefix="/api/portal-disputes", tags=["Portal Disputes"])
app.include_router(credit_memos_router, prefix="/api/credit-memos",  tags=["Credit Memos"])
app.include_router(inventory_router,    prefix="/api/inventory",      tags=["Inventory"])
app.include_router(purchase_orders_router, prefix="/api/purchase-orders", tags=["Purchase Orders"])
app.include_router(products_router,        prefix="/api/products",        tags=["Products"])

# ── WebSocket — Real-time pipeline events ────────────────────────────────
@app.websocket("/ws/pipeline")
async def pipeline_websocket(websocket: WebSocket):
    """Real-time O2C pipeline events for the dashboard."""
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Acknowledge ping
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ── Health check ─────────────────────────────────────────────────────────
@app.get("/api/health", tags=["Health"])
async def health():
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"
    return {
        "status": "ok",
        "version": "2.0.0",
        "database": db_status,
        "ws_connections": len(ws_manager.active_connections),
    }


# ── Global broadcast helper (used by agents) ────────────────────────────
async def broadcast_event(event_type: str, data: dict):
    """Broadcast a pipeline event to all WebSocket clients."""
    await ws_manager.broadcast({"type": event_type, "data": data, "timestamp": asyncio.get_event_loop().time()})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.app_host, port=settings.app_port, reload=True, log_level="info")
