import os
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import inventory_forecast_service as svc


class FakeRecord(dict):
    pass


class FakeDB:
    def __init__(self):
        self.executed = []
        self.product_exists = True
        self.forecast_rows = []
        self.active_skus = [FakeRecord({"sku_id": "SKU-001"})]
        self.stock_row = FakeRecord({
            "sku_id": "SKU-001",
            "product_name": "Widget",
            "stock_on_hand": 20,
            "reserved_stock": 5,
            "incoming_stock": 3,
            "safety_stock": 10,
            "reorder_level": 15,
            "reorder_qty": 50,
        })

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, query, *args):
        if "FROM products" in query:
            return FakeRecord({"sku_id": args[0]}) if self.product_exists else None
        if "FROM product_stock_summary" in query:
            return self.stock_row if self.product_exists else None
        return None

    async def fetch(self, query, *args):
        if "FROM products" in query:
            return self.active_skus
        if "FROM inventory_forecast_snapshot" in query:
            return self.forecast_rows
        return []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "OK"


class StalenessFakeDB:
    """FakeDB that tracks whether generate_forecast_snapshot was called."""

    def __init__(self, snapshot_rows, stock_row=None, product_exists=True):
        self.executed = []
        self.snapshot_rows = snapshot_rows
        self.stock_row = stock_row or FakeRecord({
            "sku_id": "SKU-001",
            "product_name": "Widget",
            "stock_on_hand": 20,
            "reserved_stock": 5,
            "incoming_stock": 3,
            "safety_stock": 10,
            "reorder_level": 15,
            "reorder_qty": 50,
        })
        self.product_exists = product_exists
        self.generated_called = False

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, query, *args):
        if "FROM products" in query and "is_active" in query:
            return FakeRecord({"sku_id": args[0]}) if self.product_exists else None
        if "FROM product_stock_summary" in query:
            return self.stock_row if self.product_exists else None
        return None

    async def fetch(self, query, *args):
        if "FROM products" in query:
            return [FakeRecord({"sku_id": "SKU-001"})]
        if "FROM inventory_forecast_snapshot" in query:
            return self.snapshot_rows
        return []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        self.generated_called = True
        return "OK"


@pytest.mark.asyncio
async def test_forecast_snapshot_upsert_from_ds_yhat_rows():
    db = FakeDB()
    with patch.object(svc, "predict_demand_forecast", return_value={
        "model": "prophet_trained",
        "daily_forecast": [
            {"ds": "2026-01-01", "yhat": 4, "yhat_lower": 3, "yhat_upper": 5},
            {"ds": "2026-01-02", "yhat": 6, "yhat_lower": 5, "yhat_upper": 7},
        ],
    }):
        result = await svc.generate_forecast_snapshot(db, "SKU-001", days=2)

    assert result["model_version"] == "prophet_trained"
    assert result["generated_count"] == 2
    assert result["total_demand"] == 10
    assert len(db.executed) == 2
    assert db.executed[0][1][2] == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_forecast_snapshot_upsert_from_day_yhat_rows():
    db = FakeDB()
    with patch.object(svc, "predict_demand_forecast", return_value={
        "daily_forecast": [{"day": 1, "yhat": 2}, {"day": 2, "yhat": 3}],
    }):
        result = await svc.generate_forecast_snapshot(db, "SKU-001", days=2)

    assert result["model_version"] == "placeholder_mock"
    assert result["generated_count"] == 2
    assert all(isinstance(call[1][2], date) for call in db.executed)


@pytest.mark.asyncio
async def test_missing_sku_raises_value_error():
    db = FakeDB()
    db.product_exists = False

    with pytest.raises(ValueError, match="Active SKU SKU-404 not found"):
        await svc.generate_forecast_snapshot(db, "SKU-404", days=2)


@pytest.mark.asyncio
async def test_get_inventory_forecast_reorder_calculation():
    db = FakeDB()
    db.forecast_rows = [
        FakeRecord({"forecast_date": date(2026, 1, 1), "predicted_daily_demand": 10, "predicted_demand_lower": 8, "predicted_demand_upper": 12, "model_version": "test", "generated_at": datetime.now(timezone.utc)}),
        FakeRecord({"forecast_date": date(2026, 1, 2), "predicted_daily_demand": 10, "predicted_demand_lower": 8, "predicted_demand_upper": 12, "model_version": "test", "generated_at": datetime.now(timezone.utc)}),
    ]

    result = await svc.get_inventory_forecast(db, "SKU-001", days=2)

    assert result["available_stock"] == 15
    assert result["projected_30d_demand"] == 20
    assert result["projected_demand"] == 20
    assert result["average_daily_demand"] == 10
    assert result["recommended_reorder_qty"] == 12
    assert result["reorder_needed"] is True


@pytest.mark.asyncio
async def test_fresh_complete_snapshot_does_not_regenerate():
    now = datetime.now(timezone.utc)
    rows = [
        FakeRecord({"forecast_date": date(2026, 1, d), "predicted_daily_demand": 10,
                     "predicted_demand_lower": 8, "predicted_demand_upper": 12,
                     "model_version": "mock", "generated_at": now})
        for d in range(1, 8)
    ]
    db = StalenessFakeDB(snapshot_rows=rows)

    with patch.object(svc, "generate_forecast_snapshot", new=AsyncMock()) as mock_gen:
        result = await svc.get_inventory_forecast(db, "SKU-001", days=7)

    assert mock_gen.call_count == 0, "Should not regenerate a fresh complete snapshot"
    assert result["snapshot_refreshed"] is False


@pytest.mark.asyncio
async def test_stale_snapshot_regenerates():
    stale_time = datetime.now(timezone.utc) - timedelta(hours=48)
    rows = [
        FakeRecord({"forecast_date": date(2026, 1, d), "predicted_daily_demand": 10,
                     "predicted_demand_lower": 8, "predicted_demand_upper": 12,
                     "model_version": "mock", "generated_at": stale_time})
        for d in range(1, 8)
    ]
    db = StalenessFakeDB(snapshot_rows=rows)

    with patch.object(svc, "predict_demand_forecast", return_value={
        "model": "mock",
        "daily_forecast": [{"ds": f"2026-01-{d:02d}", "yhat": 10, "yhat_lower": 8, "yhat_upper": 12} for d in range(1, 8)],
    }):
        result = await svc.get_inventory_forecast(db, "SKU-001", days=7)

    assert result["snapshot_refreshed"] is True


@pytest.mark.asyncio
async def test_incomplete_snapshot_regenerates():
    now = datetime.now(timezone.utc)
    rows = [
        FakeRecord({"forecast_date": date(2026, 1, d), "predicted_daily_demand": 10,
                     "predicted_demand_lower": 8, "predicted_demand_upper": 12,
                     "model_version": "mock", "generated_at": now})
        for d in range(1, 4)
    ]
    db = StalenessFakeDB(snapshot_rows=rows)

    with patch.object(svc, "predict_demand_forecast", return_value={
        "model": "mock",
        "daily_forecast": [{"ds": f"2026-01-{d:02d}", "yhat": 10, "yhat_lower": 8, "yhat_upper": 12} for d in range(1, 8)],
    }):
        result = await svc.get_inventory_forecast(db, "SKU-001", days=7)

    assert result["snapshot_refreshed"] is True


@pytest.mark.asyncio
async def test_days_7_returns_projected_demand_not_misleading_30d_name():
    now = datetime.now(timezone.utc)
    rows = [
        FakeRecord({"forecast_date": date(2026, 1, d), "predicted_daily_demand": 5,
                     "predicted_demand_lower": 3, "predicted_demand_upper": 7,
                     "model_version": "mock", "generated_at": now})
        for d in range(1, 8)
    ]
    db = StalenessFakeDB(snapshot_rows=rows)

    result = await svc.get_inventory_forecast(db, "SKU-001", days=7)

    assert "projected_demand" in result
    assert result["projected_demand"] == 35
    assert result["projected_30d_demand"] == 35
    assert result["days"] == 7
    assert result["snapshot_row_count"] == 7


def test_forecast_service_has_no_direct_product_stock_mutation():
    source = Path(svc.__file__).read_text(encoding="utf-8")
    assert "UPDATE products SET stock_on_hand" not in source
    assert "UPDATE products SET reserved_stock" not in source
    assert "UPDATE products SET incoming_stock" not in source


def test_celery_task_calls_forecast_generation_service():
    from agents import tasks

    class Conn:
        pass

    class Acquire:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    async def fake_get_pool():
        return Pool()

    async def fake_generate(conn, days=30):
        return {"generated_count": 3, "failed_skus": [], "model_summary": {"mock": 1}}

    with patch("database.postgres.get_pool", new=fake_get_pool), \
         patch("services.inventory_forecast_service.generate_all_forecast_snapshots", new=fake_generate):
        result = tasks.refresh_inventory_forecasts(days=7)

    assert result["generated_count"] == 3
