"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Polling behavior
EMAIL_INTAKE_ENABLED: bool = _get_bool("EMAIL_INTAKE_ENABLED", True)
POLL_INTERVAL_MINUTES: int = _get_int("POLL_INTERVAL_MINUTES", 15)
MAX_EMAILS_PER_CYCLE: int = _get_int("MAX_EMAILS_PER_CYCLE", 25)

# Gmail
PROCESSED_LABEL: str = os.getenv("PROCESSED_LABEL", "o2c/processed")

# Gmail search filter (Gmail search-operator syntax). Defaults to the Primary
# inbox tab only, excluding Promotions/Social/Updates/Forums so newsletters and
# marketing mail are never fetched. The processed-label exclusion and the
# unread/inbox constraints are always appended in gmail_client, so set this to
# additional filters only — e.g. 'from:(*@customer.com OR *@partner.com)'.
GMAIL_SEARCH_FILTER: str = os.getenv(
    "GMAIL_SEARCH_FILTER",
    "category:primary -category:promotions -category:social "
    "-category:updates -category:forums",
)

# Gmail OAuth file locations. Default to the package directory so the files can
# live next to the code regardless of the current working directory.
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
GMAIL_CREDENTIALS_FILE: str = os.getenv(
    "GMAIL_CREDENTIALS_FILE", os.path.join(_PACKAGE_DIR, "credentials.json")
)
GMAIL_TOKEN_FILE: str = os.getenv(
    "GMAIL_TOKEN_FILE", os.path.join(_PACKAGE_DIR, "token.json")
)
GMAIL_CREDENTIALS_JSON: str = os.getenv("GMAIL_CREDENTIALS_JSON", "")
GMAIL_TOKEN_JSON: str = os.getenv("GMAIL_TOKEN_JSON", "")

# LLM confidence threshold for ambiguous classifications.
# The shared Ollama Cloud client is configured via the main backend config.
LLM_CONFIDENCE_THRESHOLD: float = _get_float("LLM_CONFIDENCE_THRESHOLD", 0.6)

# O2C backend (FastAPI) integration
O2C_API_BASE_URL: str = os.getenv("O2C_API_BASE_URL", "http://localhost:8000")
O2C_API_TIMEOUT: float = _get_float("O2C_API_TIMEOUT", 90.0)

# Friend's external agent (receives ORDER / PAYMENT / DISPUTE payloads after local processing)
FRIEND_AGENT_URL: str = os.getenv("FRIEND_AGENT_URL", "")  # e.g. http://192.168.x.x:9000
FRIEND_AGENT_TIMEOUT: float = _get_float("FRIEND_AGENT_TIMEOUT", 30.0)

# Storage
DB_PATH: str = os.getenv("DB_PATH", "intake_state.db")
