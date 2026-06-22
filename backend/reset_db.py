import asyncio
import asyncpg
import sys
import os
from dotenv import load_dotenv

load_dotenv()

async def reset():
    try:
        conn = await asyncpg.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", 5432),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "postgres"),
            database=os.getenv("POSTGRES_DB", "postgres")
        )
        await conn.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public;')
        await conn.close()
        print('DB Wiped')
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

asyncio.run(reset())
