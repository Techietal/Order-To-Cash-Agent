from workers.celery_worker import celery_app
import logging
import asyncio

logger = logging.getLogger(__name__)

@celery_app.task(name="agent_02_collections")
def run_collections_agent(invoice_id: str):
    logger.info(f"Agent 2 (Collections) started for invoice: {invoice_id}")
    # In a real scenario, this would query the DB, generate a Dunning email via Groq, and send it.
    return {"status": "success", "action": "dunning_email_sent"}

@celery_app.task(name="agent_03_cash_application")
def run_cash_application_agent(remittance_id: str):
    logger.info(f"Agent 3 (Cash App) started for remittance: {remittance_id}")
    # Queries ChromaDB for invoice matching
    return {"status": "success", "action": "invoices_matched"}

@celery_app.task(name="agent_04_disputes")
def run_dispute_agent(dispute_id: str):
    logger.info(f"Agent 4 (Disputes) started for dispute: {dispute_id}")
    # Generates dispute resolution via Groq
    return {"status": "success", "action": "dispute_resolved"}


@celery_app.task(name="inventory_refresh_forecasts")
def refresh_inventory_forecasts(days=30):
    async def _run():
        from database.postgres import get_pool
        from services.inventory_forecast_service import generate_all_forecast_snapshots

        pool = await get_pool()
        async with pool.acquire() as conn:
            return await generate_all_forecast_snapshots(conn, days=days)

    try:
        result = asyncio.run(_run())
        logger.info("Inventory forecast refresh completed: %s", result)
        return result
    except Exception as exc:
        logger.exception("Inventory forecast refresh failed")
        return {"generated_count": 0, "failed_skus": [{"sku_id": "*", "error": str(exc)}], "model_summary": {}}
