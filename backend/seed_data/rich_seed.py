"""
O2C Agent v2.0 — Rich Seed Data (v3 — Comprehensive 4-Customer Rewrite)
========================================================================

Customers:
  CUST-0001  tammasatya25@gmail.com   Satya Manufacturing Pvt Ltd
             Tier A | Premium | 36-month account | 1 OVERDUE invoice so it shows in C360
             Scenarios: paid, open/pending, HITL-SOX, OVERDUE

  CUST-0002  kammajhu8@gmail.com      Kamma Enterprises
             Tier C | High-Risk | 18-month account | 4 missed payments | heavy overdue
             Scenarios: paid, FRAUD-block, 2× overdue, rejected, pre-legal dunning

  CUST-0003  kammajhu5@gmail.com      Jhansi Logistics & Co
             Tier B | Standard | 24-month account | 1 missed payment | IF anomaly
             Scenarios: paid, IF-anomaly HITL, overdue+dispute, dunning L1

  CUST-0004  priya.vendor@example.com  Priya Components Ltd
             Tier B | 12-month account | Clean history | portal active
             Scenarios: 2 paid, 1 open pending payment, 1 partial-payment edge case

Key fixes vs v2:
  - account_age_months is now CONSISTENT with invoice history
    (if oldest invoice is 90 days ago, account must be ≥ 90/30 = 3 months old)
  - CUST-0001 has one genuinely overdue invoice (38 days) so Customer-360 AR widget
    shows a real red overdue entry for the premium customer demo
  - CUST-0002 (Kamma) retains the full fraud / collections story with 4 missed payments
  - fraud_records inserted for every order
  - AR balances auto-computed from ar_ledger at end
  - ChromaDB rebuilt after seed (customers re-embedded)
"""
import asyncio
import io
import sys
from datetime import datetime, timedelta, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, '.')
from database.postgres import get_pool, init_schema
from passwords import hash_password

NOW = datetime.now(timezone.utc)


DEFAULT_PWD = hash_password('123456789')


def da(n, h=10, m=0):
    """n days ago at hour h:m"""
    return (NOW - timedelta(days=n)).replace(hour=h, minute=m, second=0, microsecond=0)


def df(n, h=10, m=0):
    """n days from now at hour h:m"""
    return (NOW + timedelta(days=n)).replace(hour=h, minute=m, second=0, microsecond=0)


async def seed():
    print(">> Initializing schema...")
    await init_schema()

    pool = await get_pool()
    async with pool.acquire() as conn:

        # ══════════════════════════════════════════════════════════════════
        print(">> Wiping all tables...")
        # ══════════════════════════════════════════════════════════════════
        for table in [
            "anomaly_alerts", "promise_to_pay", "dunning_log", "credit_memos",
            "credit_decisions", "fraud_records", "ar_ledger",
            "invoices", "orders",
            # inventory (child tables first)
            "inventory_forecast_snapshot",
            "inventory_transactions",
            "inventory_reservations",
            "purchase_order_items",
            "purchase_orders",
            "products", "customers",
            "audit_log", "customer_kyc_requests",
            "portal_dispute_attachments", "portal_dispute_messages",
            "portal_disputes", "pending_order_emails", "payments",
        ]:
            try:
                await conn.execute(f"TRUNCATE TABLE {table} CASCADE;")
                print(f"  OK {table}")
            except Exception as e:
                print(f"  SKIP {table}: {e}")

        # ══════════════════════════════════════════════════════════════════
        print("\n>> Inserting customers...")
        # ══════════════════════════════════════════════════════════════════
        # account_age_months must be >= (oldest_order_days_ago / 30) to be consistent
        # CUST-0001: oldest order 90 days ago → account_age ≥ 3 months → use 36 (3 yr)
        # CUST-0002: oldest order 90 days ago → account_age ≥ 3 months → use 18 (1.5 yr)
        # CUST-0003: oldest order 70 days ago → account_age ≥ 3 months → use 24 (2 yr)
        # CUST-0004: oldest order 60 days ago → account_age ≥ 2 months → use 12 (1 yr)
        await conn.execute("""
            INSERT INTO customers (
                customer_id, company_name, contact_name, email, phone,
                credit_tier, credit_limit_inr, open_ar_balance_inr,
                payment_terms_days, avg_dso_days, missed_payments_12m,
                account_age_months,
                is_active, portal_active, password_hash,
                city, state, gstin, industry
            ) VALUES
            ('CUST-0001','Satya Manufacturing Pvt Ltd','Satya Tamma',
             'tammasatya25@gmail.com','+91 98765 11111',
             'A', 1000000, 0, 30, 32, 0, 36,
             TRUE, TRUE, $1, 'Hyderabad', 'Telangana', '36AABCS1429B1Z1','Manufacturing'),

            ('CUST-0002','Kamma Enterprises','Kamma J',
             'kammajhu8@gmail.com','+91 98765 33333',
             'C', 200000, 0, 60, 75, 4, 18,
             TRUE, TRUE, $1, 'Chennai', 'Tamil Nadu', '33AABCK7890B1Z3','Trading'),

            ('CUST-0003','Jhansi Logistics & Co','Jhansi Kamma',
             'kammajhu5@gmail.com','+91 98765 22222',
             'B', 500000, 0, 45, 42, 1, 24,
             TRUE, TRUE, $1, 'Mumbai', 'Maharashtra', '27AABCJ5678B1Z2','Logistics'),

            ('CUST-0004','Priya Components Ltd','Priya Sharma',
             'priya.vendor@example.com','+91 98765 44444',
             'B', 300000, 0, 30, 30, 0, 12,
             TRUE, TRUE, $1, 'Pune', 'Maharashtra', '27AABCP1234B1Z4','Electronics')
        """, DEFAULT_PWD)
        print("  OK 4 customers")

        # ══════════════════════════════════════════════════════════════════
        print("\n>> Inserting products...")
        # ══════════════════════════════════════════════════════════════════
        # Columns now include inventory Phase-1 fields:
        #   reorder_level  — trigger a replenishment PO when stock_on_hand hits this
        #   safety_stock   — minimum buffer stock; reorder must keep stock above this
        #   lead_time_days — supplier lead time; used in demand forecasting
        #   reorder_qty    — standard batch size for a replenishment PO
        #   reserved_stock / incoming_stock start at 0 (will be updated by seed POs below)
        await conn.execute("""
            INSERT INTO products (
                sku_id, product_name, category, unit_of_measure,
                base_price_inr, gst_rate_pct,
                stock_on_hand, reorder_level, safety_stock, lead_time_days, reorder_qty,
                reserved_stock, incoming_stock,
                is_active
            ) VALUES
            ('SKU-001', 'Industrial Motor v2',       'Machinery',   'Units', 15000, 18,  500,  80,  30,  14, 100,   0,   0, TRUE),
            ('SKU-002', 'Copper Wire Spool 50m',      'Electricals', 'Rolls',  4500, 18,  120, 200,  80,   7, 500,   0,   0, TRUE),
            ('SKU-003', 'Steel Bearings (Pack 100)',  'Components',  'Pack',   8000, 18,  800, 120,  50,  10, 250, 100,   0, TRUE),
            ('SKU-004', 'PLC Control Unit Pro',       'Automation',  'Units', 45000, 18,   12,  25,  10,  21,  50,   5,  50, TRUE),
            ('SKU-005', 'Hydraulic Pump 5HP',         'Machinery',   'Units', 28000, 18,  200,  30,  15,  21,  60,   0,   0, TRUE)
        """)
        print("  OK 5 products (with reorder_level, safety_stock, lead_time_days, reorder_qty)")

        # ══════════════════════════════════════════════════════════════════
        # CUST-0001 — Satya Manufacturing Pvt Ltd
        # Tier A | 36-month account | avg_dso=32 | 0 missed | Credit ₹10L
        # Storyline:
        #   ORD-001-A  90d ago  fulfilled + PAID (₹3.54L)
        #   ORD-002-A  55d ago  fulfilled + PAID (₹2.65L, portal)
        #   ORD-003-A  38d ago  fulfilled + OVERDUE 8d (₹5.31L) — shows in C360 AR widget
        #   ORD-004-A   2d ago  HITL-SOX gate ₹13.3L awaiting FC sign-off
        #   ORD-20260618112754-E seeded for Gmail dispute demo invoice reference
        # ══════════════════════════════════════════════════════════════════
        print("\n>> CUST-0001 — Satya Manufacturing (Tier A, Premium, 1 overdue for demo)")

        # ── ORD-001-A: Large email order, 90 days ago — PAID ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-001-A','CUST-0001','SKU-001',20,15000,300000,18,54000,354000,
                $1,'email','PO-SAT-2025-001','fulfilled','approved',0.04,0.08,
                FALSE,'system',
                'Tier-A. IF=0.08 NORMAL. XGB=4% CLEAR. Auto-approved.','[]')
        """, da(90, 10))

        await conn.execute("""
            INSERT INTO credit_decisions (decision_id,order_id,customer_id,credit_tier,
                credit_limit_inr,open_ar_balance_inr,order_amount_inr,xgboost_credit_score,
                credit_risk_class,pd_score,recommended_credit_limit_inr,decision,decision_reason,ecoa_audit_logged)
            VALUES ('CD-001','ORD-001-A','CUST-0001','A',1000000,0,354000,0.94,'LOW',0.018,
                1200000,'approved','Tier-A, PD 1.8%, ample headroom',TRUE)
        """)

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-001','ORD-001-A','CUST-0001',0.08,0.04,FALSE,'CLEAR',FALSE,
                'Normal daytime email (10:00). Amount within Tier-A range. Account age 36m. Zero missed payments.',
                'established_account')
        """)

        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-001-A','ORD-001-A','CUST-0001',$1,$2,
                300000,54000,354000,354000,0,'paid',0,30,'100001000001')
        """, da(90, 10), da(60))  # due 60d ago, paid on time

        await conn.execute("""
            INSERT INTO payments (payment_id,invoice_id,amount_inr,payment_date,payment_method,status)
            VALUES ('PAY-001-A','INV-001-A',354000,$1,'bank_transfer','processed')
        """, da(58))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,collection_priority,last_action)
            VALUES ('AR-001-A','CUST-0001','INV-001-A','ORD-001-A','invoice',
                $1,$2,354000,0,'0-30','paid',0,'LOW','payment_received')
        """, da(90, 10), da(60))

        # ── ORD-002-A: Portal order 55 days ago — PAID ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-002-A','CUST-0001','SKU-004',5,45000,225000,18,40500,265500,
                $1,'portal','PO-SAT-2025-002','fulfilled','approved',0.03,0.06,
                FALSE,'system','Portal order. PLC bulk. Tier-A auto-approved.','[]')
        """, da(55, 14))

        await conn.execute("""
            INSERT INTO credit_decisions (decision_id,order_id,customer_id,credit_tier,
                credit_limit_inr,open_ar_balance_inr,order_amount_inr,xgboost_credit_score,
                credit_risk_class,pd_score,recommended_credit_limit_inr,decision,decision_reason,ecoa_audit_logged)
            VALUES ('CD-002','ORD-002-A','CUST-0001','A',1000000,0,265500,0.95,'LOW',0.015,
                1200000,'approved','Tier-A, zero AR, PD 1.5%',TRUE)
        """)

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-002','ORD-002-A','CUST-0001',0.06,0.03,FALSE,'CLEAR',FALSE,
                'Portal order 14:00. PLCs normal for manufacturing. Zero AR outstanding. IF=0.06 very low.',
                'zero_ar_outstanding')
        """)

        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-002-A','ORD-002-A','CUST-0001',$1,$2,
                225000,40500,265500,265500,0,'paid',0,30,'100002000002')
        """, da(55, 14), da(25))  # due 25d ago, paid on time

        await conn.execute("""
            INSERT INTO payments (payment_id,invoice_id,amount_inr,payment_date,payment_method,status)
            VALUES ('PAY-002-A','INV-002-A',265500,$1,'neft','processed')
        """, da(24))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,collection_priority,last_action)
            VALUES ('AR-002-A','CUST-0001','INV-002-A','ORD-002-A','invoice',
                $1,$2,265500,0,'0-30','paid',0,'LOW','payment_received')
        """, da(55, 14), da(25))

        # ── ORD-003-A: Email order 38 days ago — OVERDUE 8 days (payment_terms=30) ──
        # This is the KEY scenario: Tier-A premium customer but slightly late this time.
        # Makes Customer 360 AR widget non-trivial and realistic.
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-003-A','CUST-0001','SKU-002',100,4500,450000,18,81000,531000,
                $1,'email','PO-SAT-2025-003','invoiced','approved',0.05,0.09,
                FALSE,'system',
                'Copper wire bulk. GLiNER NER extracted via email. Invoice sent, awaiting payment. 8d overdue.','[]')
        """, da(38, 9))

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-003','ORD-003-A','CUST-0001',0.09,0.05,FALSE,'CLEAR',FALSE,
                'Morning email (09:00). Copper wire bulk typical for manufacturing. Amount within Tier-A limit. IF=0.09 normal.',
                'typical_sku_for_industry')
        """)

        # Invoice: issued 38d ago, due 8d ago (30d terms), now 8 days overdue
        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-003-A','ORD-003-A','CUST-0001',$1,$2,
                450000,81000,531000,0,531000,'overdue',8,30,'531000003003')
        """, da(38, 9), da(8))   # due_date = 8 days ago

        # AR ledger: 0-30 bucket, 8 days overdue
        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,collection_priority,last_action)
            VALUES ('AR-003-A','CUST-0001','INV-003-A','ORD-003-A','invoice',
                $1,$2,531000,531000,'0-30','overdue',8,'LOW','reminder_sent')
        """, da(38, 9), da(8))

        # ── Gmail dispute demo invoice referenced by the OAuth email poller ──
        # Keeps /api/disputes/submit-email from violating portal_disputes.invoice_id FK
        # when the sample inbox contains INV-20260618112754-E.
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-20260618112754-E','CUST-0001','SKU-001',3,15000,45000,18,8100,53100,
                $1,'email','PO-SAT-DISPUTE-DEMO','invoiced','approved',0.05,0.08,
                FALSE,'system',
                'Seeded invoice for Gmail dispute intake demo. Customer may request partial refund of ₹10,620.',
                '[]')
        """, da(1, 11, 27))

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-DISPUTE-DEMO','ORD-20260618112754-E','CUST-0001',0.08,0.05,FALSE,'CLEAR',FALSE,
                'Seeded Gmail dispute demo invoice. Normal customer and amount profile.',
                'seeded_dispute_demo')
        """)

        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-20260618112754-E','ORD-20260618112754-E','CUST-0001',$1,$2,
                45000,8100,53100,0,53100,'pending',0,30,'127541127540')
        """, da(1, 11, 27), df(29, 11, 27))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,collection_priority,last_action)
            VALUES ('AR-DISPUTE-DEMO','CUST-0001','INV-20260618112754-E','ORD-20260618112754-E','invoice',
                $1,$2,53100,53100,'0-30','pending',0,'LOW','invoice_generated')
        """, da(1, 11, 27), df(29, 11, 27))

        # Dunning L1 sent 3 days ago for this overdue
        await conn.execute("""
            INSERT INTO dunning_log (dunning_id,customer_id,invoice_id,dunning_level,channel,
                message_subject,message_body_preview,sent_at,groq_generated,account_segment,collection_priority_score)
            VALUES ('DUN-001-A','CUST-0001','INV-003-A','Level 1','email',
                'Friendly Reminder: Invoice INV-003-A — 8 Days Overdue',
                'Dear Satya Tamma, we hope all is well. Invoice INV-003-A for ₹5,31,000 was due 8 days ago. As a valued Tier-A customer, we understand occasional delays — please arrange payment at your earliest convenience.',
                $1,TRUE,'A1B',0.25)
        """, da(3))

        # ── ORD-004-A: BIG order 2 days ago — HITL SOX gate ₹13.3L ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-004-A','CUST-0001','SKU-004',25,45000,1125000,18,202500,1327500,
                $1,'email','PO-SAT-2025-004','hitl_required','pending',0.07,0.12,
                TRUE,'',
                'RULE-002 SOX Gate: ₹13.3L exceeds ₹10L threshold. Finance Controller sign-off needed. Fraud 7% — CLEAR.',
                '["RULE-002_SOX_GATE","LARGE_ORDER_REVIEW"]')
        """, da(2, 11))

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-004','ORD-004-A','CUST-0001',0.12,0.07,FALSE,'CLEAR',FALSE,
                'HITL triggered by amount (₹13.3L > ₹10L SOX threshold), not fraud. IF=0.12 normal for large order. XGB=7% well below 70% threshold. Awaiting Finance Controller.',
                'amount_exceeds_sox_threshold')
        """)

        print("  OK CUST-0001: 4 orders (2 paid, 1 overdue 8d, 1 HITL SOX)")

        # ══════════════════════════════════════════════════════════════════
        # CUST-0002 — Kamma Enterprises
        # Tier C | 18-month account | avg_dso=75 | 4 missed payments | Credit ₹2L
        # Storyline:
        #   ORD-001-C  90d ago  fulfilled + PAID (₹1.06L) — small approved order
        #   ORD-002-C  35d ago  FULL FRAUD BLOCK (3:12AM IF=0.89 XGB=0.82)
        #   ORD-003-C  60d ago  fulfilled → 45d OVERDUE (₹94,400) HIGH priority
        #   ORD-004-C  75d ago  fulfilled → 62d OVERDUE (₹88,500) CRITICAL pre-legal
        #   ORD-005-C   2d ago  CREDIT REJECTED (₹3.3L vs ₹0.17L headroom)
        # ══════════════════════════════════════════════════════════════════
        print("\n>> CUST-0002 — Kamma Enterprises (Tier C, High-Risk, 4 missed payments)")

        # ── ORD-001-C: Small fulfilled order 90d ago — PAID ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-001-C','CUST-0002','SKU-002',20,4500,90000,18,16200,106200,
                $1,'email','PO-KAM-001','fulfilled','approved',0.18,0.22,
                FALSE,'system',
                'Small Tier-C order. Within ₹2L limit. PD=18.4% — approved with note.','[]')
        """, da(90))

        await conn.execute("""
            INSERT INTO credit_decisions (decision_id,order_id,customer_id,credit_tier,
                credit_limit_inr,open_ar_balance_inr,order_amount_inr,xgboost_credit_score,
                credit_risk_class,pd_score,recommended_credit_limit_inr,decision,decision_reason,ecoa_audit_logged)
            VALUES ('CD-003','ORD-001-C','CUST-0002','C',200000,0,106200,0.48,'HIGH',0.22,
                150000,'approved','Small order approved despite high PD. Account 18m old.',TRUE)
        """)

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-005','ORD-001-C','CUST-0002',0.22,0.18,FALSE,'CLEAR',FALSE,
                'Small order within Tier-C range. IF=0.22 slightly elevated but below 0.55 threshold. Daytime email. 4 missed payments is credit risk not fraud signal.',
                'missed_payment_history')
        """)

        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-001-C','ORD-001-C','CUST-0002',$1,$2,
                90000,16200,106200,106200,0,'paid',0,60,'300001000001')
        """, da(90), da(30))  # 60d terms → due 30d ago → paid (just barely)

        await conn.execute("""
            INSERT INTO payments (payment_id,invoice_id,amount_inr,payment_date,payment_method,status)
            VALUES ('PAY-001-C','INV-001-C',106200,$1,'bank_transfer','processed')
        """, da(29))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,collection_priority,last_action)
            VALUES ('AR-001-C','CUST-0002','INV-001-C','ORD-001-C','invoice',
                $1,$2,106200,0,'0-30','paid',0,'MEDIUM','payment_received')
        """, da(90), da(30))

        # ── ORD-002-C: FULL FRAUD BLOCK — 3:12AM, 5 signals, IF=0.89, XGB=0.82 ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-002-C','CUST-0002','SKU-004',10,45000,450000,18,81000,531000,
                $1,'api','PO-KMM-002','fraud_review','blocked',0.82,0.89,
                TRUE,'',
                'FRAUD BLOCKED: IF=0.89 (top 1% anomaly). XGBoost=82%. 3:12AM. SKU-004 never bought. ₹5.31L=2.6x credit limit. Velocity spike. DUAL-MODEL: AUTO-BLOCKED.',
                '["RULE-005_FRAUD_BLOCK","RULE-002_EXCEEDS_LIMIT","RULE-001_VELOCITY","RULE-004_HITL"]')
        """, da(35, 3, 12))

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-006','ORD-002-C','CUST-0002',0.89,0.82,TRUE,'FRAUD',TRUE,
                'CRITICAL 5 signals: (1) 03:12AM — all prior orders 09-17h. (2) SKU-004 never purchased. (3) API channel — always email. (4) ₹5.31L = 2.6x credit limit ₹2L. (5) Velocity spike 3h after ORD-001-C. IF=0.89 top-1% anomaly. XGB=82%. DUAL-MODEL CONSENSUS: FRAUD.',
                'submission_time_03h12_velocity')
        """)

        await conn.execute("""
            INSERT INTO credit_decisions (decision_id,order_id,customer_id,credit_tier,
                credit_limit_inr,open_ar_balance_inr,order_amount_inr,xgboost_credit_score,
                credit_risk_class,pd_score,recommended_credit_limit_inr,decision,decision_reason,ecoa_audit_logged)
            VALUES ('CD-004','ORD-002-C','CUST-0002','C',200000,94400,531000,0.21,'HIGH',0.342,
                50000,'blocked','BLOCKED: Fraud overrides credit. ₹5.31L = 2.6x limit. AR ₹94,400 outstanding.',TRUE)
        """)

        # ── ORD-003-C: Fulfilled 60d ago → 45 days OVERDUE (60d terms → due 60-60=0? let's use 55d terms) ──
        # Order placed 60d ago, terms=45d → due 15d ago → 15 days overdue
        # Actually: to get 45d overdue with 60d payment terms: order must be ≥ 105 days old, but account is 18m=540d
        # Let's use: order 75d ago, terms=30d → due 45d ago → 45d overdue
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-003-C','CUST-0002','SKU-003',10,8000,80000,18,14400,94400,
                $1,'email','PO-KAM-002','fulfilled','approved',0.21,0.22,
                FALSE,'system',
                'Bearings order. Tier-C watchlist. High PD=0.22. Approved. Now 45d overdue.',
                '["RULE-003_CREDIT_WATCHLIST"]')
        """, da(75))  # placed 75d ago

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-007','ORD-003-C','CUST-0002',0.22,0.21,FALSE,'CLEAR',FALSE,
                'Borderline IF=0.22 — elevated but below 0.55 threshold. Bearings more typical than PLC. ₹94K within ₹2L limit. Daytime. Passed with watchlist flag.',
                'elevated_if_score_monitored')
        """)

        # Invoice: issued 75d ago, payment_terms=30d → due 45d ago → 45d overdue
        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-002-C','ORD-003-C','CUST-0002',$1,$2,
                80000,14400,94400,0,94400,'overdue',45,30,'094400002002')
        """, da(75), da(45))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,xgboost_delay_score,collection_priority,last_action,last_action_date)
            VALUES ('AR-002-C','CUST-0002','INV-002-C','ORD-003-C','invoice',
                $1,$2,94400,94400,'31-60','overdue',45,0.78,'HIGH','escalation_email_sent',$3)
        """, da(75), da(45), da(15))

        # ── ORD-004-C: Fulfilled 90d ago → 62 days OVERDUE ──
        # Order 90d ago, terms=28d (custom) → due 62d ago → 62d overdue
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-004-C','CUST-0002','SKU-001',5,15000,75000,18,13500,88500,
                $1,'email','PO-KAM-003','fulfilled','approved',0.19,0.19,
                FALSE,'system',
                'Third order. Pattern of late payment emerging. Pre-legal escalation triggered.',
                '["RULE-003_CREDIT_WATCHLIST"]')
        """, da(90))

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-008','ORD-004-C','CUST-0002',0.19,0.19,FALSE,'CLEAR',FALSE,
                'Normal small motor order. Cleared at order time. Payment delinquency post-approval — not detectable at order time.',
                'normal_order_delinquency_post_approval')
        """)

        # Invoice: issued 90d ago, terms=28d → due 62d ago → 62d overdue
        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-003-C','ORD-004-C','CUST-0002',$1,$2,
                75000,13500,88500,0,88500,'overdue',62,28,'088500003003')
        """, da(90), da(62))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,xgboost_delay_score,collection_priority,last_action,last_action_date)
            VALUES ('AR-003-C','CUST-0002','INV-003-C','ORD-004-C','invoice',
                $1,$2,88500,88500,'61-90','overdue',62,0.91,'CRITICAL','pre_legal_notice',$3)
        """, da(90), da(62), da(7))

        # ── ORD-005-C: Credit REJECTED 2d ago ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-005-C','CUST-0002','SKU-005',10,28000,280000,18,50400,330400,
                $1,'email','','rejected','rejected',0.15,0.18,
                FALSE,'',
                'CREDIT REJECTED: ₹3.3L exceeds available credit (Limit: ₹2L, AR: ₹1.83L, Available: ₹0.17L)',
                '["RULE-002_EXCEEDS_LIMIT","RULE-003_CREDIT_WATCHLIST"]')
        """, da(2))

        await conn.execute("""
            INSERT INTO credit_decisions (decision_id,order_id,customer_id,credit_tier,
                credit_limit_inr,open_ar_balance_inr,order_amount_inr,xgboost_credit_score,
                credit_risk_class,pd_score,recommended_credit_limit_inr,decision,decision_reason,ecoa_audit_logged)
            VALUES ('CD-005','ORD-005-C','CUST-0002','C',200000,182900,330400,0.31,'HIGH',0.41,
                80000,'rejected','Order (₹3.3L) exceeds available credit headroom (₹0.17L). 4 missed payments. PD=41%.',TRUE)
        """)

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-009','ORD-005-C','CUST-0002',0.18,0.15,FALSE,'CLEAR',FALSE,
                'Credit-rejected on limit grounds, not fraud. IF=0.18 normal. XGB=15% below threshold.',
                'credit_limit_exhausted')
        """)

        # Dunning logs for CUST-0002 — 3 levels
        await conn.execute("""
            INSERT INTO dunning_log (dunning_id,customer_id,invoice_id,dunning_level,channel,
                message_subject,message_body_preview,sent_at,groq_generated,account_segment,collection_priority_score)
            VALUES
            ('DUN-001-C','CUST-0002','INV-002-C','Level 1','email',
             'Payment Reminder: INV-002-C Overdue 30 Days',
             'Dear Kamma J, your invoice INV-002-C for ₹94,400 is 30 days overdue. Please arrange payment immediately...',
             $1,TRUE,'C2B',0.78),
            ('DUN-002-C','CUST-0002','INV-003-C','Level 2','email',
             'URGENT: Invoice INV-003-C 45 Days Overdue — Immediate Action Required',
             'Dear Kamma J, this is an urgent notice. Invoice INV-003-C for ₹88,500 is now 45 days overdue. Your account is at risk of suspension...',
             $2,TRUE,'C2B',0.91),
            ('DUN-003-C','CUST-0002','INV-003-C','Level 3','email',
             'FINAL NOTICE: Invoice INV-003-C — Legal Escalation in 7 Days',
             'Dear Kamma J, this is your final notice before we escalate to our legal team. Amount due ₹88,500. Respond within 7 days to avoid legal proceedings...',
             $3,TRUE,'C2B',0.95)
        """, da(30), da(15), da(7))

        # Anomaly alert for CUST-0002 payment pattern
        await conn.execute("""
            INSERT INTO anomaly_alerts (alert_id,alert_type,severity,customer_id,order_id,
                isolation_forest_score,sliding_window_events,groq_alert_summary,recommended_action,
                hitl_gate,hitl_required,reviewed)
            VALUES ('ALERT-001','PAYMENT_PATTERN_ANOMALY','HIGH','CUST-0002','ORD-005-C',
                0.88,4,
                'Customer CUST-0002 shows escalating payment default pattern: 4 missed payments in 12 months, 2 invoices overdue >45 days, credit utilisation at 91%. Probability of further default: 78%.',
                'Place on credit hold. Require upfront payment for future orders. Escalate to Finance Controller.',
                'HITL_GATE_5',TRUE,FALSE)
        """)

        print("  OK CUST-0002: 5 orders (1 paid, 1 FRAUD blocked, 2 overdue, 1 rejected)")

        # ══════════════════════════════════════════════════════════════════
        # CUST-0003 — Jhansi Logistics & Co
        # Tier B | 24-month account | avg_dso=42 | 1 missed payment | Credit ₹5L
        # Storyline:
        #   ORD-001-B  70d ago  fulfilled + PAID (₹2.83L)
        #   ORD-002-B   3d ago  ISOLATION FOREST ANOMALY (2:47AM, IF=0.72, XGB=0.54)
        #   ORD-003-B  25d ago  fulfilled → 25d OVERDUE (₹2.65L) + DISPUTE (pricing error)
        # ══════════════════════════════════════════════════════════════════
        print("\n>> CUST-0003 — Jhansi Logistics (Tier B, IF anomaly, overdue+dispute)")

        # ── ORD-001-B: Normal fulfilled, paid 70d ago ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-001-B','CUST-0003','SKU-003',30,8000,240000,18,43200,283200,
                $1,'email','PO-JHN-2025-001','fulfilled','approved',0.12,0.14,
                FALSE,'system','Standard bearings order. Tier-B approved. Daytime email.','[]')
        """, da(70, 10))

        await conn.execute("""
            INSERT INTO credit_decisions (decision_id,order_id,customer_id,credit_tier,
                credit_limit_inr,open_ar_balance_inr,order_amount_inr,xgboost_credit_score,
                credit_risk_class,pd_score,recommended_credit_limit_inr,decision,decision_reason,ecoa_audit_logged)
            VALUES ('CD-006','ORD-001-B','CUST-0003','B',500000,0,283200,0.74,'MEDIUM',0.062,
                500000,'approved','Tier-B, PD 6.2%, 1 missed payment — approved within limit',TRUE)
        """)

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-010','ORD-001-B','CUST-0003',0.14,0.12,FALSE,'CLEAR',FALSE,
                'Normal daytime order (10:00). Bearings fit logistics. Amount within Tier-B range. Account 24m old.',
                'daytime_submission')
        """)

        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-001-B','ORD-001-B','CUST-0003',$1,$2,
                240000,43200,283200,283200,0,'paid',0,45,'200001000001')
        """, da(70, 10), da(25))  # 45d terms → due 25d ago → paid in time

        await conn.execute("""
            INSERT INTO payments (payment_id,invoice_id,amount_inr,payment_date,payment_method,status)
            VALUES ('PAY-001-B','INV-001-B',283200,$1,'bank_transfer','processed')
        """, da(24))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,collection_priority,last_action)
            VALUES ('AR-001-B','CUST-0003','INV-001-B','ORD-001-B','invoice',
                $1,$2,283200,0,'0-30','paid',0,'LOW','payment_received')
        """, da(70, 10), da(25))

        # ── ORD-002-B: ISOLATION FOREST ANOMALY — 2:47AM, API, new SKU, 6x amount ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-002-B','CUST-0003','SKU-004',8,45000,360000,18,64800,424800,
                $1,'api','PO-JHN-002-URGENT','fraud_review','pending',0.54,0.72,
                TRUE,'',
                'ISOLATION FOREST ANOMALY: 2:47AM (customer always 9AM-6PM). PLC (never bought before). Amount 6x usual. API channel (always email). IF=0.72 — auto-blocked HITL.',
                '["RULE-005_FRAUD_ANOMALY","RULE-001_UNUSUAL_PATTERN","RULE-004_CREDIT_HITL"]')
        """, da(3, 2, 47))

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-011','ORD-002-B','CUST-0003',0.72,0.54,TRUE,'FRAUD',TRUE,
                'ANOMALY: (1) 02:47AM — all 47 prior orders 09:00-18:00. (2) SKU-004 never purchased in 2yr history. (3) API channel — customer uses only email. (4) ₹4.25L = 6x average ₹0.71L. IF=0.72 HIGH anomaly. XGB=54% fraud.',
                'submission_time_02h47')
        """)

        await conn.execute("""
            INSERT INTO credit_decisions (decision_id,order_id,customer_id,credit_tier,
                credit_limit_inr,open_ar_balance_inr,order_amount_inr,xgboost_credit_score,
                credit_risk_class,pd_score,recommended_credit_limit_inr,decision,decision_reason,ecoa_audit_logged)
            VALUES ('CD-007','ORD-002-B','CUST-0003','B',500000,265500,424800,0.58,'MEDIUM',0.078,
                400000,'pending_review','HITL: Fraud alert blocks credit. Amount + AR = ₹6.9L nearing ₹5L limit.',TRUE)
        """)

        # ── ORD-003-B: Fulfilled 25d ago → 25d OVERDUE with DISPUTE ──
        # 45d terms → due 45d from order → order 25d ago → due date 20d from now? No.
        # Let's use shorter terms: order 50d ago, 25d terms → due 25d ago → 25d overdue
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-003-B','CUST-0003','SKU-001',15,15000,225000,18,40500,265500,
                $1,'email','PO-JHN-2025-002','fulfilled','approved',0.11,0.13,
                FALSE,'system','Email order. Motor delivery confirmed. Invoice overdue. Dispute raised.','[]')
        """, da(50))

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-012','ORD-003-B','CUST-0003',0.13,0.11,FALSE,'CLEAR',FALSE,
                'Normal morning order. Email channel consistent with history. Motor fits logistics sector.',
                'consistent_channel_usage')
        """)

        # Invoice: issued 50d ago, 25d terms → due 25d ago → 25d overdue
        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-002-B','ORD-003-B','CUST-0003',$1,$2,
                225000,40500,265500,0,265500,'overdue',25,25,'265500002002')
        """, da(50), da(25))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,xgboost_delay_score,collection_priority,last_action)
            VALUES ('AR-002-B','CUST-0003','INV-002-B','ORD-003-B','invoice',
                $1,$2,265500,265500,'0-30','overdue',25,0.67,'HIGH','reminder_sent')
        """, da(50), da(25))

        # Dispute on INV-002-B
        await conn.execute("""
            INSERT INTO portal_disputes (dispute_id, customer_id, order_id, invoice_id,
                dispute_type, status, source, subject, ai_summary)
            VALUES ('DISP-20250603-001', 'CUST-0003', 'ORD-003-B', 'INV-002-B',
                'pricing_error', 'open', 'email', 'Pricing Error on INV-002-B',
                'Customer claims they were quoted ₹13,000 per motor but billed at ₹15,000. Disputed amount: ₹30,000.')
        """)

        await conn.execute("""
            INSERT INTO portal_dispute_messages (message_id, dispute_id, sender_type, sender_id, body, created_at)
            VALUES ('MSG-DISP-001', 'DISP-20250603-001', 'customer', 'CUST-0003',
                'We were quoted ₹13,000 per motor in the sales quote dated 30-Apr-2025 but were billed at ₹15,000 on INV-002-B. We are disputing ₹30,000 difference.',
                $1)
        """, da(5))

        # Dunning L1 for CUST-0003
        await conn.execute("""
            INSERT INTO dunning_log (dunning_id,customer_id,invoice_id,dunning_level,channel,
                message_subject,message_body_preview,sent_at,groq_generated,account_segment,collection_priority_score)
            VALUES ('DUN-001-B','CUST-0003','INV-002-B','Level 1','email',
                'Friendly Reminder: Invoice INV-002-B Due',
                'Dear Jhansi Kamma, this is a friendly reminder that invoice INV-002-B for ₹2,65,500 is now overdue. Please arrange payment or contact us about the open dispute.',
                $1,TRUE,'B2B',0.67)
        """, da(15))

        print("  OK CUST-0003: 3 orders (1 paid, 1 IF anomaly blocked, 1 overdue+dispute)")

        # ══════════════════════════════════════════════════════════════════
        # CUST-0004 — Priya Components Ltd
        # Tier B | 12-month account | avg_dso=30 | 0 missed | Credit ₹3L
        # Storyline:
        #   ORD-001-D  60d ago  fulfilled + PAID (₹1.18L)
        #   ORD-002-D  30d ago  fulfilled + PAID (₹1.77L)  — partial payment edge case
        #   ORD-003-D  10d ago  invoiced → PENDING (₹2.36L) — Cash Application demo
        # ══════════════════════════════════════════════════════════════════
        print("\n>> CUST-0004 — Priya Components (Tier B, Clean, Cash App demo)")

        # ── ORD-001-D: Fulfilled 60d ago — PAID ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-001-D','CUST-0004','SKU-003',15,8000,120000,18,21600,141600,
                $1,'portal','PO-PRY-2025-001','fulfilled','approved',0.08,0.11,
                FALSE,'system','Portal order. Tier-B clean account. Auto-approved.','[]')
        """, da(60, 10))

        await conn.execute("""
            INSERT INTO credit_decisions (decision_id,order_id,customer_id,credit_tier,
                credit_limit_inr,open_ar_balance_inr,order_amount_inr,xgboost_credit_score,
                credit_risk_class,pd_score,recommended_credit_limit_inr,decision,decision_reason,ecoa_audit_logged)
            VALUES ('CD-008','ORD-001-D','CUST-0004','B',300000,0,141600,0.82,'LOW',0.031,
                350000,'approved','Tier-B, PD 3.1%, no missed payments, clean account',TRUE)
        """)

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-013','ORD-001-D','CUST-0004',0.11,0.08,FALSE,'CLEAR',FALSE,
                'Portal order 10:00. Bearings fits electronics sector. Amount well within Tier-B limit. Zero missed payments. IF=0.11 very low.',
                'clean_account_history')
        """)

        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-001-D','ORD-001-D','CUST-0004',$1,$2,
                120000,21600,141600,141600,0,'paid',0,30,'400001000001')
        """, da(60, 10), da(30))

        await conn.execute("""
            INSERT INTO payments (payment_id,invoice_id,amount_inr,payment_date,payment_method,status)
            VALUES ('PAY-001-D','INV-001-D',141600,$1,'neft','processed')
        """, da(29))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,collection_priority,last_action)
            VALUES ('AR-001-D','CUST-0004','INV-001-D','ORD-001-D','invoice',
                $1,$2,141600,0,'0-30','paid',0,'LOW','payment_received')
        """, da(60, 10), da(30))

        # ── ORD-002-D: Fulfilled 30d ago — PARTIAL PAYMENT (₹1L paid, ₹77,360 still due) ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-002-D','CUST-0004','SKU-001',10,15000,150000,18,27000,177000,
                $1,'email','PO-PRY-2025-002','invoiced','approved',0.09,0.10,
                FALSE,'system','Email order. Partial payment received ₹1L. Balance ₹77,360 pending.','[]')
        """, da(30, 11))

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-014','ORD-002-D','CUST-0004',0.10,0.09,FALSE,'CLEAR',FALSE,
                'Normal daytime email (11:00). Motor fits electronics sector. Amount within Tier-B limit.',
                'established_account')
        """)

        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-002-D','ORD-002-D','CUST-0004',$1,$2,
                150000,27000,177000,100000,77000,'pending',0,30,'177000002002')
        """, da(30, 11), df(0))  # due today exactly

        await conn.execute("""
            INSERT INTO payments (payment_id,invoice_id,amount_inr,payment_date,payment_method,status)
            VALUES ('PAY-002-D','INV-002-D',100000,$1,'upi','processed')
        """, da(5))

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,collection_priority,last_action)
            VALUES ('AR-002-D','CUST-0004','INV-002-D','ORD-002-D','invoice',
                $1,$2,177000,77000,'0-30','pending',0,'LOW','partial_payment_applied')
        """, da(30, 11), df(0))

        # ── ORD-003-D: New email order 10d ago — PENDING payment (Cash App demo) ──
        await conn.execute("""
            INSERT INTO orders (order_id,customer_id,sku_id,quantity,unit_price_inr,
                subtotal_inr,gst_pct,gst_amount_inr,total_amount_inr,
                order_date,channel,po_reference,status,credit_check_status,
                fraud_score,isolation_forest_score,hitl_required,hitl_resolved_by,
                agent_notes,policy_engine_flags)
            VALUES ('ORD-003-D','CUST-0004','SKU-002',40,4500,180000,18,32400,212400,
                $1,'portal','PO-PRY-2025-003','invoiced','approved',0.06,0.09,
                FALSE,'system','Portal copper wire order. Invoice sent. Awaiting payment.','[]')
        """, da(10, 9))

        await conn.execute("""
            INSERT INTO fraud_records (fraud_id,order_id,customer_id,isolation_forest_score,
                xgboost_fraud_probability,anomaly_flag,fraud_verdict,order_blocked,shap_explanation,shap_top_feature)
            VALUES ('FR-015','ORD-003-D','CUST-0004',0.09,0.06,FALSE,'CLEAR',FALSE,
                'Portal order 09:00. Copper wire fits electronics. Amount well within limit. Zero history issues.',
                'zero_risk_profile')
        """)

        await conn.execute("""
            INSERT INTO invoices (invoice_id,order_id,customer_id,invoice_date,due_date,
                subtotal_inr,gst_amount_inr,total_amount_inr,amount_paid_inr,balance_due_inr,
                payment_status,days_overdue,payment_terms_days,payment_token)
            VALUES ('INV-003-D','ORD-003-D','CUST-0004',$1,$2,
                180000,32400,212400,0,212400,'pending',0,30,'212400003003')
        """, da(10, 9), df(20))  # due 20 days from now

        await conn.execute("""
            INSERT INTO ar_ledger (ar_id,customer_id,invoice_id,order_id,transaction_type,
                transaction_date,due_date,amount_inr,outstanding_balance_inr,aging_bucket,
                payment_status,days_overdue,collection_priority,last_action)
            VALUES ('AR-003-D','CUST-0004','INV-003-D','ORD-003-D','invoice',
                $1,$2,212400,212400,'0-30','pending',0,'LOW','invoice_sent')
        """, da(10, 9), df(20))

        print("  OK CUST-0004: 3 orders (1 paid, 1 partial, 1 pending)")

        # ══════════════════════════════════════════════════════════════════
        print("\n>> Inventory Phase 1 — opening stock transactions + sample POs...")
        # ══════════════════════════════════════════════════════════════════
        # Opening STOCK_ADJUSTMENT transactions record the initial on-hand balance
        # for each SKU so the inventory ledger starts with a complete audit trail.
        opening_txns = [
            # (txn_id, sku_id, qty_delta, field_affected, balance_after, reason)
('TXN-OPEN-001', 'SKU-001', 500,  'stock_on_hand', 500,  'Opening stock — warehouse count 2025-01-01'),
            ('TXN-OPEN-002', 'SKU-002', 120,  'stock_on_hand', 120,  'Opening stock — warehouse count 2025-01-01'),
            ('TXN-OPEN-003', 'SKU-003', 800,  'stock_on_hand', 800,  'Opening stock — warehouse count 2025-01-01'),
            ('TXN-OPEN-004', 'SKU-004', 12,   'stock_on_hand', 12,   'Opening stock — warehouse count 2025-01-01'),
            ('TXN-OPEN-005', 'SKU-005', 200,  'stock_on_hand', 200,  'Opening stock — warehouse count 2025-01-01'),
        ]
        for txn_id, sku_id, qty_delta, field_affected, balance_after, reason in opening_txns:
            await conn.execute("""
                INSERT INTO inventory_transactions
                    (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                     balance_after, reason, performed_by, actor_type, created_at)
                VALUES ($1, $2, 'STOCK_ADJUSTMENT', $3, $4, $5, $6, 'system', 'system', $7)
            """, txn_id, sku_id, qty_delta, field_affected, balance_after, reason, da(180))
        print(f"  OK {len(opening_txns)} opening STOCK_ADJUSTMENT transactions")

        # ── Sample Purchase Order 1: SKU-004 PLC replenishment (already confirmed) ──
        # SKU-004 has only 150 units on hand with reorder_level=25 and lead_time=21d.
        # A PO was already raised and is in transit — drives incoming_stock.
        await conn.execute("""
            INSERT INTO purchase_orders
                (po_id, supplier_id, status, expected_arrival_date,
                 created_at, confirmed_at, created_by, metadata)
            VALUES ('PO-2025-001', 'SUPPLIER-PLCTECH', 'confirmed', $1,
                    $2, $3, 'admin',
                    '{"notes": "Quarterly PLC replenishment. Supplier confirmed 2025-05-20."}')
        """, df(7), da(21), da(18))

        await conn.execute("""
            INSERT INTO purchase_order_items
                (po_item_id, po_id, sku_id, quantity_ordered, quantity_received,
                 unit_cost_inr, line_status, created_at)
            VALUES ('POI-2025-001-01', 'PO-2025-001', 'SKU-004', 50, 0, 38000, 'open', $1)
        """, da(21))

        # Reflect incoming_stock on the product and log the transaction
        await conn.execute(
            "UPDATE products SET incoming_stock = 50 WHERE sku_id = 'SKU-004'"
        )
        await conn.execute("""
            INSERT INTO inventory_transactions
                (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                 balance_after, purchase_order_id, reason, performed_by, actor_type, created_at)
            VALUES ('TXN-PO-001', 'SKU-004', 'PURCHASE_ORDER_CONFIRMED', 50, 'incoming_stock',
                    50, 'PO-2025-001', 'PO-2025-001 confirmed — 50 PLC units incoming',
                    'admin', 'human', $1)
        """, da(21))
        print("  OK PO-2025-001 (SKU-004 × 50 PLCs, confirmed, arriving in 7 days)")

        # ── Sample Purchase Order 2: SKU-001 Motor replenishment (draft) ──
        # SKU-001 has 500 units on hand, reorder_level=80, safety_stock=30, lead_time=14d.
        # A draft PO is queued — not confirmed yet, so incoming_stock stays 0.
        await conn.execute("""
            INSERT INTO purchase_orders
                (po_id, supplier_id, status, expected_arrival_date,
                 created_at, created_by, metadata)
            VALUES ('PO-2025-002', 'SUPPLIER-MOTORCO', 'draft', $1,
                    $2, 'system',
                    '{"notes": "Auto-generated draft. Awaiting procurement approval.", "auto_generated": true}')
        """, df(21), da(2))

        await conn.execute("""
            INSERT INTO purchase_order_items
                (po_item_id, po_id, sku_id, quantity_ordered, quantity_received,
                 unit_cost_inr, line_status, created_at)
            VALUES ('POI-2025-002-01', 'PO-2025-002', 'SKU-001', 100, 0, 12500, 'open', $1)
        """, da(2))
        print("  OK PO-2025-002 (SKU-001 × 100 Motors, draft — awaiting approval)")

        # ── Inventory reservations for demo diversity ──
        # SKU-003 reserved 100 units (approved order), SKU-004 reserved 5 (low-stock urgent order)
        await conn.execute("""
            INSERT INTO inventory_reservations
                (reservation_id, order_id, sku_id, quantity_requested,
                 quantity_reserved, quantity_backordered, status,
                 expected_availability_date, reserved_at, metadata)
            VALUES
                ('RES-SEED-001', 'ORD-001-A', 'SKU-003', 100, 100, 0, 'active', NULL, $1, '{}'),
                ('RES-SEED-002', 'ORD-003-A', 'SKU-004',   5,   5, 0, 'active', NULL, $1, '{}')
        """, da(30))
        await conn.execute("""
            INSERT INTO inventory_transactions
                (txn_id, sku_id, txn_type, quantity_delta, field_affected,
                 balance_after, order_id, reason, performed_by, actor_type, created_at)
            VALUES
                ('TXN-RES-001', 'SKU-003', 'ORDER_RESERVATION', 100, 'reserved_stock', 100, 'ORD-001-A',
                 'Seed reservation — 100 Bearings reserved for ORD-001-A', 'system', 'system', $1),
                ('TXN-RES-002', 'SKU-004', 'ORDER_RESERVATION',   5, 'reserved_stock',   5, 'ORD-003-A',
                 'Seed reservation — 5 PLCs reserved for ORD-003-A', 'system', 'system', $1)
        """, da(30))
        print("  OK 2 seed reservations (SKU-003 × 100, SKU-004 × 5)")

        # ══════════════════════════════════════════════════════════════════
        print("\n>> Auto-updating AR balances from ar_ledger...")
        # ══════════════════════════════════════════════════════════════════
        await conn.execute("""
            UPDATE customers SET open_ar_balance_inr = (
                SELECT COALESCE(SUM(outstanding_balance_inr), 0)
                FROM ar_ledger
                WHERE customer_id = customers.customer_id
                  AND payment_status != 'paid'
            )
        """)
        print("  OK AR balances auto-updated from ar_ledger")

        # ══════════════════════════════════════════════════════════════════
        print("\n>> Inserting audit log entries...")
        # ══════════════════════════════════════════════════════════════════
        audit_entries = [
            # CUST-0001 full pipeline
            ('ORDER_PROCESSED',  'agent_01_order_ingestion',  'CUST-0001', 'ORD-001-A', 'INV-001-A', 'order_extracted',      '{"channel":"email","ner_source":"gliner","groq_validated":true}',                            'success'),
            ('CREDIT_APPROVED',  'agent_02_credit_check',     'CUST-0001', 'ORD-001-A', 'INV-001-A', 'credit_approved',      '{"tier":"A","pd_score":0.018,"xgboost":0.94,"risk_class":"LOW"}',                          'approved'),
            ('FRAUD_CLEARED',    'agent_03_fraud_detection',  'CUST-0001', 'ORD-001-A', '',          'fraud_cleared',        '{"isolation_forest":0.08,"xgboost":0.04,"verdict":"CLEAR"}',                               'cleared'),
            ('INVOICE_GENERATED','agent_06_invoice',          'CUST-0001', 'ORD-001-A', 'INV-001-A', 'invoice_generated',    '{"invoice_id":"INV-001-A","amount":354000,"due_days":30}',                                  'success'),
            ('PAYMENT_APPLIED',  'agent_07_cash_app',         'CUST-0001', 'ORD-001-A', 'INV-001-A', 'payment_matched',      '{"payment_id":"PAY-001-A","amount":354000,"match_confidence":0.99}',                       'success'),
            # CUST-0001 overdue
            ('DUNNING_SENT',     'agent_08_collections',      'CUST-0001', '', 'INV-003-A', 'dunning_level1_sent',           '{"level":"Level 1","days_overdue":8,"groq_generated":true}',                               'sent'),
            # CUST-0001 SOX HITL
            ('ORDER_PROCESSED',  'agent_01_order_ingestion',  'CUST-0001', 'ORD-004-A', '',          'order_extracted',      '{"channel":"email","amount":1327500,"triggered_sox_check":true}',                          'success'),
            ('HITL_ESCALATION',  'policy_engine',             'CUST-0001', 'ORD-004-A', '',          'hitl_required',        '{"reason":"RULE-002_SOX_GATE","amount":1327500,"threshold":1000000}',                      'pending'),
            # CUST-0002 fraud block
            ('ORDER_PROCESSED',  'agent_01_order_ingestion',  'CUST-0002', 'ORD-002-C', '',          'order_extracted',      '{"channel":"api","time":"03:12","groq_flagged":"critical_anomaly"}',                       'success'),
            ('FRAUD_FLAGGED',    'agent_03_fraud_detection',  'CUST-0002', 'ORD-002-C', '',          'fraud_blocked',        '{"isolation_forest":0.89,"xgboost":0.82,"verdict":"FRAUD","order_blocked":true,"signals":5}','blocked'),
            ('CREDIT_REJECTED',  'agent_02_credit_check',     'CUST-0002', 'ORD-005-C', '',          'credit_rejected',      '{"available_headroom":17100,"order_amount":330400,"pd_score":0.41}',                       'rejected'),
            ('DUNNING_SENT',     'agent_08_collections',      'CUST-0002', '', 'INV-002-C', 'dunning_level1_sent',           '{"level":"Level 1","days_overdue":30,"groq_generated":true}',                              'sent'),
            ('DUNNING_SENT',     'agent_08_collections',      'CUST-0002', '', 'INV-003-C', 'dunning_level2_sent',           '{"level":"Level 2","days_overdue":45,"groq_generated":true}',                              'sent'),
            ('DUNNING_SENT',     'agent_08_collections',      'CUST-0002', '', 'INV-003-C', 'dunning_level3_sent',           '{"level":"Level 3","days_overdue":62,"groq_generated":true}',                              'sent'),
            # CUST-0003 IF anomaly
            ('ORDER_PROCESSED',  'agent_01_order_ingestion',  'CUST-0003', 'ORD-002-B', '',          'order_extracted',      '{"channel":"api","time":"02:47","groq_flagged":"unusual_time"}',                           'success'),
            ('FRAUD_FLAGGED',    'agent_03_fraud_detection',  'CUST-0003', 'ORD-002-B', '',          'fraud_flagged',        '{"isolation_forest":0.72,"xgboost":0.54,"verdict":"FRAUD","anomaly_flag":true}',           'blocked'),
            ('DISPUTE_CREATED',  'agent_04_dispute_ner',      'CUST-0003', 'ORD-003-B', 'INV-002-B', 'dispute_extracted',   '{"reason":"pricing_error","confidence":0.91,"disputed_amount":30000}',                    'open'),
            ('DUNNING_SENT',     'agent_08_collections',      'CUST-0003', '', 'INV-002-B', 'dunning_level1_sent',           '{"level":"Level 1","days_overdue":25,"groq_generated":true}',                              'sent'),
            # CUST-0004 cash app
            ('INVOICE_GENERATED','agent_06_invoice',          'CUST-0004', 'ORD-003-D', 'INV-003-D', 'invoice_generated',   '{"invoice_id":"INV-003-D","amount":212400,"due_days":30}',                                  'success'),
            ('PAYMENT_APPLIED',  'agent_07_cash_app',         'CUST-0004', 'ORD-002-D', 'INV-002-D', 'partial_payment',     '{"payment_id":"PAY-002-D","amount":100000,"balance_remaining":77000}',                     'partial'),
        ]
        await conn.executemany("""
            INSERT INTO audit_log (event_type, agent_name, customer_id, order_id, invoice_id, action, details, outcome)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """, audit_entries)
        print(f"  OK {len(audit_entries)} audit log entries")

        # ══════════════════════════════════════════════════════════════════
        print("\n>> Verifying data counts...")
        # ══════════════════════════════════════════════════════════════════
        for tbl in ['customers', 'products', 'orders', 'invoices', 'ar_ledger',
                    'fraud_records', 'credit_decisions', 'dunning_log',
                    'anomaly_alerts', 'payments', 'audit_log', 'portal_disputes',
                    'inventory_transactions', 'inventory_reservations',
                    'purchase_orders', 'purchase_order_items',
                    'inventory_forecast_snapshot']:
            n = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")
            print(f"  {tbl}: {n} rows")

        # Print final AR balances per customer
        rows = await conn.fetch(
            "SELECT customer_id, company_name, credit_tier, open_ar_balance_inr FROM customers ORDER BY customer_id"
        )
        print("\n  Final AR balances:")
        for r in rows:
            print(f"    {r['customer_id']} ({r['company_name']}) Tier-{r['credit_tier']}: Rs.{int(r['open_ar_balance_inr']):,}")

        print("""
  [OK] Rich seed v3 inserted successfully!

  ┌─────────────────────────────────────────────────────────────────────┐
  │  TEST SCENARIOS                                                     │
  ├─────────────────────────────────────────────────────────────────────┤
  │  CUST-0001 tammasatya25@gmail.com  (Satya Manufacturing, Tier A)    │
  │    ORD-001-A  90d  fulfilled + paid (INV-001-A ✓)                  │
  │    ORD-002-A  55d  portal fulfilled + paid (INV-002-A ✓)           │
  │    ORD-003-A  38d  OVERDUE 8d ₹5.31L — C360 AR widget shows red   │
  │    ORD-004-A   2d  HITL-SOX gate ₹13.3L awaiting sign-off         │
  ├─────────────────────────────────────────────────────────────────────┤
  │  CUST-0002 kammajhu8@gmail.com  (Kamma Enterprises, Tier C)        │
  │    ORD-001-C  90d  fulfilled + paid (INV-001-C ✓)                  │
  │    ORD-002-C  35d  FRAUD BLOCK (3:12AM IF=0.89 XGB=0.82)          │
  │    ORD-003-C  75d  45d OVERDUE ₹94,400 HIGH priority              │
  │    ORD-004-C  90d  62d OVERDUE ₹88,500 CRITICAL pre-legal         │
  │    ORD-005-C   2d  CREDIT REJECTED ₹3.3L vs ₹0.17L headroom       │
  ├─────────────────────────────────────────────────────────────────────┤
  │  CUST-0003 kammajhu5@gmail.com  (Jhansi Logistics, Tier B)         │
  │    ORD-001-B  70d  fulfilled + paid (INV-001-B ✓)                  │
  │    ORD-002-B   3d  IF ANOMALY HITL (2:47AM IF=0.72 XGB=0.54)      │
  │    ORD-003-B  50d  25d OVERDUE ₹2.65L + DISPUTE pricing error     │
  ├─────────────────────────────────────────────────────────────────────┤
  │  CUST-0004 priya.vendor@example.com  (Priya Components, Tier B)    │
  │    ORD-001-D  60d  fulfilled + paid                                 │
  │    ORD-002-D  30d  PARTIAL payment ₹1L paid, ₹77K still due        │
  │    ORD-003-D  10d  pending ₹2.12L (Cash App demo)                  │
  └─────────────────────────────────────────────────────────────────────┘

  Passwords: 123456789 (all customers)
""")

    await pool.close()

    # ══════════════════════════════════════════════════════════════════
    # Rebuild ChromaDB customer embeddings after re-seed
    # ══════════════════════════════════════════════════════════════════
    print(">> Rebuilding ChromaDB customer embeddings...")
    try:
        import asyncpg
        from database.chromadb_client import get_customers_collection
        from ml.embeddings import embed_text
        from config import settings

        col = get_customers_collection()
        try:
            col.delete(where={"customer_id": {"$ne": ""}})
        except Exception:
            pass

        pool2 = await get_pool()
        async with pool2.acquire() as conn2:
            customers = await conn2.fetch("SELECT * FROM customers")

        for cust in customers:
            text = f"{cust['company_name']} {cust['city']} {cust['state']} {cust['industry']} {cust['gstin']}"
            emb = embed_text(text)
            col.upsert(
                ids=[cust['customer_id']],
                embeddings=[emb],
                metadatas=[{
                    "customer_id": cust['customer_id'],
                    "company_name": cust['company_name'],
                    "email": cust['email'],
                }]
            )
            print(f"  Embedded {cust['customer_id']} — {cust['company_name']}")

        await pool2.close()
        print("  OK ChromaDB rebuilt with 4 customers")
    except Exception as e:
        print(f"  WARN ChromaDB rebuild skipped: {e}")
        print("  (ChromaDB will be rebuilt on next server startup)")


if __name__ == '__main__':
    asyncio.run(seed())
