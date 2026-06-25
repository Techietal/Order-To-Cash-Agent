"""
O2C Agent v2.0 — Application Configuration
Uses pydantic-settings for type-safe env var loading.
"""

from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    frontend_url: str = "http://localhost:5173"
    log_level: str = "INFO"

    # PostgreSQL
    database_url: str = ""  # Full DSN takes priority when set (e.g. Neon cloud)
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "o2c_agent"
    postgres_user: str = "o2c_admin"
    postgres_password: str = "changeme"
    postgres_ssl: str = ""  # e.g. 'require' for cloud DBs like Neon

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def asyncpg_dsn(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # ChromaDB
    chromadb_host: str = "localhost"
    chromadb_port: int = 8001
    chromadb_persist_path: str = "./chroma_data"

    # ── LLM provider (OpenAI-compatible) ──────────────────────────────────────
    # Only Ollama Cloud is supported; other providers are disabled.
    llm_provider: str = "ollama_cloud"

    # OpenRouter (one key → hundreds of models, many free-tier; full tool-calling)
    # Get a free key at https://openrouter.ai/keys — no credit card required.
    # Append :free to any model id for the free tier (rate-limited, no billing).
    # Ollama Cloud (remote GPU models, OpenAI-compatible; free tier, tool-calling)
    # Create a key at https://ollama.com/settings/keys ; models at
    # https://ollama.com/search?c=cloud . No local install needed in remote mode.
    ollama_cloud_api_key: str = ""
    ollama_cloud_base_url: str = "https://ollama.com/v1"
    ollama_cloud_model_primary: str = "gpt-oss:120b"
    ollama_cloud_model_fallback: str = "gpt-oss:20b"

    # Google AI Studio (Gemini / Gemma via the OpenAI-compatible endpoint)
    # NOTE: Gemini-3.x thinking models fail multi-turn tool loops via the compat
    # endpoint (thought_signature issue). Use gemini-2.5-flash / gemini-2.5-flash-lite.
    @field_validator("llm_provider", mode="before")
    @classmethod
    def force_ollama_cloud_provider(cls, value: str | None) -> str:
        configured = (value or "ollama_cloud").strip().lower()
        if configured != "ollama_cloud":
            return "ollama_cloud"
        return configured

    @property
    def llm_base_url(self) -> str:
        return self.ollama_cloud_base_url

    @property
    def llm_api_key(self) -> str:
        return self.ollama_cloud_api_key

    @property
    def llm_model_primary(self) -> str:
        return self.ollama_cloud_model_primary

    @property
    def llm_model_fallback(self) -> str:
        return self.ollama_cloud_model_fallback

    # JWT
    jwt_secret_key: str = "change_this_in_production_minimum_32_chars"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_tls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@example.com"   # sender address; override via SMTP_FROM env var

    @property
    def email_from(self) -> str:
        """Alias — returns smtp_user if set (Gmail etc.), otherwise smtp_from."""
        return self.smtp_user or self.smtp_from


    # ML
    ml_models_path: str = "./ml/models"
    gliner_model: str = "urchade/gliner_medium-v2.1"
    embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Business Rules
    fraud_block_threshold: float = 0.70
    cash_app_auto_match_threshold: float = 0.90
    credit_limit_hitl_threshold: float = 0.90
    hitl_gate_sox_amount_inr: float = 50000.0
    dunning_max_contacts_per_week: int = 2

    # Inventory
    backorder_stale_days: int = 30          # days before an active backorder is flagged as stale
    default_safety_stock_buffer_pct: float = 0.20  # 20% buffer above reorder_level for safety_stock calc

    # ── Agentic layer ──
    collections_agent_max_iterations: int = 6
    collections_agent_temperature: float = 0.2
    collections_agent_checkpoint_table: str = "maf_checkpoints"
    agent_run_table_retention_days: int = 90

    # ── Proactive monitor + agent chaining ──
    # The monitor scans the DB for trigger conditions and starts agents on its
    # own (no API call needed). Conservative defaults to protect free-tier LLM
    # quota — raise the cap / lower the interval once you have headroom.
    proactive_monitor_enabled: bool = True
    proactive_poll_seconds: int = 120        # how often to scan for work
    proactive_max_per_cycle: int = 2         # max agents auto-started per scan
    proactive_cooldown_minutes: int = 60     # don't re-trigger same entity within this window
    proactive_overdue_days: int = 1          # invoice days_overdue threshold for Collections
    agent_chain_enabled: bool = True         # allow agents to hand off to other agents
    agent_chain_max_depth: int = 3           # loop guard for chained handoffs


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
