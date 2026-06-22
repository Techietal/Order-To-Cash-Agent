"""
O2C Agent v2.0 — Embedding Model (Pre-trained, HuggingFace)
all-MiniLM-L6-v2 — 384-dim local embeddings, no API call needed.
Used for: ChromaDB vector storage + Cash Application payment-invoice matching.
"""

import logging
from typing import List
from functools import lru_cache
from config import settings

logger = logging.getLogger(__name__)

_model = None


def get_embedding_model():
    """Load embedding model once (lazy init)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading embedding model: {settings.embeddings_model}")
        _model = SentenceTransformer(settings.embeddings_model)
        logger.info("Embedding model loaded — 384-dim, ~80MB, CPU inference")
    return _model


def embed_text(text: str) -> List[float]:
    """Embed a single text string."""
    model = get_embedding_model()
    return model.encode(text, normalize_embeddings=True).tolist()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Batch embed multiple texts."""
    model = get_embedding_model()
    return model.encode(texts, normalize_embeddings=True, batch_size=32).tolist()

def compute_similarity(text1: str, text2: str) -> float:
    """Compute cosine similarity between two texts (0 to 1)."""
    import numpy as np
    model = get_embedding_model()
    embs = model.encode([text1, text2], normalize_embeddings=True)
    return float(np.dot(embs[0], embs[1]))
