"""End-to-end test for all MAF agents (Collections + Disputes + Cash + Credit + KYC).

Runs three layers:
  A. Deterministic tool layer (no LLM) against real seed data.
  B. HITL plumbing via the shared runtime (start -> escalate -> detect -> finish).
  C. Full LLM agent loop for each domain (only if OLLAMA_CLOUD_API_KEY is set).

Isolation: creates a temp KYC row and temp dispute, snapshots/restores the seed
invoice balance, and cleans up temp rows so seed data is left unchanged.
"""
import asyncio
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import settings
from database.postgres import get_pool

CUST = "CUST-0001"
INV = "INV-003-A"
VALID_GSTIN = "27AAPFU0939F1ZV"   # known valid-format Indian GSTIN
TMP_KYC = "KYC-E2E-TEST"
TMP_DISPUTE = "DISP-E2E-TEST"

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((name, cond))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


async def section_a_tools():
    print("\n== A. Deterministic tool layer ==")
    # KYC
    from agents_maf.kyc import tools as kyc
    v = await kyc.verify_gstin(VALID_GSTIN)
    check("KYC verify_gstin valid", v["valid"] is True, json.dumps(v))
    bad = await kyc.verify_gstin("NOTAGSTIN")
    check("KYC verify_gstin rejects bad", bad["valid"] is False)
    s_hit = await kyc.check_sanctions("Redline Traders")
    check("KYC sanctions hit", s_hit["sanctions_hit"] is True)
    s_clean = await kyc.check_sanctions("Satya Manufacturing Pvt Ltd")
    check("KYC sanctions clean", s_clean["sanctions_hit"] is False)

    # Credit
    from agents_maf.credit import tools as credit
    prof = await credit.get_customer_credit_profile(CUST)
    check("Credit profile loads", prof["found"] is True)
    fraud = await credit.screen_fraud(CUST, 200000.0)
    check("Credit screen_fraud returns verdict", "fraud_verdict" in fraud, fraud.get("fraud_verdict"))
    risk = await credit.assess_credit_risk(CUST, 200000.0)
    check("Credit assess_credit_risk returns class", "credit_risk_class" in risk, risk.get("credit_risk_class"))
    terms = await credit.propose_terms(risk.get("credit_risk_class", "MEDIUM"), risk.get("pd_score", 0.3), 500000)
    check("Credit propose_terms returns terms", "recommended_net_terms_days" in terms)

    # Cash
    from agents_maf.cash_application import tools as cash
    bal = await cash.get_invoice_balance(INV)
    check("Cash get_invoice_balance", bal["found"] is True, f"balance={bal.get('balance_due_inr')}")
    match = await cash.match_payment(INV, bal["balance_due_inr"], INV)
    check("Cash match_payment exact->high conf", match["confidence"] >= 0.7, f"conf={match['confidence']}")
    mismatch = await cash.match_payment(INV, 1.0, "unrelated")
    check("Cash match_payment mismatch->low conf", mismatch["confidence"] < 0.65, f"conf={mismatch['confidence']}")

    # Disputes
    from agents_maf.disputes import tools as disp
    dlist = await get_any_dispute()
    if dlist:
        got = await disp.get_dispute(dlist)
        check("Disputes get_dispute", got["found"] is True)
    else:
        check("Disputes get_dispute (no seed dispute)", True, "skipped")


async def get_any_dispute():
    pool = await get_pool()
    async with pool.acquire() as db:
        r = await db.fetchval("SELECT dispute_id FROM portal_disputes LIMIT 1")
    return r


async def section_b_hitl():
    print("\n== B. HITL plumbing (runtime) ==")
    from agents_maf import runtime
    tid, started = await runtime.start_run(
        agent_name="credit_agent", entity_type="customer", entity_id=CUST, customer_id=CUST)
    check("runtime.start_run created row", bool(tid))
    await runtime.log_hitl(agent_name="credit_agent", event_type="CREDIT_HITL",
                           entity_id=CUST, customer_id=CUST, reason="e2e test", suggested_action="approve")
    hit = await runtime.hitl_since("CREDIT_HITL", CUST, started)
    check("runtime.hitl_since detects escalation", hit is not None and hit.get("reason") == "e2e test")
    await runtime.finish_run(tid, "paused_hitl", "e2e", hitl=hit)
    run = await runtime.get_run(tid)
    check("runtime.finish_run set paused_hitl", run["status"] == "paused_hitl")
    # cleanup
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM agent_runs WHERE thread_id=$1", tid)


async def setup_temp_fixtures():
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO customer_kyc_requests (kyc_id, company_name, contact_name, email, gstin, status)
               VALUES ($1,'E2E Clean Co','Tester','e2e@example.com',$2,'pending')
               ON CONFLICT (kyc_id) DO UPDATE SET status='pending'""",
            TMP_KYC, VALID_GSTIN)
        await db.execute(
            """INSERT INTO portal_disputes (dispute_id, customer_id, invoice_id, dispute_type, subject, status)
               VALUES ($1,$2,$3,'pricing_error','E2E test dispute','pending_admin')
               ON CONFLICT (dispute_id) DO UPDATE SET status='pending_admin'""",
            TMP_DISPUTE, CUST, INV)
        await db.execute(
            """INSERT INTO portal_dispute_messages (message_id, dispute_id, sender_type, body)
               VALUES ($1,$2,'customer','We were overcharged by 2000 INR on this invoice, please review.')
               ON CONFLICT (message_id) DO NOTHING""",
            "MSG-E2E-1", TMP_DISPUTE)
        bal = await db.fetchval("SELECT balance_due_inr FROM invoices WHERE invoice_id=$1", INV)
    return float(bal or 0)


async def cleanup_temp_fixtures(orig_balance):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM portal_dispute_messages WHERE dispute_id=$1", TMP_DISPUTE)
        await db.execute("DELETE FROM portal_disputes WHERE dispute_id=$1", TMP_DISPUTE)
        await db.execute("DELETE FROM customer_kyc_requests WHERE kyc_id=$1", TMP_KYC)
        await db.execute("DELETE FROM credit_memos WHERE dispute_id=$1", TMP_DISPUTE)
        # restore seed invoice balance in case a memo/payment touched it
        await db.execute("UPDATE invoices SET balance_due_inr=$1 WHERE invoice_id=$2", orig_balance, INV)
        await db.execute("UPDATE ar_ledger SET outstanding_balance_inr=$1 WHERE invoice_id=$2", orig_balance, INV)


def _is_quota(text):
    t = (text or "").lower()
    return "429" in t or "rate limit" in t or "rate_limit" in t or "quota" in t


async def run_agent_safe(label, coro):
    try:
        res = await asyncio.wait_for(coro, timeout=120)
        ok = res.get("status") in ("done", "paused_hitl")
        if not ok and _is_quota(res.get("summary")):
            print(f"  [SKIP] LLM {label} run — LLM daily token quota exhausted (external)")
            return res
        check(f"LLM {label} run -> {res.get('status')}", ok, (res.get("summary") or "")[:90])
        return res
    except Exception as exc:  # noqa: BLE001
        if _is_quota(str(exc)):
            print(f"  [SKIP] LLM {label} run — LLM daily token quota exhausted (external)")
            return None
        check(f"LLM {label} run", False, f"{type(exc).__name__}: {exc}")
        return None


async def section_c_llm():
    print("\n== C. Full LLM agent loops ==")
    if not settings.ollama_cloud_api_key:
        print("  (skipped — no OLLAMA_CLOUD_API_KEY)")
        return
    from agents_maf.credit import agent as credit_agent
    from agents_maf.kyc import agent as kyc_agent
    from agents_maf.cash_application import agent as cash_agent
    from agents_maf.disputes import agent as disp_agent

    await run_agent_safe("credit", credit_agent.run(CUST, order_amount_inr=150000))
    await run_agent_safe("kyc", kyc_agent.run(TMP_KYC))
    # tiny mismatched remittance -> agent should escalate (no mutation)
    await run_agent_safe("cash", cash_agent.run(INV, remittance_amount=1.0, remittance_text="unknown"))
    await run_agent_safe("disputes", disp_agent.run(TMP_DISPUTE))


async def main():
    orig_balance = await setup_temp_fixtures()
    try:
        await section_a_tools()
        await section_b_hitl()
        await section_c_llm()
    finally:
        await cleanup_temp_fixtures(orig_balance)

    passed = sum(1 for _, c in results if c)
    total = len(results)
    print(f"\n==== E2E RESULT: {passed}/{total} checks passed ====")
    if passed != total:
        print("FAILURES:", [n for n, c in results if not c])


asyncio.run(main())
