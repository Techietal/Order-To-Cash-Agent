import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.postgres import get_pool
from ml.model_placeholders import predict_customer_segment

async def run():
    pool = await get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch("""
            SELECT customer_id, company_name, credit_tier,
                   open_ar_balance_inr, avg_dso_days,
                   missed_payments_12m, credit_limit_inr, account_age_months
            FROM customers ORDER BY customer_id
        """)
        print("\n=== K-Means Segment Predictions ===")
        for r in rows:
            cust = dict(r)
            result = predict_customer_segment(cust)
            print(f"  {cust['customer_id']} | {cust['company_name']:<35} | Tier-{cust['credit_tier']} | DSO={cust['avg_dso_days']} | Missed={cust['missed_payments_12m']} | AR=₹{cust['open_ar_balance_inr']:,.0f} | → [{result['segment']}] (cluster {result['cluster_id']})")

if __name__ == "__main__":
    asyncio.run(run())
