"""
O2C Agent v2.0 — ChromaDB Semantic Layer
6 collections for vector storage and semantic retrieval.
"""

import chromadb
import logging
from chromadb.config import Settings as ChromaSettings
from config import settings

logger = logging.getLogger(__name__)

_client = None
_collections = {}

COLLECTION_NAMES = [
    "customers",        # Customer records for deduplication
    "orders",           # Order embeddings for similarity lookup
    "invoices",         # Invoice embeddings for cash app matching
    "dunning_history",  # Dunning communications history
    "dispute_evidence", # Dispute evidence documents
    "remittances",      # Payment remittance advices
]


def get_chromadb_client() -> chromadb.Client:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chromadb_persist_path,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        logger.info("ChromaDB persistent client initialized")
    return _client


def get_collection(name: str) -> chromadb.Collection:
    global _collections
    if name not in _collections:
        client = get_chromadb_client()
        _collections[name] = client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"}
        )
    return _collections[name]


async def init_collections():
    """Initialize all 6 ChromaDB collections on startup."""
    for name in COLLECTION_NAMES:
        col = get_collection(name)
        logger.info(f"ChromaDB collection '{name}' ready: {col.count()} documents")
    logger.info("All 6 ChromaDB collections initialized")


def get_customers_collection() -> chromadb.Collection:
    return get_collection("customers")


def get_orders_collection() -> chromadb.Collection:
    return get_collection("orders")


def get_invoices_collection() -> chromadb.Collection:
    return get_collection("invoices")


def get_dunning_collection() -> chromadb.Collection:
    return get_collection("dunning_history")


def get_dispute_evidence_collection() -> chromadb.Collection:
    return get_collection("dispute_evidence")


def get_remittances_collection() -> chromadb.Collection:
    return get_collection("remittances")
