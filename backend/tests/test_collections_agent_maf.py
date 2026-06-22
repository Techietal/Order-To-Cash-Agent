"""Tests for the MAF Collections Agent layer (G8).

- FDCPA guard: a send is blocked once the weekly contact limit is reached.
- Checkpoint roundtrip: save -> load -> delete using a real WorkflowCheckpoint
  (skipped automatically if Postgres / psycopg is unavailable).
"""
import pytest


@pytest.mark.asyncio
async def test_fdcpa_guard_blocks_over_limit(monkeypatch):
    """send_dunning_email must refuse when can_contact is False (FDCPA RULE-007)."""
    from agents_maf.collections import tools as t

    async def fake_count(customer_id):
        return {
            "contacts_this_week": 2,
            "max_per_week": 2,
            "remaining": 0,
            "can_contact": False,
        }

    monkeypatch.setattr(t, "count_weekly_contacts", fake_count)

    result = await t.send_dunning_email(
        to_email="x@y.com",
        subject="s",
        body="b",
        invoice_id="INV-1",
        customer_id="CUST-1",
    )
    assert result["sent"] is False
    assert "FDCPA" in result["blocked_reason"]


@pytest.mark.asyncio
async def test_postgres_checkpoint_roundtrip():
    """Save -> load -> delete a real WorkflowCheckpoint. Skips if no DB/psycopg."""
    from agent_framework import WorkflowCheckpoint
    from agents_maf.storage.postgres_checkpoint import PostgresCheckpointStorage

    store = PostgresCheckpointStorage(table_name="maf_checkpoints_test")
    try:
        await store.initialize()
    except Exception as exc:  # noqa: BLE001 — environment-dependent
        pytest.skip(f"Postgres/psycopg unavailable: {exc}")

    try:
        cp = WorkflowCheckpoint(
            workflow_name="collections-test",
            graph_signature_hash="deadbeef",
            state={"x": 1},
        )
        cid = await store.save(cp)
        assert cid

        loaded = await store.load(cid)
        assert loaded is not None
        assert loaded.workflow_name == "collections-test"
        assert loaded.state.get("x") == 1

        assert await store.delete(cid) is True
    finally:
        await store.close()
