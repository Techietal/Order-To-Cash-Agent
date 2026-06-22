"""Singleton accessors for the PostgresCheckpointStorage instance."""
from __future__ import annotations

from typing import Optional

from .postgres_checkpoint import PostgresCheckpointStorage

_storage: Optional[PostgresCheckpointStorage] = None


async def setup_storage() -> PostgresCheckpointStorage:
    """Initialize and return the singleton checkpoint storage.

    Safe to call multiple times — initializes only once.
    """
    global _storage
    if _storage is None:
        _storage = PostgresCheckpointStorage()
        await _storage.initialize()
    return _storage


async def get_storage() -> PostgresCheckpointStorage:
    """Return the singleton checkpoint storage, initializing if needed."""
    if _storage is None:
        return await setup_storage()
    return _storage


async def close_storage() -> None:
    """Close the checkpoint storage connection pool."""
    global _storage
    if _storage is not None:
        await _storage.close()
    _storage = None
