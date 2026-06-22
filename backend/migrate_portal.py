import asyncio, sys
sys.path.insert(0, '.')
from database.postgres import get_pool

async def migrate():
    pool = await get_pool()
    async with pool.acquire() as conn:
        print("Adding portal columns to customers...")
        await conn.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS portal_active BOOLEAN DEFAULT TRUE;")
        await conn.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS password_hash TEXT DEFAULT '';")
        await conn.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS kyc_id TEXT DEFAULT '';")

        print("Creating customer_kyc_requests table...")
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS customer_kyc_requests (
            kyc_id           VARCHAR(30) PRIMARY KEY,
            company_name     TEXT NOT NULL,
            contact_name     TEXT NOT NULL,
            email            TEXT NOT NULL,
            phone            TEXT,
            gstin            VARCHAR(15),
            pan_number       VARCHAR(10),
            business_type    TEXT,
            state            TEXT,
            city             TEXT,
            address          TEXT,
            annual_turnover  TEXT DEFAULT '',
            status           TEXT DEFAULT 'pending',
            reviewer         TEXT DEFAULT '',
            review_notes     TEXT DEFAULT '',
            rejection_reason TEXT DEFAULT '',
            submitted_at     TIMESTAMPTZ DEFAULT NOW(),
            reviewed_at      TIMESTAMPTZ
        );
        """)
        print("All migrations completed successfully.")
    await pool.close()

asyncio.run(migrate())
