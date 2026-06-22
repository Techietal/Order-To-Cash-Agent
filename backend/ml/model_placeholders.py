"""
O2C Agent v2.0 — ML Model Placeholders
These models require training on REAL datasets before use.
Until trained models are provided, they return realistic mock scores
so the full pipeline can be tested end-to-end.

=============================================================================
TRAINING REQUIRED — TO BE DONE BY THE ML TEAM
=============================================================================

MODEL 1: XGBoost Fraud Classifier
  - Dataset: Kaggle Credit Card Fraud Detection
  - Link: https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud
  - Format: creditcard.csv (284,807 rows, 31 columns: V1-V28 PCA, Amount, Time, Class)
  - Target: Class (0=legitimate, 1=fraud)
  - Training: xgboost with SMOTE resampling (492 fraud vs 284K legit)
  - Metric target: AUROC >= 0.95
  - Output: fraud_xgboost.joblib

MODEL 2: XGBoost Credit Risk Scorer
  - Dataset: UCI Polish Companies Bankruptcy (5 annual datasets)
  - Link: https://archive.ics.uci.edu/dataset/365/polish+companies+bankruptcy+data
  - Format: 1year.arff through 5year.arff (64 financial ratio features, bankrupt flag)
  - Target: bankruptcy_flag (proxy for credit risk HIGH/MEDIUM/LOW)
  - Training: XGBoost 3-class classifier after bucketing
  - Metric target: Accuracy >= 85%
  - Output: credit_xgboost.joblib

MODEL 2B: Logistic Regression PD Model (Probability of Default)
  - Dataset: UCI Credit Card Default
  - Link: https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients
  - Format: default_of_credit_card_clients.xls (30,000 rows, 24 features)
  - Target: default.payment.next.month (0/1)
  - Training: LogisticRegression with StandardScaler, ECOA bias audit hook
  - Metric target: AUROC >= 0.78
  - Output: pd_model.joblib, pd_scaler.joblib

MODEL 3: XGBoost/LightGBM Payment Delay Predictor
  - Dataset: IBM Late Payment Histories (Kaggle)
  - Link: https://www.kaggle.com/datasets/rohitsahoo/sales-forecasting
  - Alternate: https://www.kaggle.com/datasets/saurabhshahane/predict-payment-of-invoice
  - Format: CSV with invoice_date, due_date, payment_date, amount, customer_features
  - Target (regression): days_to_pay / Target (binary): late_flag
  - Training: XGBoost regression + binary classifier
  - Metric target: RMSE <= 5 days on holdout
  - Output: payment_delay_xgb.joblib

MODEL 4: Prophet Demand Forecaster
  - Dataset: Kaggle M5 Forecasting — Walmart
  - Link: https://www.kaggle.com/competitions/m5-forecasting-accuracy/data
  - Format: sales_train_evaluation.csv + calendar.csv + sell_prices.csv
  - Training: Facebook Prophet per-SKU with weekly seasonality + regressors
  - Metric target: WRMSSE < 0.6 on validation window
  - Output: prophet_models/ (one .json per SKU)

=============================================================================
EXPECTED TRAINING DATA STRUCTURE (for each model)
See ML_Training_Guide.md in the data/ folder for complete column specs.
=============================================================================
"""

import logging
import random
import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
import joblib

logger = logging.getLogger(__name__)

MODELS_DIR = Path("./ml/models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════
# XGBoost Fraud Classifier — PLACEHOLDER
# ══════════════════════════════════════════════════════════════════════════

def load_fraud_model():
    """Load trained XGBoost fraud model if available."""
    model_path = MODELS_DIR / "fraud_xgboost.joblib"
    if model_path.exists():
        logger.info("Loading XGBoost fraud model from disk")
        return joblib.load(model_path)
    logger.warning("PLACEHOLDER: XGBoost fraud model not trained yet. Using mock scores.")
    return None


def predict_fraud(order_features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Predict fraud probability for an order.
    Returns realistic scores until real model is trained.
    
    order_features expected keys:
      - amount_inr: float
      - customer_age_months: int
      - avg_days_late: float
      - missed_payments: int
      - open_ar_ratio: float  (open_ar / credit_limit)
      - is_new_customer: bool
      - hour_of_day: int
      - channel: str
    """
    model = load_fraud_model()
    
    if model is not None:
        # Real XGBoost prediction — pass named DataFrame to match feature_names_in_
        X = pd.DataFrame([{
            "amount_inr":          float(order_features.get("amount_inr", 0)),
            "customer_age_months": float(order_features.get("customer_age_months", 12)),
            "avg_days_late":       float(order_features.get("avg_days_late", 0)),
            "missed_payments":     float(order_features.get("missed_payments", 0)),
            "open_ar_ratio":       float(order_features.get("open_ar_ratio", 0)),
            "is_new_customer":     1.0 if order_features.get("is_new_customer") else 0.0,
            "hour_of_day":         float(order_features.get("hour_of_day", 12)),
            "channel":             float({"email": 0, "edi": 1, "api": 2, "portal": 3, "csv_upload": 4}.get(
                                       str(order_features.get("channel", "api")), 2)),
        }])
        prob = float(model.predict_proba(X)[0][1])


        return {
            "fraud_probability": round(prob, 4),
            "fraud_verdict": "FRAUD" if prob > 0.7 else ("REVIEW" if prob > 0.4 else "CLEAR"),
            "model": "xgboost_trained",
            "shap_top_feature": None,
        }
    
    # PLACEHOLDER — heuristic mock that mimics realistic fraud patterns
    amount = float(order_features.get("amount_inr", 0))
    is_new = order_features.get("is_new_customer", False)
    missed = int(order_features.get("missed_payments", 0))
    
    base_prob = 0.03  # 3% base fraud rate
    if is_new and amount > 100000:
        base_prob += 0.25
    if missed > 3:
        base_prob += 0.15
    if amount > 500000:
        base_prob += 0.10
    
    prob = min(0.95, max(0.01, base_prob + random.gauss(0, 0.03)))
    
    return {
        "fraud_probability": round(prob, 4),
        "fraud_verdict": "FRAUD" if prob > 0.7 else ("REVIEW" if prob > 0.4 else "CLEAR"),
        "model": "placeholder_heuristic",
        "warning": "PLACEHOLDER: Train XGBoost on Kaggle Credit Card Fraud dataset for production use",
    }


def _fraud_features(d: Dict[str, Any]) -> List[float]:
    """Feature vector for fraud model (mirrors Kaggle credit card fraud features)."""
    return [
        float(d.get("amount_inr", 0)),
        float(d.get("customer_age_months", 12)),
        float(d.get("avg_days_late", 0)),
        float(d.get("missed_payments", 0)),
        float(d.get("open_ar_ratio", 0)),
        1.0 if d.get("is_new_customer") else 0.0,
        float(d.get("hour_of_day", 12)),
        {"email": 0, "edi": 1, "api": 2, "portal": 3, "csv_upload": 4}.get(d.get("channel", "api"), 0),
    ]


# ══════════════════════════════════════════════════════════════════════════
# XGBoost Credit Risk Scorer — PLACEHOLDER
# ══════════════════════════════════════════════════════════════════════════

def load_credit_model():
    """Load trained XGBoost credit risk model if available."""
    model_path = MODELS_DIR / "credit_xgboost.joblib"
    if model_path.exists():
        return joblib.load(model_path)
    return None


def load_pd_model():
    """Load trained Probability of Default logistic regression model."""
    model_path = MODELS_DIR / "pd_model.joblib"
    scaler_path = MODELS_DIR / "pd_scaler.joblib"
    if model_path.exists() and scaler_path.exists():
        return joblib.load(model_path), joblib.load(scaler_path)
    return None, None


def predict_credit_risk(customer_features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Predict credit risk class (LOW/MEDIUM/HIGH) and PD score for a customer.
    
    customer_features expected keys:
      - order_value_inr: float
      - credit_limit_inr: float
      - open_ar_balance_inr: float
      - avg_days_late: float
      - payment_tier: int (1-4)
      - missed_payment_count: int
      - account_age_months: int
      - industry_segment: str
    """
    credit_model = load_credit_model()
    pd_model, pd_scaler = load_pd_model()

    # Build named DataFrame — matches feature_names_in_ for both credit + PD models
    cl = float(customer_features.get("credit_limit_inr", 100000))
    industry_map = {
        "Manufacturing": 0, "Retail": 1, "FMCG": 2, "Pharma": 3,
        "Logistics": 4, "IT Services": 5, "Construction": 6, "Automotive": 7,
    }
    X_df = pd.DataFrame([{
        "order_to_limit":       float(customer_features.get("order_value_inr", 0)) / max(cl, 1),
        "ar_to_limit":          float(customer_features.get("open_ar_balance_inr", 0)) / max(cl, 1),
        "avg_days_late":        float(customer_features.get("avg_days_late", 0)),
        "missed_payment_count": float(customer_features.get("missed_payment_count", 0)),
        "account_age_months":   float(customer_features.get("account_age_months", 12)),
        "industry_segment":     float(industry_map.get(customer_features.get("industry_segment", "Retail"), 0)),
        "payment_tier":         float(customer_features.get("payment_tier", 2)),
    }])

    if credit_model is not None:
        credit_class_idx = int(credit_model.predict(X_df)[0])
        credit_classes = ["LOW", "MEDIUM", "HIGH"]
        credit_class = credit_classes[min(credit_class_idx, 2)]
        credit_score = float(credit_model.predict_proba(X_df)[0][credit_class_idx])
    else:
        # PLACEHOLDER
        tier = customer_features.get("credit_tier", "B")
        tier_map = {"A": ("LOW", 0.85), "B": ("MEDIUM", 0.65), "C": ("HIGH", 0.40), "D": ("HIGH", 0.15)}
        credit_class, credit_score = tier_map.get(tier, ("MEDIUM", 0.60))

    if pd_model is not None and pd_scaler is not None:
        X_scaled = pd_scaler.transform(X_df)   # DataFrame keeps column names → no warning
        pd_score = float(pd_model.predict_proba(X_scaled)[0][1])
    else:
        # PLACEHOLDER PD based on tier + missed payments
        tier = customer_features.get("credit_tier", "B")
        missed = customer_features.get("missed_payment_count", 0)
        base_pd = {"A": 0.02, "B": 0.07, "C": 0.18, "D": 0.40}.get(tier, 0.10)
        pd_score = min(0.95, base_pd + missed * 0.05)
    
    return {
        "credit_risk_class": credit_class,
        "credit_score": round(credit_score, 4),
        "pd_score": round(pd_score, 4),
        "recommended_credit_limit_multiplier": 1.2 if credit_class == "LOW" else (1.0 if credit_class == "MEDIUM" else 0.7),
        "model": "xgboost_trained" if credit_model else "placeholder_heuristic",
    }


def _credit_features(d: Dict[str, Any]) -> List[float]:
    """Feature vector for credit model (mirrors UCI Polish Companies features)."""
    cl = float(d.get("credit_limit_inr", 100000))
    return [
        float(d.get("order_value_inr", 0)) / max(cl, 1),  # order to limit ratio
        float(d.get("open_ar_balance_inr", 0)) / max(cl, 1),
        float(d.get("avg_days_late", 0)),
        float(d.get("missed_payment_count", 0)),
        float(d.get("account_age_months", 12)),
        {"Manufacturing": 0, "Retail": 1, "FMCG": 2, "Pharma": 3, "Logistics": 4,
         "IT Services": 5, "Construction": 6, "Automotive": 7}.get(d.get("industry_segment", "Retail"), 0),
        float(d.get("payment_tier", 2)),
    ]


# ══════════════════════════════════════════════════════════════════════════
# XGBoost Payment Delay Predictor — PLACEHOLDER
# ══════════════════════════════════════════════════════════════════════════

def load_payment_delay_model():
    """Load trained XGBoost payment delay model."""
    model_path = MODELS_DIR / "payment_delay_xgb.joblib"
    if model_path.exists():
        return joblib.load(model_path)
    return None


def predict_payment_delay(invoice_features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Predict payment delay for an invoice.
    
    invoice_features expected keys:
      - invoice_amount_inr: float
      - payment_terms_days: int
      - customer_avg_days_late: float
      - customer_missed_payments: int
      - open_ar_ratio: float
      - account_age_months: int
      - industry_segment: str
      - promise_to_pay: bool
      - quarter: int (1-4)
    
    Returns:
      - late_probability: float (0-1)
      - predicted_days_to_pay: int
      - bucket: str (GREEN/AMBER/RED)
    """
    model = load_payment_delay_model()
    
    if model is not None:
        # Named DataFrame — matches feature_names_in_ of payment_delay_xgb
        X = pd.DataFrame([{
            "invoice_amount_inr":        float(invoice_features.get("invoice_amount_inr", 0)),
            "payment_terms_days":        float(invoice_features.get("payment_terms_days", 30)),
            "customer_avg_days_late":    float(invoice_features.get("customer_avg_days_late", 0)),
            "customer_missed_payments":  float(invoice_features.get("customer_missed_payments", 0)),
            "open_ar_ratio":             float(invoice_features.get("open_ar_ratio", 0)),
            "account_age_months":        float(invoice_features.get("account_age_months", 12)),
            "quarter":                   float(invoice_features.get("quarter", 1)),
            "promise_to_pay":            1.0 if invoice_features.get("promise_to_pay") else 0.0,
        }])
        # Regressor: predicts days late (positive = late, negative = early)
        days_late = float(model.predict(X)[0])
        days_to_pay = max(0, round(days_late))
        # Derive late probability from predicted days
        late_prob = float(model.predict_proba(X)[0][1]) if hasattr(model, 'predict_proba') else min(0.95, max(0.0, days_late / 30.0))
        return {
            "late_probability":      round(late_prob, 4),
            "predicted_days_to_pay": days_to_pay,
            "bucket": _get_bucket(late_prob, days_to_pay, invoice_features.get("payment_terms_days", 30)),
            "model": "xgboost_trained",
        }
    
    # PLACEHOLDER
    avg_late = float(invoice_features.get("customer_avg_days_late", 5))
    missed = int(invoice_features.get("customer_missed_payments", 0))
    ptp = bool(invoice_features.get("promise_to_pay", False))
    terms = int(invoice_features.get("payment_terms_days", 30))
    
    predicted_days = max(0, terms + avg_late + missed * 3 + random.gauss(0, 3))
    late_prob = min(0.95, max(0.05, (predicted_days - terms) / 30 + 0.1))
    if ptp:
        late_prob *= 0.6
    
    return {
        "late_probability": round(late_prob, 4),
        "predicted_days_to_pay": round(predicted_days, 1),
        "bucket": _get_bucket(late_prob, predicted_days, terms),
        "model": "placeholder_heuristic",
        "warning": "PLACEHOLDER: Train XGBoost on IBM Late Payment Histories (Kaggle) for production use",
    }


def _payment_features(d: Dict[str, Any]) -> List[float]:
    return [
        float(d.get("invoice_amount_inr", 0)),
        float(d.get("payment_terms_days", 30)),
        float(d.get("customer_avg_days_late", 0)),
        float(d.get("customer_missed_payments", 0)),
        float(d.get("open_ar_ratio", 0)),
        float(d.get("account_age_months", 12)),
        float(d.get("quarter", 1)),
        1.0 if d.get("promise_to_pay") else 0.0,
    ]


def _get_bucket(late_prob: float, days: float, terms: int) -> str:
    if late_prob < 0.35 and days <= terms:
        return "GREEN"
    elif late_prob < 0.65:
        return "AMBER"
    else:
        return "RED"


# ══════════════════════════════════════════════════════════════════════════
# Prophet Demand Forecaster — PLACEHOLDER
# ══════════════════════════════════════════════════════════════════════════

def predict_demand_forecast(sku_id: str, days: int = 30) -> Dict[str, Any]:
    """
    Predict 30-day demand forecast for a SKU.
    Uses Prophet if trained model exists + prophet package installed.
    Falls back to realistic mock if prophet package not installed.
    
    Prophet model per-SKU is trained on M5 Forecasting dataset.
    Training script: ml/train_prophet.py
    """
    model_path = MODELS_DIR / f"prophet_{sku_id}.json"
    
    if model_path.exists():
        try:
            from prophet.serialize import model_from_json
            # model_from_json expects a JSON *string*, not a dict
            with open(model_path, "r") as f:
                model = model_from_json(f.read())   # pass raw string, not json.load()
            future = model.make_future_dataframe(periods=days)
            forecast = model.predict(future)
            last_30 = forecast.tail(days)
            return {
                "sku_id": sku_id,
                "forecast_days": days,
                "daily_forecast": last_30[["ds", "yhat", "yhat_lower", "yhat_upper"]].to_dict("records"),
                "total_demand_30d": round(float(last_30["yhat"].sum()), 1),
                "model": "prophet_trained",
            }
        except ModuleNotFoundError:
            logger.warning("prophet package not installed — returning mock forecast. Install: pip install prophet")
            # Model file exists, so report it as ready-but-needs-package
            base = random.randint(10, 40)
            daily = [max(0, base + random.gauss(0, base * 0.1)) for _ in range(days)]
            return {
                "sku_id": sku_id,
                "forecast_days": days,
                "daily_forecast": [{"day": i+1, "yhat": round(v, 1)} for i, v in enumerate(daily)],
                "total_demand_30d": round(sum(daily), 1),
                "model": "prophet_model_ready_install_package",
                "note": f"Trained model exists at {model_path.name} — run: pip install prophet",
            }
    
    # PLACEHOLDER — realistic seasonal mock (no model file at all)
    base = random.randint(5, 50)
    daily = [max(0, base + random.gauss(0, base * 0.15)) for _ in range(days)]
    return {
        "sku_id": sku_id,
        "forecast_days": days,
        "daily_forecast": [{"day": i+1, "yhat": round(v, 1)} for i, v in enumerate(daily)],
        "total_demand_30d": round(sum(daily), 1),
        "model": "placeholder_mock",
        "warning": "PLACEHOLDER: Train Prophet on M5 Forecasting (Kaggle) for production use",
    }


# ══════════════════════════════════════════════════════════════════════════
# k-means Customer Segmentation — Fits at runtime (no labeled data needed)
# ══════════════════════════════════════════════════════════════════════════

_kmeans_model = None

SEGMENT_LABELS = {0: "Premium", 1: "Standard", 2: "At-Risk", 3: "Problem"}


def get_kmeans_model(customers: Optional[List[Dict]] = None):
    """Get or train k-means segmentation model. Always loads fresh from disk."""
    global _kmeans_model
    model_path = MODELS_DIR / "kmeans_segmentation.joblib"
    if model_path.exists():
        _kmeans_model = joblib.load(model_path)
        return _kmeans_model
    if customers:
        return train_kmeans(customers)
    from sklearn.cluster import KMeans
    _kmeans_model = KMeans(n_clusters=4, random_state=42, n_init=10)
    return _kmeans_model


def train_kmeans(customers: List[Dict[str, Any]]):
    """Train k-means on customer AR features."""
    global _kmeans_model
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    if len(customers) < 4:
        logger.warning(f"K-Means needs >= 4 customers, got {len(customers)}. Skipping.")
        return None

    # Build feature matrix: [ar_balance, dso, missed_payments, credit_limit, account_age]
    X = np.array([
        [
            float(c.get("open_ar_balance_inr", 0)),
            float(c.get("avg_dso_days", 30)),
            float(c.get("missed_payments_12m", 0)),
            float(c.get("credit_limit_inr", 100000)),
            float(c.get("account_age_months", 12)),
        ]
        for c in customers
    ])
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    n_clusters = min(4, len(customers))
    _kmeans_model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    _kmeans_model.fit(X_scaled)

    # Compute risk score on original-scale cluster centers for interpretability.
    # Risk increases with: higher AR balance, higher DSO, more missed payments
    # Risk decreases with: higher credit limit, longer account age (loyalty)
    centers_original = scaler.inverse_transform(_kmeans_model.cluster_centers_)
    # Normalize each feature to 0-1 range for fair weighting
    feature_ranges = X.max(axis=0) - X.min(axis=0)
    feature_ranges[feature_ranges == 0] = 1  # avoid divide-by-zero
    centers_norm = (centers_original - X.min(axis=0)) / feature_ranges

    # Composite risk score (higher = riskier):
    # +balance (normalized), +DSO (normalized), +missed_payments*2 (normalized)
    # -credit_limit (normalized), -account_age (normalized)
    risk_scores = (
        centers_norm[:, 0]       # AR balance: high = risky
        + centers_norm[:, 1]     # DSO: high = slow payer = risky
        + centers_norm[:, 2] * 2 # missed_payments: strongest risk signal
        - centers_norm[:, 3]     # credit_limit: high = trusted = less risky
        - centers_norm[:, 4]     # account_age: veteran customer = less risky
    )

    # Sort cluster IDs from lowest risk → highest risk
    sorted_by_risk = np.argsort(risk_scores)
    # Map raw cluster ID → segment rank (0=Premium, 1=Standard, 2=At-Risk, 3=Problem)
    cluster_mapping = {int(sorted_by_risk[i]): i for i in range(n_clusters)}

    logger.info(f"K-Means trained on {len(customers)} customers. Risk scores: {risk_scores}. Mapping: {cluster_mapping}")
    joblib.dump((_kmeans_model, scaler, cluster_mapping), MODELS_DIR / "kmeans_segmentation.joblib")
    return _kmeans_model, scaler, cluster_mapping


def predict_customer_segment(customer: Dict[str, Any]) -> Dict[str, Any]:
    """Predict customer segment label."""
    model_data = get_kmeans_model()
    if model_data is None:
        tier = customer.get("credit_tier", "B")
        segment = {"A": "Premium", "B": "Standard", "C": "At-Risk", "D": "Problem"}.get(tier, "Standard")
        return {"segment": segment, "cluster_id": -1}

    if isinstance(model_data, tuple) and len(model_data) == 3:
        model, scaler, mapping = model_data
    elif isinstance(model_data, tuple) and len(model_data) == 2:
        model, scaler = model_data
        mapping = {0: 0, 1: 1, 2: 2, 3: 3}
    else:
        model, scaler, mapping = model_data, None, {0: 0, 1: 1, 2: 2, 3: 3}

    features = np.array([[
        float(customer.get("open_ar_balance_inr", 0)),
        float(customer.get("avg_dso_days", 30)),
        float(customer.get("missed_payments_12m", 0)),
        float(customer.get("credit_limit_inr", 100000)),
        float(customer.get("account_age_months", 12)),
    ]])

    if scaler is not None:
        features = scaler.transform(features)

    try:
        raw_cluster = int(model.predict(features)[0])
        ranked_cluster = mapping.get(raw_cluster, 1)
        segment = SEGMENT_LABELS.get(ranked_cluster, "Standard")
        return {"segment": segment, "cluster_id": raw_cluster}
    except Exception as e:
        logger.warning(f"K-Means predict failed: {e}, falling back to credit_tier")
        tier = customer.get("credit_tier", "B")
        segment = {"A": "Premium", "B": "Standard", "C": "At-Risk", "D": "Problem"}.get(tier, "Standard")
        return {"segment": segment, "cluster_id": 1}


