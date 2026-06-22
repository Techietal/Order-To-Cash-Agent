import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database.postgres import init_schema, get_pool

async def run():
    await init_schema()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        print("\n=== Tables in DB ===")
        for r in rows:
            print(" ", r['tablename'])

asyncio.run(run())
