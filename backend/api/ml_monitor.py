"""
O2C Agent v2.0 — ML Model Monitor API
Reports real model status based on actual .joblib file presence + metadata.
"""
from fastapi import APIRouter, Depends
from pathlib import Path
from api.staff_deps import require_role

router = APIRouter()

MODELS_DIR = Path("ml/models")


def _model_status(filename: str) -> dict:
    """Check if a model file exists and return its size/status."""
    path = MODELS_DIR / filename
    if path.exists():
        size_kb = round(path.stat().st_size / 1024, 1)
        return {"status": "trained", "file": filename, "size_kb": size_kb}
    return {"status": "placeholder", "file": filename, "size_kb": 0}


@router.get("/models")
async def list_models(staff=Depends(require_role(["admin"]))):
    """Live model registry — status reflects actual trained .joblib files."""
    gliner_status = "active"  # always loaded at startup
    embeddings_status = "active"

    fraud_meta   = _model_status("fraud_xgboost.joblib")
    credit_meta  = _model_status("credit_xgboost.joblib")
    pd_meta      = _model_status("pd_model.joblib")
    payment_meta = _model_status("payment_delay_xgb.joblib")
    if_meta      = _model_status("isolation_forest.joblib")
    kmeans_meta  = _model_status("kmeans_segmentation.joblib")

    # Prophet: check how many SKU models are available
    prophet_files = list(MODELS_DIR.glob("prophet_*.json"))
    prophet_status = "trained" if prophet_files else "placeholder"

    return {"models": [
        {
            "name": "GLiNER NER (Agent 1)",
            "type": "zero_shot_ner",
            "status": gliner_status,
            "source": "HuggingFace: urchade/gliner_medium-v2.1",
            "role": "Extracts order entities from emails — no training data required",
        },
        {
            "name": "all-MiniLM-L6-v2 (Embeddings)",
            "type": "embedding",
            "status": embeddings_status,
            "source": "HuggingFace: sentence-transformers",
            "role": "Customer record deduplication, invoice semantic search",
        },
        {
            "name": "Isolation Forest (Agent 3/11)",
            "type": "unsupervised_anomaly",
            "status": if_meta["status"],
            "size_kb": if_meta["size_kb"],
            "source": "scikit-learn — trained on live order data at startup",
            "role": "Per-order anomaly scoring for fraud pipeline",
        },
        {
            "name": "k-means Segmentation (Agent 8)",
            "type": "unsupervised_clustering",
            "status": kmeans_meta["status"],
            "size_kb": kmeans_meta["size_kb"],
            "source": "scikit-learn — trained on customer AR features at startup",
            "role": "Customer segmentation for targeted dunning strategy",
        },
        {
            "name": "XGBoost Fraud Classifier (Agent 3)",
            "type": "supervised_classifier",
            "status": fraud_meta["status"],
            "size_kb": fraud_meta["size_kb"],
            "dataset": "Kaggle Credit Card Fraud Detection",
            "dataset_link": "https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud",
            "role": "Fraud probability for every new order",
        },
        {
            "name": "XGBoost Credit Scorer (Agent 2)",
            "type": "supervised_classifier",
            "status": credit_meta["status"],
            "size_kb": credit_meta["size_kb"],
            "dataset": "UCI Polish Companies Bankruptcy",
            "dataset_link": "https://archive.ics.uci.edu/dataset/365",
            "role": "Credit risk class (LOW/MEDIUM/HIGH) for every customer",
        },
        {
            "name": "Logistic Regression PD Model (Agent 2)",
            "type": "supervised_regression",
            "status": pd_meta["status"],
            "size_kb": pd_meta["size_kb"],
            "dataset": "UCI Credit Card Default",
            "dataset_link": "https://archive.ics.uci.edu/dataset/350",
            "role": "Probability of Default score per customer",
        },
        {
            "name": "XGBoost Payment Delay (Agent 7)",
            "type": "supervised_regression",
            "status": payment_meta["status"],
            "size_kb": payment_meta["size_kb"],
            "dataset": "Kaggle Invoice Payment Prediction",
            "dataset_link": "https://www.kaggle.com/datasets/saurabhshahane/predict-payment-of-invoice",
            "role": "Predicts days-to-pay per open invoice for collections prioritization",
        },
        {
            "name": f"Prophet Demand Forecast (Agent 4) — {len(prophet_files)} SKUs",
            "type": "time_series",
            "status": prophet_status,
            "sku_count": len(prophet_files),
            "dataset": "Kaggle M5 Forecasting (Walmart)",
            "dataset_link": "https://www.kaggle.com/competitions/m5-forecasting-accuracy",
            "role": "30-day demand forecast per SKU for ATP/inventory agent",
        },
    ]}
