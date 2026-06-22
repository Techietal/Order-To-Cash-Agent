"""Inventory demand forecast snapshot and read APIs."""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from ml.model_placeholders import predict_demand_forecast

_STALE_HOURS = 24


def _snapshot_id() -> str:
    return f"FCS-{uuid.uuid4().hex[:20].upper()}"


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _forecast_rows(result: dict, days: int) -> list[dict]:
    raw_rows = result.get("daily_forecast") or result.get("forecast") or result.get("rows") or []
    today = datetime.now(timezone.utc).date()
    rows = []
    for idx, row in enumerate(raw_rows[:days]):
        if "ds" in row:
            forecast_date = _as_date(row["ds"])
        elif "day" in row:
            forecast_date = today + timedelta(days=int(row["day"]) - 1)
        else:
            forecast_date = today + timedelta(days=idx)

        yhat = float(row.get("yhat", 0) or 0)
        rows.append({
            "forecast_date": forecast_date,
            "predicted_daily_demand": max(0, yhat),
            "predicted_demand_lower": max(0, float(row.get("yhat_lower", yhat) or 0)),
            "predicted_demand_upper": max(0, float(row.get("yhat_upper", yhat) or 0)),
        })
    return rows


async def generate_forecast_snapshot(db, sku_id: str, days: int = 30, performed_by="system") -> dict:
    if days <= 0:
        raise ValueError("days must be > 0")

    product = await db.fetchrow(
        "SELECT sku_id FROM products WHERE sku_id = $1 AND is_active = TRUE",
        sku_id,
    )
    if not product:
        raise ValueError(f"Active SKU {sku_id} not found")

    forecast = predict_demand_forecast(sku_id, days=days)
    model_version = forecast.get("model") or forecast.get("model_version") or "placeholder_mock"
    rows = _forecast_rows(forecast, days)

    for row in rows:
        await db.execute(
            """INSERT INTO inventory_forecast_snapshot
               (snapshot_id, sku_id, forecast_date, predicted_daily_demand,
                predicted_demand_lower, predicted_demand_upper, model_version, generated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
               ON CONFLICT (sku_id, forecast_date) DO UPDATE SET
                 predicted_daily_demand = EXCLUDED.predicted_daily_demand,
                 predicted_demand_lower = EXCLUDED.predicted_demand_lower,
                 predicted_demand_upper = EXCLUDED.predicted_demand_upper,
                 model_version = EXCLUDED.model_version,
                 generated_at = NOW()""",
            _snapshot_id(), sku_id, row["forecast_date"], row["predicted_daily_demand"],
            row["predicted_demand_lower"], row["predicted_demand_upper"], model_version,
        )

    total_demand = sum(r["predicted_daily_demand"] for r in rows)
    return {
        "sku_id": sku_id,
        "days": days,
        "model_version": model_version,
        "total_demand": total_demand,
        "generated_count": len(rows),
        "forecast": rows,
    }


async def generate_all_forecast_snapshots(db, days: int = 30) -> dict:
    skus = await db.fetch("SELECT sku_id FROM products WHERE is_active = TRUE ORDER BY sku_id")
    generated_count = 0
    failed_skus = []
    models = {}
    for row in skus:
        sku_id = row["sku_id"]
        try:
            result = await generate_forecast_snapshot(db, sku_id, days=days)
            generated_count += result["generated_count"]
            models[result["model_version"]] = models.get(result["model_version"], 0) + 1
        except Exception as exc:
            failed_skus.append({"sku_id": sku_id, "error": str(exc)})
    return {"generated_count": generated_count, "failed_skus": failed_skus, "model_summary": models}


def _is_stale(generated_at: Any) -> bool:
    if generated_at is None:
        return True
    if isinstance(generated_at, str):
        generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if isinstance(generated_at, datetime):
        generated_at = generated_at.replace(tzinfo=timezone.utc) if generated_at.tzinfo is None else generated_at
        return (datetime.now(timezone.utc) - generated_at) > timedelta(hours=_STALE_HOURS)
    return True


async def get_inventory_forecast(db, sku_id: str, days: int = 30, refresh: bool = False) -> dict:
    snapshot_refreshed = False
    need_regenerate = refresh

    if not need_regenerate:
        rows = await db.fetch(
            """SELECT forecast_date, predicted_daily_demand, predicted_demand_lower,
                      predicted_demand_upper, model_version, generated_at
               FROM inventory_forecast_snapshot
               WHERE sku_id = $1 AND forecast_date >= CURRENT_DATE
               ORDER BY forecast_date ASC
               LIMIT $2""",
            sku_id, days,
        )
        if not rows:
            need_regenerate = True
        else:
            newest_generated = max(r["generated_at"] for r in rows)
            if _is_stale(newest_generated):
                need_regenerate = True
            elif len(rows) < days:
                need_regenerate = True

    if need_regenerate:
        await generate_forecast_snapshot(db, sku_id, days=days)
        snapshot_refreshed = True
        rows = await db.fetch(
            """SELECT forecast_date, predicted_daily_demand, predicted_demand_lower,
                      predicted_demand_upper, model_version, generated_at
               FROM inventory_forecast_snapshot
               WHERE sku_id = $1 AND forecast_date >= CURRENT_DATE
               ORDER BY forecast_date ASC
               LIMIT $2""",
            sku_id, days,
        )

    snapshot_row_count = len(rows)

    product = await db.fetchrow(
        """SELECT sku_id, product_name, stock_on_hand, reserved_stock, incoming_stock,
                  safety_stock, reorder_level, reorder_qty
           FROM product_stock_summary
           WHERE sku_id = $1""",
        sku_id,
    )
    if not product:
        raise ValueError(f"SKU {sku_id} not found")

    forecast = [dict(r) for r in rows]
    projected_demand = sum(float(r["predicted_daily_demand"] or 0) for r in forecast)
    average_daily_demand = projected_demand / len(forecast) if forecast else 0
    stock_on_hand = int(product["stock_on_hand"] or 0)
    reserved_stock = int(product["reserved_stock"] or 0)
    incoming_stock = int(product["incoming_stock"] or 0)
    safety_stock = int(product["safety_stock"] or 0)
    available_stock = max(0, stock_on_hand - reserved_stock)
    days_until_stockout: Optional[float] = None
    depletion_date = None
    if average_daily_demand > 0:
        days_until_stockout = available_stock / average_daily_demand
        depletion_date = (datetime.now(timezone.utc).date() + timedelta(days=int(days_until_stockout))).isoformat()

    recommended_reorder_qty = max(0, projected_demand + safety_stock - available_stock - incoming_stock)
    reorder_needed = recommended_reorder_qty > 0

    result = {
        "sku_id": sku_id,
        "days": days,
        "forecast": forecast,
        "stock_position": dict(product),
        "projected_demand": projected_demand,
        "projected_30d_demand": projected_demand,
        "average_daily_demand": average_daily_demand,
        "available_stock": available_stock,
        "days_until_stockout": days_until_stockout,
        "depletion_date": depletion_date,
        "recommended_reorder_qty": recommended_reorder_qty,
        "reorder_needed": reorder_needed,
        "model_version": forecast[0].get("model_version") if forecast else "unknown",
        "snapshot_refreshed": snapshot_refreshed,
        "snapshot_row_count": snapshot_row_count,
    }
    return result
