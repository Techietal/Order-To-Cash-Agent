"""Full ML model audit script — tests all 7 model categories."""
import sys, os
os.chdir('backend')
sys.path.insert(0, '.')

from pathlib import Path
MODELS_DIR = Path('ml/models')

print('=' * 60)
print('  O2C ML MODEL STATUS AUDIT')
print('=' * 60)

print('\n[FILES IN ml/models/]')
for f in sorted(MODELS_DIR.iterdir()):
    print(f'  {f.name:<50} {f.stat().st_size/1024:>8.1f} KB')

# ── 1. Fraud XGBoost ──────────────────────────────────────────
print('\n[1] FRAUD XGBOOST (binary:logistic — trained on Kaggle CC Fraud)')
from ml.model_placeholders import predict_fraud

r1a = predict_fraud({
    'amount_inr': 50000, 'customer_age_months': 24, 'avg_days_late': 5,
    'missed_payments': 0, 'open_ar_ratio': 0.3, 'is_new_customer': False,
    'hour_of_day': 10, 'channel': 'portal'
})
print(f'  Normal order   prob={r1a["fraud_probability"]:.4f}  verdict={r1a["fraud_verdict"]}  model={r1a["model"]}')

r1b = predict_fraud({
    'amount_inr': 500000, 'customer_age_months': 3, 'avg_days_late': 45,
    'missed_payments': 5, 'open_ar_ratio': 0.9, 'is_new_customer': True,
    'hour_of_day': 2, 'channel': 'email'
})
print(f'  High-risk order prob={r1b["fraud_probability"]:.4f}  verdict={r1b["fraud_verdict"]}  model={r1b["model"]}')

# ── 2. Credit XGBoost ─────────────────────────────────────────
print('\n[2] CREDIT XGBOOST (multi:softprob 3-class — UCI Polish Companies)')
from ml.model_placeholders import predict_credit_risk

r2a = predict_credit_risk({
    'order_value_inr': 50000, 'credit_limit_inr': 1000000,
    'open_ar_balance_inr': 100000, 'avg_days_late': 2,
    'missed_payment_count': 0, 'account_age_months': 48,
    'industry_segment': 'Manufacturing', 'payment_tier': 1, 'credit_tier': 'A'
})
print(f'  Tier A  class={r2a["credit_risk_class"]}  pd={r2a["pd_score"]:.4f}  model={r2a["model"]}')

r2b = predict_credit_risk({
    'order_value_inr': 180000, 'credit_limit_inr': 200000,
    'open_ar_balance_inr': 150000, 'avg_days_late': 30,
    'missed_payment_count': 4, 'account_age_months': 6,
    'industry_segment': 'Retail', 'payment_tier': 4, 'credit_tier': 'D'
})
print(f'  Tier D  class={r2b["credit_risk_class"]}  pd={r2b["pd_score"]:.4f}  model={r2b["model"]}')

# ── 3. Payment Delay XGBoost ──────────────────────────────────
print('\n[3] PAYMENT DELAY XGBOOST (reg:squarederror — IBM Late Payment Histories)')
from ml.model_placeholders import predict_payment_delay

r3a = predict_payment_delay({
    'invoice_amount_inr': 50000, 'payment_terms_days': 30,
    'customer_avg_days_late': 2, 'customer_missed_payments': 0,
    'open_ar_ratio': 0.2, 'account_age_months': 48, 'quarter': 2, 'promise_to_pay': False
})
print(f'  Good payer  prob={r3a["late_probability"]:.4f}  days={r3a["predicted_days_to_pay"]}  bucket={r3a["bucket"]}  model={r3a["model"]}')

r3b = predict_payment_delay({
    'invoice_amount_inr': 200000, 'payment_terms_days': 30,
    'customer_avg_days_late': 40, 'customer_missed_payments': 3,
    'open_ar_ratio': 0.85, 'account_age_months': 6, 'quarter': 4, 'promise_to_pay': False
})
print(f'  Bad payer   prob={r3b["late_probability"]:.4f}  days={r3b["predicted_days_to_pay"]}  bucket={r3b["bucket"]}  model={r3b["model"]}')

# ── 4. Prophet ────────────────────────────────────────────────
print('\n[4] PROPHET DEMAND FORECAST (Facebook Prophet — trained on M5 Walmart data)')
prophet_files = list(Path('ml/models').glob('prophet_*.json'))
print(f'  Trained .json model files found: {len(prophet_files)}')
for pf in prophet_files:
    print(f'    {pf.name}  {pf.stat().st_size/1024:.1f} KB')
try:
    from ml.model_placeholders import predict_demand_forecast
    for sku in ['SKU-001', 'SKU-002']:
        r = predict_demand_forecast(sku, days=30)
        print(f'  {sku}  total_30d={r["total_demand_30d"]:.1f}  model={r["model"]}')
except ModuleNotFoundError as e:
    print(f'  Prophet package not installed ({e}) — install with: pip install prophet')
    print(f'  NOTE: {len(prophet_files)} pre-trained .json models ARE ready on disk — will load when prophet is installed')

# ── 5. Isolation Forest ───────────────────────────────────────
print('\n[5] ISOLATION FOREST (scikit-learn — 200 estimators, retrained on startup)')
from ml.isolation_forest import score_order, get_order_isolation_forest
model = get_order_isolation_forest()
fitted = hasattr(model, 'estimators_')
print(f'  Model fitted on startup: {fitted}')
r5a = score_order({'total_amount_inr': 50000, 'quantity': 5, 'unit_price_inr': 10000,
                   'avg_dso_days': 30, 'missed_payments_12m': 0, 'open_ar_balance_inr': 50000,
                   'account_age_months': 24, 'channel': 'portal'})
print(f'  Normal order   score={r5a["anomaly_score"]:.4f}  flag={r5a["anomaly_flag"]}  {r5a["interpretation"]}')
r5b = score_order({'total_amount_inr': 5000000, 'quantity': 500, 'unit_price_inr': 10000,
                   'avg_dso_days': 90, 'missed_payments_12m': 5, 'open_ar_balance_inr': 800000,
                   'account_age_months': 1, 'channel': 'email'})
print(f'  Anomalous order score={r5b["anomaly_score"]:.4f}  flag={r5b["anomaly_flag"]}  {r5b["interpretation"]}')

# ── 6. k-means ────────────────────────────────────────────────
print('\n[6] K-MEANS SEGMENTATION (4 clusters — fits on live customer AR data)')
from ml.model_placeholders import predict_customer_segment
r6a = predict_customer_segment({'open_ar_balance_inr': 0, 'avg_dso_days': 28, 'missed_payments_12m': 0,
                                'credit_limit_inr': 1000000, 'account_age_months': 60})
print(f'  Premium  segment={r6a["segment"]}  cluster={r6a["cluster_id"]}')
r6b = predict_customer_segment({'open_ar_balance_inr': 180000, 'avg_dso_days': 75, 'missed_payments_12m': 4,
                                'credit_limit_inr': 200000, 'account_age_months': 6})
print(f'  At-Risk  segment={r6b["segment"]}  cluster={r6b["cluster_id"]}')

# ── 7. Sentence Transformer ───────────────────────────────────
print('\n[7] ALL-MINILM-L6-v2 EMBEDDINGS (384-dim, 80MB, pre-trained HuggingFace)')
from ml.embeddings import compute_similarity, embed_text
emb = embed_text('Invoice INV-123 amount 50000 INR')
print(f'  Embedding dim: {len(emb)}')
s_good = compute_similarity(
    'Payment for Invoice INV-123 amount 50000 INR from Jhansi Logistics',
    'Invoice INV-123 for customer CUST-0002 amount 50000 INR due 2026-07-01'
)
s_bad = compute_similarity(
    'Random bank transfer REF-9999 no invoice number',
    'Invoice INV-123 for customer CUST-0002 amount 50000 INR due 2026-07-01'
)
print(f'  Good remittance match sim: {s_good:.3f}  (threshold: 0.78 for auto-post)')
print(f'  Bad  remittance match sim: {s_bad:.3f}  (would route to HITL)')

print()
print('=' * 60)
print('  AUDIT COMPLETE')
print('=' * 60)
