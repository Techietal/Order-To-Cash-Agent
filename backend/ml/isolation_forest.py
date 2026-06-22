"""
O2C Agent v2.0 — Isolation Forest (Unsupervised Anomaly Detection)
Used by: Agent 3 (Fraud Detection) for per-order anomaly scoring.
         Agent 11 (Anomaly Watchdog) for cross-order pattern detection.

NO training data required — fits on live event data at startup/runtime.
"""

import logging
import numpy as np
import joblib
from pathlib import Path
from typing import Dict, List, Any, Optional
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

MODEL_PATH = Path("./ml/models/isolation_forest.joblib")

_order_model: Optional[IsolationForest] = None
_watchdog_model: Optional[IsolationForest] = None


def _order_features(order: Dict[str, Any]) -> List[float]:
    """Extract numerical features for a single order."""
    return [
        float(order.get("total_amount_inr", 0)),
        float(order.get("quantity", 1)),
        float(order.get("unit_price_inr", 0)),
        float(order.get("avg_dso_days", 30)),
        float(order.get("missed_payments_12m", 0)),
        float(order.get("open_ar_balance_inr", 0)),
        float(order.get("account_age_months", 12)),
        1.0 if order.get("channel") == "email" else 0.0,
    ]


def get_order_isolation_forest(orders: Optional[List[Dict]] = None) -> IsolationForest:
    """Get or train the order-level Isolation Forest."""
    global _order_model
    if _order_model is not None:
        return _order_model
    if MODEL_PATH.exists():
        _order_model = joblib.load(MODEL_PATH)
        logger.info("Isolation Forest loaded from disk")
        return _order_model
    if orders:
        return train_order_isolation_forest(orders)
    # Default: create unfitted model (will be scored as 0 until trained)
    _order_model = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
    logger.warning("Isolation Forest created but not trained — fit on first batch")
    return _order_model


def train_order_isolation_forest(orders: List[Dict[str, Any]]) -> IsolationForest:
    """Fit Isolation Forest on a list of order dicts."""
    global _order_model
    if len(orders) < 10:
        logger.warning("Too few orders for Isolation Forest training (<10)")
        return get_order_isolation_forest()
    X = np.array([_order_features(o) for o in orders])
    _order_model = IsolationForest(n_estimators=200, contamination=0.05, random_state=42, n_jobs=-1)
    _order_model.fit(X)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(_order_model, MODEL_PATH)
    logger.info(f"Isolation Forest trained on {len(orders)} orders and saved")
    return _order_model


def score_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score a single order for anomaly.
    Returns: {'anomaly_score': float, 'anomaly_flag': bool, 'interpretation': str}
    
    Uses IsolationForest.decision_function():
      - Returns 0-centered score: negative = anomaly, positive = normal
      - threshold is 0 (offset = contamination level)
      - anomaly_flag = predict() == -1  (the model's own ground-truth label)
    """
    model = get_order_isolation_forest()
    features = np.array([_order_features(order)]).reshape(1, -1)
    try:
        # decision_function: positive = normal, negative = anomaly
        # More negative → more anomalous
        decision = float(model.decision_function(features)[0])
        # predict: -1 = anomaly, +1 = normal (uses contamination threshold internally)
        label = int(model.predict(features)[0])
        anomaly_flag = (label == -1)
        # Normalize decision score to 0-1 anomaly probability
        # decision is typically in range [-0.5, 0.5]
        # Map: decision = -0.5 → score = 1.0 (extreme anomaly)
        #       decision =  0.0 → score = 0.5 (borderline)
        #       decision =  0.5 → score = 0.0 (clearly normal)
        anomaly_score = max(0.0, min(1.0, 0.5 - decision))

        # Flag is the model's ground-truth label — use it as primary gate
        if not anomaly_flag:
            interpretation = "NORMAL"
        elif anomaly_score > 0.55:
            interpretation = "HIGH_ANOMALY"
        else:
            interpretation = "MODERATE"

        return {
            "raw_score": round(decision, 4),
            "anomaly_score": round(anomaly_score, 4),
            "anomaly_flag": anomaly_flag,
            "interpretation": interpretation,
        }
    except Exception as e:
        if "not fitted yet" in str(e):
            logger.info("Isolation Forest not yet fitted. Returning default score 0.0.")
        else:
            logger.warning(f"IF scoring issue: {e}")
        return {"raw_score": 0.0, "anomaly_score": 0.0, "anomaly_flag": False, "interpretation": "NORMAL"}
