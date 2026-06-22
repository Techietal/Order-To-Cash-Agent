"""
O2C Agent v2.0 — PostgreSQL Database Layer
11-table schema with asyncpg async driver and Row-Level Security.
"""

import asyncpg
import logging
import uuid
from typing import Optional
from config import settings
from passwords import hash_password

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if settings.database_url:
            # Use full DSN (e.g. Neon cloud URL with sslmode already encoded)
            _pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=2,
                max_size=10,
                command_timeout=60,
            )
        else:
            ssl_value = settings.postgres_ssl if settings.postgres_ssl else None
            _pool = await asyncpg.create_pool(
                host=settings.postgres_host,
                port=settings.postgres_port,
                database=settings.postgres_db,
                user=settings.postgres_user,
                password=settings.postgres_password,
                min_size=2,
                max_size=10,
                command_timeout=60,
                ssl=ssl_value,
            )
        logger.info("✅ PostgreSQL connection pool created")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ══════════════════════════════════════════════════
# SCHEMA — 11 TABLES
# ══════════════════════════════════════════════════
SCHEMA_SQL = """
-- STAFF USERS
CREATE TABLE IF NOT EXISTS staff_users (
    user_id       UUID PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- CUSTOMERS
CREATE TABLE IF NOT EXISTS customers (
    customer_id       VARCHAR(20) PRIMARY KEY,
    company_name      TEXT NOT NULL,
    contact_name      TEXT,
    email             TEXT,
    phone             TEXT,
    billing_address   TEXT,
    shipping_address  TEXT,
    city              TEXT,
    state             TEXT,
    pincode           VARCHAR(10),
    gstin             VARCHAR(15),
    industry          TEXT,
    credit_tier       CHAR(1) CHECK (credit_tier IN ('A','B','C','D')),
    credit_limit_inr  NUMERIC(15,2) DEFAULT 0,
    payment_terms_days INT DEFAULT 30,
    avg_dso_days      INT DEFAULT 30,
    missed_payments_12m INT DEFAULT 0,
    open_ar_balance_inr NUMERIC(15,2) DEFAULT 0,
    account_age_months  INT DEFAULT 0,
    is_active         BOOLEAN DEFAULT TRUE,
    portal_active     BOOLEAN DEFAULT TRUE,
    password_hash     TEXT DEFAULT '',
    kyc_id            TEXT DEFAULT '',
    risk_flag         BOOLEAN DEFAULT FALSE,
    embedding_id      TEXT,
    notes             TEXT DEFAULT '',
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- PRODUCTS / SKUs
CREATE TABLE IF NOT EXISTS products (
    sku_id            VARCHAR(20) PRIMARY KEY,
    product_name      TEXT NOT NULL,
    category          TEXT,
    unit_of_measure   TEXT DEFAULT 'Units',
    base_price_inr    NUMERIC(12,2) NOT NULL,
    gst_rate_pct      NUMERIC(5,2) DEFAULT 18,
    hsn_code          VARCHAR(20),
    stock_on_hand     INT DEFAULT 0,
    reorder_level     INT DEFAULT 10,
    safety_stock      INT DEFAULT 5,
    lead_time_days    INT DEFAULT 7,
    warehouse_location TEXT,
    min_order_qty     INT DEFAULT 1,
    is_active         BOOLEAN DEFAULT TRUE,
    supplier_id       TEXT,
    weight_kg         NUMERIC(8,3),
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ORDERS
CREATE TABLE IF NOT EXISTS orders (
    order_id              VARCHAR(30) PRIMARY KEY,
    customer_id           VARCHAR(20) REFERENCES customers(customer_id),
    sku_id                VARCHAR(20) REFERENCES products(sku_id),
    quantity              INT NOT NULL,
    unit_price_inr        NUMERIC(12,2) NOT NULL,
    subtotal_inr          NUMERIC(15,2) NOT NULL,
    gst_pct               NUMERIC(5,2) DEFAULT 18,
    gst_amount_inr        NUMERIC(12,2) DEFAULT 0,
    total_amount_inr      NUMERIC(15,2) NOT NULL,
    order_date            TIMESTAMPTZ DEFAULT NOW(),
    requested_delivery_date TIMESTAMPTZ,
    delivery_address      TEXT,
    channel               TEXT DEFAULT 'api',
    po_reference          TEXT,
    status                TEXT DEFAULT 'pending_credit',
    credit_check_status   TEXT DEFAULT 'pending',
    fraud_score           NUMERIC(6,4) DEFAULT 0,
    isolation_forest_score NUMERIC(6,4) DEFAULT 0,
    credit_tier_at_order  CHAR(1),
    agent_notes           TEXT DEFAULT '',
    policy_engine_flags   JSONB DEFAULT '[]',
    hitl_required         BOOLEAN DEFAULT FALSE,
    hitl_resolved_by      TEXT DEFAULT '',
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

-- INVOICES
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id        VARCHAR(20) PRIMARY KEY,
    order_id          VARCHAR(30) REFERENCES orders(order_id),
    customer_id       VARCHAR(20) REFERENCES customers(customer_id),
    invoice_date      TIMESTAMPTZ DEFAULT NOW(),
    due_date          TIMESTAMPTZ NOT NULL,
    subtotal_inr      NUMERIC(15,2) NOT NULL,
    gst_amount_inr    NUMERIC(12,2) DEFAULT 0,
    total_amount_inr  NUMERIC(15,2) NOT NULL,
    amount_paid_inr   NUMERIC(15,2) DEFAULT 0,
    balance_due_inr   NUMERIC(15,2) DEFAULT 0,
    payment_status    TEXT DEFAULT 'pending',
    days_overdue      INT DEFAULT 0,
    payment_terms_days INT DEFAULT 30,
    invoice_pdf_path  TEXT,
    sent_at           TIMESTAMPTZ,
    reminder_count    INT DEFAULT 0,
    created_by_agent  TEXT DEFAULT 'agent_06_invoice',
    po_reference      TEXT,
    bank_ref_number   TEXT DEFAULT '',
    credit_note_id    TEXT DEFAULT '',
    payment_token     VARCHAR(12) UNIQUE,     -- 12-digit secret token; required to authorize payment
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- PAYMENTS
CREATE TABLE IF NOT EXISTS payments (
    payment_id        VARCHAR(30) PRIMARY KEY,
    invoice_id        VARCHAR(20) REFERENCES invoices(invoice_id),
    amount_inr        NUMERIC(15,2) NOT NULL,
    payment_date      TIMESTAMPTZ DEFAULT NOW(),
    payment_method    TEXT DEFAULT 'bank_transfer',
    bank_ref_number   TEXT,
    status            TEXT DEFAULT 'processed',
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- AR LEDGER
CREATE TABLE IF NOT EXISTS ar_ledger (
    ar_id                   VARCHAR(30) PRIMARY KEY,
    customer_id             VARCHAR(20) REFERENCES customers(customer_id),
    invoice_id              VARCHAR(20) REFERENCES invoices(invoice_id),
    order_id                VARCHAR(30) REFERENCES orders(order_id),
    transaction_type        TEXT DEFAULT 'invoice',
    transaction_date        TIMESTAMPTZ DEFAULT NOW(),
    due_date                TIMESTAMPTZ,
    amount_inr              NUMERIC(15,2) NOT NULL,
    outstanding_balance_inr NUMERIC(15,2) DEFAULT 0,
    aging_bucket            TEXT DEFAULT '0-30',
    payment_status          TEXT DEFAULT 'pending',
    days_overdue            INT DEFAULT 0,
    xgboost_delay_score     NUMERIC(6,4) DEFAULT 0,
    predicted_pay_date      TIMESTAMPTZ,
    collection_priority     TEXT DEFAULT 'MEDIUM',
    promise_to_pay_date     TIMESTAMPTZ,
    promise_to_pay_amount   NUMERIC(15,2),
    last_action             TEXT DEFAULT 'invoice_sent',
    last_action_date        TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- FRAUD RECORDS
CREATE TABLE IF NOT EXISTS fraud_records (
    fraud_id                VARCHAR(20) PRIMARY KEY,
    order_id                VARCHAR(30) REFERENCES orders(order_id),
    customer_id             VARCHAR(20) REFERENCES customers(customer_id),
    isolation_forest_score  NUMERIC(6,4),
    anomaly_flag            BOOLEAN DEFAULT FALSE,
    xgboost_fraud_probability NUMERIC(6,4),
    fraud_verdict           TEXT DEFAULT 'PENDING',
    shap_top_feature        TEXT,
    shap_explanation        TEXT,
    hitl_required           BOOLEAN DEFAULT FALSE,
    hitl_decision           TEXT DEFAULT '',
    reviewed_by             TEXT DEFAULT '',
    review_notes            TEXT DEFAULT '',
    order_blocked           BOOLEAN DEFAULT FALSE,
    detected_at             TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at             TIMESTAMPTZ,
    processed_by_agent      TEXT DEFAULT 'agent_03_fraud_detection',
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- CREDIT DECISIONS
CREATE TABLE IF NOT EXISTS credit_decisions (
    decision_id               VARCHAR(20) PRIMARY KEY,
    order_id                  VARCHAR(30) REFERENCES orders(order_id),
    customer_id               VARCHAR(20) REFERENCES customers(customer_id),
    credit_tier               CHAR(1),
    credit_limit_inr          NUMERIC(15,2),
    open_ar_balance_inr       NUMERIC(15,2),
    order_amount_inr          NUMERIC(15,2),
    xgboost_credit_score      NUMERIC(6,4),
    credit_risk_class         TEXT,
    pd_score                  NUMERIC(6,4),
    recommended_credit_limit_inr NUMERIC(15,2),
    decision                  TEXT DEFAULT 'pending',
    decision_reason           TEXT,
    ecoa_audit_logged         BOOLEAN DEFAULT FALSE,
    hitl_required             BOOLEAN DEFAULT FALSE,
    hitl_override             BOOLEAN DEFAULT FALSE,
    policy_engine_flags       JSONB DEFAULT '[]',
    decided_at                TIMESTAMPTZ DEFAULT NOW(),
    processed_by_agent        TEXT DEFAULT 'agent_02_credit_check',
    created_at                TIMESTAMPTZ DEFAULT NOW()
);

-- DUNNING LOG
CREATE TABLE IF NOT EXISTS dunning_log (
    dunning_id            VARCHAR(20) PRIMARY KEY,
    customer_id           VARCHAR(20) REFERENCES customers(customer_id),
    invoice_id            VARCHAR(20) REFERENCES invoices(invoice_id),
    dunning_level         TEXT,
    channel               TEXT DEFAULT 'email',
    message_subject       TEXT,
    message_body_preview  TEXT,
    sent_at               TIMESTAMPTZ DEFAULT NOW(),
    opened                BOOLEAN DEFAULT FALSE,
    responded             BOOLEAN DEFAULT FALSE,
    promise_to_pay        BOOLEAN DEFAULT FALSE,
    promise_date          TIMESTAMPTZ,
    promise_amount_inr    NUMERIC(15,2),
    promise_kept          BOOLEAN,
    groq_generated        BOOLEAN DEFAULT TRUE,
    account_segment       TEXT,
    collection_priority_score NUMERIC(6,4),
    processed_by_agent    TEXT DEFAULT 'agent_08_collections',
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

-- ANOMALY ALERTS
CREATE TABLE IF NOT EXISTS anomaly_alerts (
    alert_id              VARCHAR(20) PRIMARY KEY,
    alert_type            TEXT NOT NULL,
    severity              TEXT DEFAULT 'MEDIUM',
    customer_id           VARCHAR(20) REFERENCES customers(customer_id),
    order_id              VARCHAR(30) REFERENCES orders(order_id),
    isolation_forest_score NUMERIC(6,4),
    sliding_window_events INT,
    groq_alert_summary    TEXT,
    recommended_action    TEXT,
    hitl_gate             TEXT DEFAULT 'HITL_GATE_5',
    hitl_required         BOOLEAN DEFAULT TRUE,
    reviewed              BOOLEAN DEFAULT FALSE,
    reviewed_by           TEXT DEFAULT '',
    resolution            TEXT DEFAULT '',
    detected_at           TIMESTAMPTZ DEFAULT NOW(),
    processed_by_agent    TEXT DEFAULT 'agent_11_anomaly_watchdog',
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

-- AUDIT LOG (append-only, SOX compliant — RLS prevents UPDATE/DELETE)
CREATE TABLE IF NOT EXISTS audit_log (
    log_id            BIGSERIAL PRIMARY KEY,
    event_type        TEXT NOT NULL,
    agent_name        TEXT,
    user_id           TEXT,
    customer_id       TEXT,
    order_id          TEXT,
    invoice_id        TEXT,
    action            TEXT NOT NULL,
    details           JSONB DEFAULT '{}',
    policy_rule_id    TEXT,
    outcome           TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Append-only enforcement via RLS
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_log_insert_only ON audit_log;
CREATE POLICY audit_log_insert_only ON audit_log FOR INSERT WITH CHECK (TRUE);

-- PROMISE TO PAY
CREATE TABLE IF NOT EXISTS promise_to_pay (
    ptp_id            VARCHAR(20) PRIMARY KEY,
    customer_id       VARCHAR(20) REFERENCES customers(customer_id),
    invoice_id        VARCHAR(20) REFERENCES invoices(invoice_id),
    ar_id             VARCHAR(30) REFERENCES ar_ledger(ar_id),
    promise_date      TIMESTAMPTZ NOT NULL,
    promise_amount_inr NUMERIC(15,2) NOT NULL,
    channel           TEXT DEFAULT 'email',
    status            TEXT DEFAULT 'pending',
    kept              BOOLEAN,
    actual_pay_date   TIMESTAMPTZ,
    actual_amount_inr NUMERIC(15,2),
    logged_by_agent   TEXT DEFAULT 'agent_08_collections',
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- INDEXES for performance
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(payment_status);
CREATE INDEX IF NOT EXISTS idx_ar_customer ON ar_ledger(customer_id);
CREATE INDEX IF NOT EXISTS idx_ar_overdue ON ar_ledger(days_overdue);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_dunning_customer ON dunning_log(customer_id);
CREATE INDEX IF NOT EXISTS idx_staff_users_active ON staff_users(is_active);

-- CUSTOMER KYC REQUESTS (New customer onboarding — HITL review)
CREATE TABLE IF NOT EXISTS customer_kyc_requests (
    kyc_id           VARCHAR(30) PRIMARY KEY,
    company_name     TEXT NOT NULL,
    contact_name     TEXT NOT NULL,
    email            TEXT NOT NULL,
    phone            TEXT,
    gstin            VARCHAR(15),
    pan_number       VARCHAR(10),
    business_type    TEXT,
    state            TEXT,
    city             TEXT,
    address          TEXT,
    annual_turnover  TEXT DEFAULT '',
    status           TEXT DEFAULT 'pending',
    reviewer         TEXT DEFAULT '',
    review_notes     TEXT DEFAULT '',
    rejection_reason TEXT DEFAULT '',
    submitted_at     TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_kyc_email ON customer_kyc_requests(email);
CREATE INDEX IF NOT EXISTS idx_kyc_status ON customer_kyc_requests(status);

-- CUSTOMER PORTAL DISPUTES (human escalation chat with AI admin summary)
CREATE TABLE IF NOT EXISTS portal_disputes (
    dispute_id              VARCHAR(40) PRIMARY KEY,
    customer_id             VARCHAR(20) REFERENCES customers(customer_id),
    invoice_id              VARCHAR(20) REFERENCES invoices(invoice_id),
    order_id                VARCHAR(20) REFERENCES orders(order_id),
    dispute_type            TEXT DEFAULT 'general',
    subject                 TEXT NOT NULL,
    ai_summary              TEXT DEFAULT '',
    ai_summary_status       TEXT DEFAULT 'pending',
    ai_summary_model        TEXT DEFAULT '',
    ai_summary_generated_at TIMESTAMPTZ,
    status                  TEXT DEFAULT 'pending_admin',
    next_actor              TEXT DEFAULT 'admin',
    proof_count             INT DEFAULT 0,
    source                  TEXT DEFAULT 'portal',
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    withdrawn_at            TIMESTAMPTZ,
    withdrawn_reason        TEXT DEFAULT '',
    closed_at               TIMESTAMPTZ,
    decided_by              TEXT DEFAULT '',
    decision_note           TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS portal_dispute_messages (
    message_id      VARCHAR(50) PRIMARY KEY,
    dispute_id      VARCHAR(40) REFERENCES portal_disputes(dispute_id) ON DELETE CASCADE,
    sender_type     TEXT NOT NULL CHECK (sender_type IN ('customer','admin','system')),
    sender_id       TEXT,
    body            TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portal_dispute_attachments (
    attachment_id   VARCHAR(50) PRIMARY KEY,
    dispute_id      VARCHAR(40) REFERENCES portal_disputes(dispute_id) ON DELETE CASCADE,
    message_id      VARCHAR(50) REFERENCES portal_dispute_messages(message_id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    content_type    TEXT,
    file_path       TEXT NOT NULL,
    size_bytes      INT DEFAULT 0,
    uploaded_by     TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_portal_disputes_customer ON portal_disputes(customer_id);
CREATE INDEX IF NOT EXISTS idx_portal_disputes_status ON portal_disputes(status);
CREATE INDEX IF NOT EXISTS idx_portal_disputes_next_actor ON portal_disputes(next_actor);
CREATE INDEX IF NOT EXISTS idx_portal_messages_dispute ON portal_dispute_messages(dispute_id);
CREATE INDEX IF NOT EXISTS idx_portal_attachments_dispute ON portal_dispute_attachments(dispute_id);

-- Add portal columns to customers if they don't exist
ALTER TABLE customers ADD COLUMN IF NOT EXISTS portal_active BOOLEAN DEFAULT TRUE;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS password_hash TEXT DEFAULT '';
ALTER TABLE customers ADD COLUMN IF NOT EXISTS kyc_id TEXT DEFAULT '';

-- Add source column to portal_disputes if it doesn't exist
ALTER TABLE portal_disputes ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'portal';

-- PENDING ORDER EMAILS (unregistered sender — held until registration complete)
CREATE TABLE IF NOT EXISTS pending_order_emails (
    id               SERIAL PRIMARY KEY,
    invite_token     TEXT UNIQUE NOT NULL,
    email_from       TEXT NOT NULL,
    subject          TEXT DEFAULT '',
    email_text       TEXT NOT NULL,
    status           TEXT DEFAULT 'awaiting_registration',  -- awaiting_registration | processed | expired
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    processed_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_pending_orders_email ON pending_order_emails(email_from);
CREATE INDEX IF NOT EXISTS idx_pending_orders_token ON pending_order_emails(invite_token);

-- Add payment_token to invoices if upgrading an existing schema
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_token VARCHAR(12) UNIQUE;

-- ── Audit log human-identity extensions (Section 1 RBAC) ───────────────────
-- actor_type: 'ai_agent' | 'human' — lets you filter to "only what people did"
-- actor_username: JWT sub claim of the logged-in staff member (NULL for AI agents)
-- actor_role: JWT role claim of the logged-in staff member (NULL for AI agents)
-- previous_value: JSONB snapshot of the entity BEFORE the human action
-- new_value: JSONB snapshot of the entity AFTER the human action
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor_type     TEXT DEFAULT 'ai_agent';
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor_username TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor_role     TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS previous_value JSONB;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS new_value      JSONB;

CREATE INDEX IF NOT EXISTS idx_audit_log_actor_type ON audit_log(actor_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor_user ON audit_log(actor_username);

-- ── Credit Memos (Section 2 + Section 5 extension) ─────────────────────────
-- Unified balance-adjustment ledger: covers dispute credits, manual payments,
-- customer portal payments, and any other source that reduces an invoice balance.
-- source: 'dispute_resolution' | 'ar_ledger_manual' | 'customer_portal' | 'hitl_payment'
-- payment_ref: optional external ref (wire transfer ID, cheque no., etc.)
CREATE TABLE IF NOT EXISTS credit_memos (
    memo_id            VARCHAR(30) PRIMARY KEY,
    order_id           VARCHAR(30),
    invoice_id         VARCHAR(20) REFERENCES invoices(invoice_id),
    customer_id        VARCHAR(20) REFERENCES customers(customer_id),
    dispute_id         VARCHAR(20),
    amount_inr         NUMERIC(15,2) NOT NULL,
    reason             TEXT NOT NULL,
    approved_by        TEXT NOT NULL,
    approved_by_role   TEXT NOT NULL,
    balance_before_inr NUMERIC(15,2) NOT NULL,
    balance_after_inr  NUMERIC(15,2) NOT NULL,
    source             TEXT NOT NULL DEFAULT 'dispute_resolution',
    payment_ref        TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
-- Backfill source column for rows created before this migration
ALTER TABLE credit_memos ADD COLUMN IF NOT EXISTS source       TEXT NOT NULL DEFAULT 'dispute_resolution';
ALTER TABLE credit_memos ADD COLUMN IF NOT EXISTS payment_ref  TEXT;
ALTER TABLE credit_memos ALTER COLUMN dispute_id TYPE TEXT;
CREATE INDEX IF NOT EXISTS idx_credit_memos_customer  ON credit_memos(customer_id);
CREATE INDEX IF NOT EXISTS idx_credit_memos_invoice   ON credit_memos(invoice_id);
CREATE INDEX IF NOT EXISTS idx_credit_memos_order     ON credit_memos(order_id);
CREATE INDEX IF NOT EXISTS idx_credit_memos_dispute   ON credit_memos(dispute_id);
CREATE INDEX IF NOT EXISTS idx_credit_memos_created   ON credit_memos(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_credit_memos_source    ON credit_memos(source);

-- ══════════════════════════════════════════════════════════════════════════════
-- INVENTORY PHASE 1 — Database Foundation
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Extend products table with inventory tracking columns ─────────────────────
-- reserved_stock: units locked by approved/pending orders not yet shipped
-- incoming_stock: units on open purchase orders, not yet received
-- reorder_qty:    standard replenishment batch size for this SKU
-- available_stock is NOT stored; compute as: stock_on_hand - reserved_stock
ALTER TABLE products ADD COLUMN IF NOT EXISTS reserved_stock  INT NOT NULL DEFAULT 0;
ALTER TABLE products ADD COLUMN IF NOT EXISTS incoming_stock  INT NOT NULL DEFAULT 0;
ALTER TABLE products ADD COLUMN IF NOT EXISTS reorder_qty     INT NOT NULL DEFAULT 0;

-- Enforce non-negative stock floors (idempotent — ADD CONSTRAINT IF NOT EXISTS
-- is not supported in older PG, so we use DO $$ ... $$ blocks)
DO $$ BEGIN
    ALTER TABLE products ADD CONSTRAINT chk_products_stock_on_hand_nonneg
        CHECK (stock_on_hand >= 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE products ADD CONSTRAINT chk_products_reserved_stock_nonneg
        CHECK (reserved_stock >= 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── INVENTORY TRANSACTIONS ─────────────────────────────────────────────────────
-- Append-only ledger of every stock movement.
-- Canonical txn_type values (enforced by inventory_service.py — do NOT use ad-hoc strings):
--   STOCK_ADJUSTMENT          — manual correction or opening-balance entry
--   ORDER_RESERVATION         — units reserved when an order is approved
--   BACKORDER_CREATED         — units moved to backorder when stock is insufficient
--   FULFILLMENT_DEDUCTION     — stock_on_hand decremented when order ships
--   ORDER_RELEASE_CANCELLED   — reservation released on order cancel/reject
--   PURCHASE_RECEIPT          — incoming_stock decremented + stock_on_hand incremented on PO receipt
--   PURCHASE_ORDER_CONFIRMED  — incoming_stock incremented when supplier confirms PO
--   DAMAGED_INVENTORY         — negative STOCK_ADJUSTMENT for damaged/written-off units
-- field_affected:    'stock_on_hand' | 'reserved_stock' | 'incoming_stock'
-- quantity_delta:    positive = stock increases, negative = stock decreases
-- balance_after:     snapshot of the affected field after this transaction
CREATE TABLE IF NOT EXISTS inventory_transactions (
    txn_id              VARCHAR(30) PRIMARY KEY,
    sku_id              VARCHAR(20) NOT NULL REFERENCES products(sku_id),
    txn_type            TEXT NOT NULL,
    quantity_delta      INT NOT NULL,
    field_affected      TEXT NOT NULL,
    balance_after       INT NOT NULL,
    order_id            VARCHAR(30) REFERENCES orders(order_id),
    purchase_order_id   VARCHAR(30),
    reason              TEXT NOT NULL DEFAULT '',
    metadata            JSONB NOT NULL DEFAULT '{}',
    performed_by        TEXT NOT NULL DEFAULT 'system',
    actor_type          TEXT NOT NULL DEFAULT 'system',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inv_txn_sku_time   ON inventory_transactions(sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inv_txn_order      ON inventory_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_inv_txn_po         ON inventory_transactions(purchase_order_id);

-- ── INVENTORY RESERVATIONS ─────────────────────────────────────────────────────
-- One row per order-SKU pair; tracks how many units are reserved vs back-ordered.
-- status: 'active' | 'released' | 'fulfilled' | 'backordered' | 'cancelled'
CREATE TABLE IF NOT EXISTS inventory_reservations (
    reservation_id              VARCHAR(30) PRIMARY KEY,
    order_id                    VARCHAR(30) NOT NULL REFERENCES orders(order_id),
    sku_id                      VARCHAR(20) NOT NULL REFERENCES products(sku_id),
    quantity_requested          INT NOT NULL,
    quantity_reserved           INT NOT NULL DEFAULT 0,
    quantity_backordered        INT NOT NULL DEFAULT 0,
    status                      TEXT NOT NULL DEFAULT 'active',
    expected_availability_date  TIMESTAMPTZ,
    reserved_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    released_at                 TIMESTAMPTZ,
    fulfilled_at                TIMESTAMPTZ,
    metadata                    JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_inv_res_order      ON inventory_reservations(order_id);
CREATE INDEX IF NOT EXISTS idx_inv_res_sku_status ON inventory_reservations(sku_id, status);

-- ── PURCHASE ORDERS ────────────────────────────────────────────────────────────
-- Replenishment purchase orders raised to suppliers.
-- status: 'draft' | 'confirmed' | 'in_transit' | 'received' | 'cancelled'
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id                 VARCHAR(30) PRIMARY KEY,
    supplier_id           TEXT,
    status                TEXT NOT NULL DEFAULT 'draft',
    expected_arrival_date TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at          TIMESTAMPTZ,
    received_at           TIMESTAMPTZ,
    created_by            TEXT NOT NULL DEFAULT 'system',
    metadata              JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_po_status_arrival ON purchase_orders(status, expected_arrival_date);

-- ── PURCHASE ORDER LINE ITEMS ──────────────────────────────────────────────────
-- One row per SKU per PO. Unique constraint prevents duplicate SKU lines on a PO.
-- line_status: 'open' | 'partial' | 'received' | 'cancelled'
CREATE TABLE IF NOT EXISTS purchase_order_items (
    po_item_id          VARCHAR(30) PRIMARY KEY,
    po_id               VARCHAR(30) NOT NULL REFERENCES purchase_orders(po_id),
    sku_id              VARCHAR(20) NOT NULL REFERENCES products(sku_id),
    quantity_ordered    INT NOT NULL,
    quantity_received   INT NOT NULL DEFAULT 0,
    unit_cost_inr       NUMERIC(12,2) NOT NULL DEFAULT 0,
    line_status         TEXT NOT NULL DEFAULT 'open',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_po_item_sku UNIQUE (po_id, sku_id)
);

CREATE INDEX IF NOT EXISTS idx_po_items_po   ON purchase_order_items(po_id);
CREATE INDEX IF NOT EXISTS idx_po_items_sku  ON purchase_order_items(sku_id);

-- ── INVENTORY FORECAST SNAPSHOTS ──────────────────────────────────────────────
-- Daily demand forecasts per SKU generated by the Prophet model.
-- Unique per (sku_id, forecast_date) — re-running the model upserts, not duplicates.
-- model_version tracks which trained model produced the snapshot.
CREATE TABLE IF NOT EXISTS inventory_forecast_snapshot (
    snapshot_id              VARCHAR(30) PRIMARY KEY,
    sku_id                   VARCHAR(20) NOT NULL REFERENCES products(sku_id),
    forecast_date            DATE NOT NULL,
    predicted_daily_demand   NUMERIC(10,2) NOT NULL,
    predicted_demand_lower   NUMERIC(10,2),
    predicted_demand_upper   NUMERIC(10,2),
    model_version            TEXT NOT NULL DEFAULT 'prophet_trained',
    generated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_forecast_sku_date UNIQUE (sku_id, forecast_date)
);

CREATE INDEX IF NOT EXISTS idx_forecast_sku_date ON inventory_forecast_snapshot(sku_id, forecast_date);

-- ── PRODUCT STOCK SUMMARY VIEW ─────────────────────────────────────────────────
-- Convenience read-only view for dashboards and API endpoints.
-- available_stock = stock_on_hand - reserved_stock (never stored, always computed).
-- Recreate-or-replace so schema changes to products are reflected automatically.
CREATE OR REPLACE VIEW product_stock_summary AS
SELECT
    p.sku_id,
    p.product_name,
    p.category,
    p.unit_of_measure,
    p.base_price_inr,
    p.stock_on_hand,
    p.reserved_stock,
    (p.stock_on_hand - p.reserved_stock) AS available_stock,
    p.incoming_stock,
    p.reorder_level,
    p.safety_stock,
    p.lead_time_days,
    p.reorder_qty,
    p.is_active
FROM products p;

-- ══════════════════════════════════════════════════════════════════════════════
-- AGENTIC LAYER — app-level agent run registry
-- (checkpoint bytes live in maf_checkpoints, created by PostgresCheckpointStorage)
-- ══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id         TEXT NOT NULL,
    agent_name        TEXT NOT NULL,
    invoice_id        VARCHAR(20),
    customer_id       VARCHAR(20),
    status            TEXT NOT NULL DEFAULT 'running',
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paused_at         TIMESTAMPTZ,
    resumed_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    last_summary      TEXT DEFAULT '',
    hitl_payload      JSONB DEFAULT '{}',
    hitl_decision     JSONB DEFAULT '{}',
    error             TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_thread  ON agent_runs(thread_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status  ON agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_invoice ON agent_runs(invoice_id);

-- Forward-compat: checkpoint id set when a run is paused for HITL (idempotent for existing DBs)
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS checkpoint_id TEXT;

-- Generic entity reference so the run registry is uniform across all agents
-- (collections uses invoice_id; disputes/cash/credit/kyc use entity_id + entity_type)
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS entity_id   TEXT;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS entity_type TEXT;

-- No-Celery delayed follow-up queue (swept by the FastAPI lifespan sweeper)
CREATE TABLE IF NOT EXISTS followups (
    followup_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id  VARCHAR(20) NOT NULL,
    due_at      TIMESTAMPTZ NOT NULL,
    reason      TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending|done|cancelled
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_followups_due ON followups(status, due_at);

-- Agent-to-agent handoff queue (chaining). One agent records a handoff; the
-- monitor/processor picks it up and runs the target agent. depth guards loops.
CREATE TABLE IF NOT EXISTS agent_handoffs (
    handoff_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_agent  TEXT NOT NULL,
    to_agent    TEXT NOT NULL,                      -- collections|disputes|cash|credit|kyc
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    reason      TEXT DEFAULT '',
    payload     JSONB DEFAULT '{}',
    depth       INT NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'pending',    -- pending|done|failed|skipped
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_status ON agent_handoffs(status, created_at);

"""


DEV_STAFF_USERS = [
    ("admin", "admin123", "admin", "O2C Admin"),
    ("analyst", "ca123", "collections_analyst", "Collections Analyst"),
    ("controller", "ctrl123", "controller", "Finance Controller"),
    ("dispute_manager", "dm123", "dispute_manager", "Disputes Manager"),
    ("collections_analyst", "ca123", "collections_analyst", "Collections Analyst"),
    ("inventory_manager", "inv123", "inventory_manager", "Inventory Manager"),
]


async def seed_development_staff_users(conn):
    """Create local demo staff users only in development environments."""
    if settings.app_env.lower() != "development":
        return

    for username, password, role, display_name in DEV_STAFF_USERS:
        await conn.execute(
            """INSERT INTO staff_users
               (user_id, username, password_hash, role, display_name, is_active)
               VALUES ($1, $2, $3, $4, $5, TRUE)
               ON CONFLICT (username) DO NOTHING""",
            uuid.uuid5(uuid.NAMESPACE_DNS, f"o2c-staff-{username}"),
            username,
            hash_password(password),
            role,
            display_name,
        )
    logger.info("Development staff seed users ensured")



async def init_schema():
    """Create all tables, indexes, views, and constraints.

    Executes SCHEMA_SQL as a single string so that dollar-quoted DO $$ blocks
    (used for idempotent constraint additions) are preserved intact.
    asyncpg supports multi-statement strings in execute() for plain SQL.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(SCHEMA_SQL)
        except Exception as e:
            logger.warning(f"Schema init warning (some statements may already exist): {e}")
        await seed_development_staff_users(conn)
    logger.info("✅ PostgreSQL schema initialized — all tables ready")


async def get_db():
    """FastAPI dependency — yields a DB connection from the pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
