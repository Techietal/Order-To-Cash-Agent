"""
O2C Agent v2.0 — GLiNER Zero-Shot NER + Groq LLM Evaluator
Model: urchade/gliner_medium-v2.1

Pipeline:
  1. GLiNER extracts entities locally (~150ms, no API cost)
  2. Groq evaluates the result, corrects mistakes, fills missing fields
  3. Merged result returned with source tags per field (gliner / groq / groq_corrected)

Used by: Agent 1 (Order Ingestion), Agent 4 (Disputes)
"""

import logging
from typing import List, Dict, Any
from config import settings

logger = logging.getLogger(__name__)

_model = None

ORDER_ENTITIES = [
    "product name",
    "item code or SKU",
    "quantity or number of units",
    "delivery date",
    "company name or customer name",
    "shipping address",
    "purchase order reference",
    "unit price",
]

# Entity types for Dispute emails (fallback to Groq for dispute)
DISPUTE_ENTITIES = [
    "invoice_reference",
    "claim_amount",
    "dispute_reason",
    "evidence_type",
    "contact_name",
]


def get_gliner_model():
    """Load GLiNER model once (lazy init)."""
    global _model
    if _model is None:
        from gliner import GLiNER
        logger.info(f"Loading GLiNER model: {settings.gliner_model}")
        _model = GLiNER.from_pretrained(settings.gliner_model)
        logger.info("GLiNER loaded — zero-shot NER, BERT-based, ~150ms CPU inference")
    return _model


def extract_order_entities(text: str, threshold: float = 0.35) -> Dict[str, Any]:
    """
    Extract order entities from unstructured email text.
    Returns dict of entity_type -> extracted_value.
    """
    try:
        model = get_gliner_model()
        entities = model.predict_entities(text, ORDER_ENTITIES, threshold=threshold)
        result = {}
        # Map verbose labels back to canonical keys
        label_map = {
            "product name": "product_name",
            "item code or SKU": "item_code",
            "quantity or number of units": "quantity",
            "delivery date": "delivery_date",
            "company name or customer name": "customer_name",
            "shipping address": "shipping_address",
            "purchase order reference": "order_reference",
            "unit price": "unit_price",
        }
        for ent in entities:
            label = label_map.get(ent["label"], ent["label"])
            value = ent["text"]
            score = ent.get("score", 0)
            if label not in result or score > result[label].get("confidence", 0):
                result[label] = {"value": value, "confidence": round(score, 4)}
        return result
    except Exception as e:
        logger.error(f"GLiNER extraction failed: {e}")
        return {}


def extract_order_entities_with_llm_backup(text: str, threshold: float = 0.35) -> Dict[str, Any]:
    """
    MAIN ENTRY POINT for order NER.
    Step 1: GLiNER extracts entities locally (fast, no API cost)
    Step 2: Groq evaluates the GLiNER result, corrects mistakes, fills missing fields
    Returns merged result with per-field source tags.
    """
    # Step 1 — GLiNER (always runs)
    gliner_result = extract_order_entities(text, threshold=threshold)
    logger.info(f"GLiNER found {len(gliner_result)} entities: {list(gliner_result.keys())}")

    # Step 2 — Groq evaluates and corrects
    try:
        from ml.groq_client import evaluate_and_correct_ner
        merged = evaluate_and_correct_ner(text, gliner_result)
        corrections = merged.get("_groq_corrections", [])
        if corrections:
            logger.info(f"Groq made {len(corrections)} correction(s): {corrections}")
        else:
            logger.info("Groq validated GLiNER result — no corrections needed")
        return merged
    except Exception as e:
        logger.warning(f"Groq NER evaluation unavailable ({e}), using GLiNER result only")
        return gliner_result


def extract_dispute_entities(text: str, threshold: float = 0.5) -> Dict[str, Any]:
    """
    Dispute NER — uses Groq directly (disputes are always free-form, messy emails).
    Falls back to GLiNER if Groq is unavailable.
    """
    try:
        from ml.groq_client import extract_dispute_entities_groq
        return extract_dispute_entities_groq(text)
    except Exception as e:
        logger.warning(f"Groq dispute NER unavailable ({e}), falling back to GLiNER")
        # GLiNER fallback
        try:
            model = get_gliner_model()
            entities = model.predict_entities(text, DISPUTE_ENTITIES, threshold=threshold)
            result = {}
            for ent in entities:
                result[ent["label"]] = {"value": ent["text"], "confidence": round(ent.get("score", 0), 4)}
            return result
        except Exception as e2:
            logger.error(f"GLiNER dispute fallback also failed: {e2}")
            return {}
