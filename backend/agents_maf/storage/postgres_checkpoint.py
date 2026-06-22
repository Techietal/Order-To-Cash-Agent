"""
Custom Postgres-backed CheckpointStorage for MAF v1.1.

MAF v1.x ships only InMemoryCheckpointStorage and FileCheckpointStorage.
We implement the CheckpointStorage protocol against the same Postgres as asyncpg,
using psycopg3 (psycopg[binary]), so HITL pause/resume survives restarts and is
queryable by thread_id / workflow_name.

CheckpointStorage protocol methods (verified against MAF v1.1.0):
  save(checkpoint: WorkflowCheckpoint) -> CheckpointID  (str)
  load(checkpoint_id: CheckpointID) -> WorkflowCheckpoint
  list_checkpoints(*, workflow_name: str) -> list[WorkflowCheckpoint]
  delete(checkpoint_id: CheckpointID) -> bool
  get_latest(*, workflow_name: str) -> WorkflowCheckpoint | None
  list_checkpoint_ids(*, workflow_name: str) -> list[CheckpointID]

WorkflowCheckpoint is a dataclass with to_dict() / from_dict() helpers.
We serialize it to JSONB using pickle-safe dataclass_asdict via to_dict().
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from agent_framework import WorkflowCheckpoint, WorkflowCheckpointException

from config import settings

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    checkpoint_id           TEXT PRIMARY KEY,
    workflow_name           TEXT NOT NULL,
    previous_checkpoint_id  TEXT,
    blob                    JSONB NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_{table}_wf_name ON {table}(workflow_name, created_at DESC);
"""


def _conninfo() -> str:
    """Build a psycopg3-compatible connection string from settings."""
    if settings.database_url:
        # Strip SQLAlchemy driver prefix if present
        return settings.database_url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")
    return (
        f"host={settings.postgres_host} "
        f"port={settings.postgres_port} "
        f"dbname={settings.postgres_db} "
        f"user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )


def _checkpoint_to_json(checkpoint: WorkflowCheckpoint) -> str:
    """Serialize a WorkflowCheckpoint to a JSON string for Postgres JSONB storage."""
    raw = checkpoint.to_dict()
    return json.dumps(raw, default=str)


def _json_to_checkpoint(blob: str | dict) -> WorkflowCheckpoint:
    """Deserialize a WorkflowCheckpoint from a JSON string or dict."""
    data = blob if isinstance(blob, dict) else json.loads(blob)
    try:
        return WorkflowCheckpoint.from_dict(data)
    except Exception as exc:
        raise WorkflowCheckpointException(
            f"Failed to restore WorkflowCheckpoint from stored blob: {exc}"
        ) from exc


class PostgresCheckpointStorage:
    """Async Postgres checkpoint store implementing the MAF CheckpointStorage protocol.

    Uses psycopg3 (psycopg[binary]) — a separate pool from the asyncpg pool used by
    the rest of the app — pointed at the same database.
    """

    def __init__(self, table_name: str | None = None) -> None:
        self.table = table_name or settings.collections_agent_checkpoint_table
        self._pool: Any = None  # psycopg_pool.AsyncConnectionPool

    async def initialize(self) -> None:
        """Create the connection pool and the checkpoint table (idempotent)."""
        from psycopg_pool import AsyncConnectionPool  # type: ignore[import]

        conninfo = _conninfo()
        self._pool = AsyncConnectionPool(conninfo=conninfo, max_size=8, open=False)
        await self._pool.open()
        create_sql = _CREATE_TABLE_SQL.format(table=self.table)
        async with self._pool.connection() as conn:
            # Execute each statement separately — psycopg3 execute() accepts one stmt
            for stmt in create_sql.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(stmt)
            await conn.commit()
        logger.info(f"✅ PostgresCheckpointStorage ready (table={self.table})")

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
        self._pool = None

    # ── CheckpointStorage protocol ────────────────────────────────────────────

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        """Persist a checkpoint; return its checkpoint_id."""
        cid = checkpoint.checkpoint_id or str(uuid.uuid4())
        blob = _checkpoint_to_json(checkpoint)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO {self.table} "
                f"(checkpoint_id, workflow_name, previous_checkpoint_id, blob) "
                f"VALUES (%s, %s, %s, %s) "
                f"ON CONFLICT (checkpoint_id) DO UPDATE SET blob = EXCLUDED.blob",
                (cid, checkpoint.workflow_name, checkpoint.previous_checkpoint_id, blob),
            )
            await conn.commit()
        return cid

    async def load(self, checkpoint_id: str) -> WorkflowCheckpoint:
        """Load a checkpoint by ID; raises WorkflowCheckpointException if not found."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT blob FROM {self.table} WHERE checkpoint_id = %s",
                (checkpoint_id,),
            )
            row = await cur.fetchone()
        if row is None:
            raise WorkflowCheckpointException(
                f"No checkpoint found with id '{checkpoint_id}'"
            )
        return _json_to_checkpoint(row[0])

    async def list_checkpoints(self, *, workflow_name: str) -> list[WorkflowCheckpoint]:
        """Return all checkpoints for a given workflow_name, newest first."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT blob FROM {self.table} WHERE workflow_name = %s "
                f"ORDER BY created_at DESC",
                (workflow_name,),
            )
            rows = await cur.fetchall()
        return [_json_to_checkpoint(r[0]) for r in rows]

    async def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint by ID. Returns True if deleted, False if not found."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"DELETE FROM {self.table} WHERE checkpoint_id = %s RETURNING checkpoint_id",
                (checkpoint_id,),
            )
            deleted = await cur.fetchone()
            await conn.commit()
        return deleted is not None

    async def get_latest(self, *, workflow_name: str) -> WorkflowCheckpoint | None:
        """Return the latest checkpoint for a workflow_name, or None."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT blob FROM {self.table} WHERE workflow_name = %s "
                f"ORDER BY created_at DESC LIMIT 1",
                (workflow_name,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return _json_to_checkpoint(row[0])

    async def list_checkpoint_ids(self, *, workflow_name: str) -> list[str]:
        """Return checkpoint IDs for a workflow_name, newest first."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT checkpoint_id FROM {self.table} WHERE workflow_name = %s "
                f"ORDER BY created_at DESC",
                (workflow_name,),
            )
            rows = await cur.fetchall()
        return [r[0] for r in rows]
