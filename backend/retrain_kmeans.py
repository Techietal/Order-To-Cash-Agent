import asyncio
import sys
import os

# Add backend to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.postgres import get_pool
from ml.model_placeholders import train_kmeans

async def run():
    pool = await get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch('SELECT * FROM customers')
        custs = [dict(r) for r in rows]
        print(f"Retraining with {len(custs)} customers...")
        train_kmeans(custs)
        print("Retraining successful.")

if __name__ == "__main__":
    asyncio.run(run())
