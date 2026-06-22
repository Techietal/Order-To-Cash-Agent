"""
O2C Agent v2.0 — Model Pre-Download & Warm-Up Script
=====================================================
Run this ONCE before starting the server for the first time.
Downloads and caches all required AI models so the app
starts instantly with zero cold-start delays.

Models downloaded:
  1. GLiNER medium-v2.1     ~780MB  (Order NER extraction)
  2. all-MiniLM-L6-v2        ~80MB  (ChromaDB embeddings + Cash App matching)

XGBoost / Prophet models are PLACEHOLDERS until the ML team trains them.
They use heuristic fallbacks automatically — no download needed.

Usage:
    python download_models.py
"""

import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SEPARATOR = "=" * 65


def banner(text: str):
    print(f"\n{SEPARATOR}")
    print(f"  {text}")
    print(SEPARATOR)


def check(name: str):
    print(f"  ✅ {name}")


def warn(name: str):
    print(f"  ⚠️  {name}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. GLiNER — Zero-Shot NER model for Order Ingestion (Agent 1)
# ─────────────────────────────────────────────────────────────────────────────
def download_gliner():
    banner("MODEL 1: GLiNER medium-v2.1  (~780 MB)")
    print("  Purpose : Agent 1 — extracts SKU, quantity, customer from emails")
    print("  Source  : HuggingFace urchade/gliner_medium-v2.1")
    print()

    try:
        from gliner import GLiNER
        logger.info("Downloading + loading GLiNER model (this may take 10–15 min on first run)...")
        t0 = time.time()
        model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
        elapsed = time.time() - t0
        logger.info(f"GLiNER ready in {elapsed:.1f}s")

        # Quick smoke test
        logger.info("Running smoke test on GLiNER...")
        entities = model.predict_entities(
            "Please order 20 Industrial Motors for Acme Corp.",
            ["product", "quantity", "customer"],
        )
        logger.info(f"Smoke test passed — extracted {len(entities)} entities: {entities}")
        check("GLiNER model downloaded and verified")
        return True
    except ImportError:
        warn("gliner package not installed. Run: pip install gliner")
        return False
    except Exception as e:
        warn(f"GLiNER download failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Sentence Transformers — Embeddings for ChromaDB + Cash App matching
# ─────────────────────────────────────────────────────────────────────────────
def download_embeddings():
    banner("MODEL 2: all-MiniLM-L6-v2  (~80 MB)")
    print("  Purpose : ChromaDB vector store + Cash Application invoice matching")
    print("  Source  : HuggingFace sentence-transformers/all-MiniLM-L6-v2")
    print()

    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Downloading + loading embedding model...")
        t0 = time.time()
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        elapsed = time.time() - t0
        logger.info(f"Embedding model ready in {elapsed:.1f}s")

        # Quick smoke test
        logger.info("Running smoke test on embeddings...")
        emb = model.encode("Invoice INV-001 for Acme Corp", normalize_embeddings=True)
        assert len(emb) == 384, f"Expected 384 dims, got {len(emb)}"
        logger.info(f"Smoke test passed — embedding dim: {len(emb)}")
        check("Embedding model downloaded and verified (384-dim)")
        return True
    except ImportError:
        warn("sentence-transformers not installed. Run: pip install sentence-transformers")
        return False
    except Exception as e:
        warn(f"Embedding download failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 3. Isolation Forest — Trains from scratch on startup (no download needed)
# ─────────────────────────────────────────────────────────────────────────────
def verify_isolation_forest():
    banner("MODEL 3: Isolation Forest  (trains at runtime — no download)")
    print("  Purpose : Anomaly scoring for orders (Agent 3 Fraud Detection)")
    print("  Source  : scikit-learn (fits on first order batch)")
    print()

    try:
        from sklearn.ensemble import IsolationForest
        import numpy as np
        model = IsolationForest(n_estimators=100, contamination=0.1, random_state=42)
        X_dummy = np.random.randn(50, 5)
        model.fit(X_dummy)
        score = model.score_samples(X_dummy[:1])
        logger.info(f"Isolation Forest smoke test passed — score: {score[0]:.4f}")
        check("Isolation Forest (scikit-learn) — ready, no download needed")
        return True
    except ImportError:
        warn("scikit-learn not installed. Run: pip install scikit-learn")
        return False
    except Exception as e:
        warn(f"Isolation Forest check failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 4. XGBoost Placeholders — no download, confirm package exists
# ─────────────────────────────────────────────────────────────────────────────
def verify_xgboost():
    banner("MODEL 4: XGBoost Fraud / Credit / Payment Delay  (PLACEHOLDERS)")
    print("  Purpose : Fraud prob, credit risk, payment delay prediction")
    print("  Status  : Using heuristic fallbacks until ML team trains real models")
    print()

    try:
        import xgboost as xgb
        logger.info(f"XGBoost {xgb.__version__} installed — placeholder models active")
        check(f"XGBoost {xgb.__version__} installed (models use heuristic placeholders)")
        return True
    except ImportError:
        warn("xgboost not installed. Run: pip install xgboost")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 5. Check Groq API key (LLM for dunning emails + dispute resolution)
# ─────────────────────────────────────────────────────────────────────────────
def verify_groq():
    banner("MODEL 5: Groq LLM API  (Collections + Disputes agents)")
    print("  Purpose : Groq llama-3.3-70b generates dunning emails, dispute summaries")
    print("  Source  : api.groq.com (cloud, no local download)")
    print()

    import os
    # Try loading from .env first
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    key = os.environ.get("GROQ_API_KEY", "")
    if key and key.startswith("gsk_"):
        check(f"GROQ_API_KEY set (starts with gsk_...{key[-6:]})")
        return True
    elif key:
        warn("GROQ_API_KEY is set but may be invalid (should start with 'gsk_')")
        return False
    else:
        warn("GROQ_API_KEY not set in .env — Collections & Disputes agents will use fallback text")
        print("       → Get a free key at: https://console.groq.com/keys")
        print("       → Add to backend/.env: GROQ_API_KEY=gsk_...")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     O2C Agent v2.0 — Model Pre-Download & Verification      ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print("This script downloads all AI models once so the server starts fast.")
    print("Total download: ~860 MB (GLiNER 780MB + MiniLM 80MB)")
    print()

    results = {
        "GLiNER NER":           download_gliner(),
        "Sentence Embeddings":  download_embeddings(),
        "Isolation Forest":     verify_isolation_forest(),
        "XGBoost (placeholders)": verify_xgboost(),
        "Groq API key":         verify_groq(),
    }

    banner("SUMMARY")
    all_ok = True
    for name, ok in results.items():
        status = "✅ READY" if ok else "⚠️  ACTION NEEDED"
        print(f"  {status:20s} {name}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("🚀  All models ready! You can now start the server:")
        print()
        print("    Terminal 1: uvicorn main:app --reload")
        print("    Terminal 2: python.exe -m celery -A workers.celery_worker worker --loglevel=info --pool=solo")
        print("    Terminal 3: cd ../frontend && npm run dev")
    else:
        print("⚠️   Some items need attention (see warnings above).")
        print("    The server will still work — optional items use fallbacks.")
        print()
        print("    Start the server whenever you are ready:")
        print("    Terminal 1: uvicorn main:app --reload")
    print()
