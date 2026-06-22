# O2C Agent v2.0 — Seed Data

## Files
| File | Records | Description |
|------|---------|-------------|
| customers.xlsx | 100 | B2B customers with credit tiers A-D |
| products_skus.xlsx | 50 | Products with pricing, GST, inventory |
| orders.xlsx | 300 | Orders across all lifecycle statuses |
| invoices.xlsx | 250 | Invoices with payment status |
| ar_ledger.xlsx | 250 | AR aging entries per invoice |
| payments.xlsx | ~150 | Payment records with match confidence |
| disputes.xlsx | 40 | Dispute cases with type + resolution |
| dunning_log.xlsx | 200 | Collections outreach log |
| inventory_ledger.xlsx | ~175 | Stock movements per SKU |
| fraud_records.xlsx | 50 | Fraud detection results |
| credit_decisions.xlsx | 200 | Credit check outcomes |
| anomaly_alerts.xlsx | 30 | Watchdog alerts |
| policy_rules.xlsx | 8 | Policy Engine rules |
| O2C_Master_Dataset.xlsx | ALL | All sheets in one workbook |

## Loading into PostgreSQL
Run `backend/seed_data/load_seed_data.py` to bulk-load all Excel files into PostgreSQL.

## Notes
- All customer data generated with Faker (synthetic — for pipeline testing only)
- Financial amounts in INR
- Fraud scores, credit scores are placeholder values — real models replace these
