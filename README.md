# O2C Agent v2.0

An AI-powered Order-to-Cash (O2C) automation system. This system uses a multi-agent architecture with Microsoft Agent Framework (MAF), configurable OpenAI-compatible LLM providers, GLiNER for NER, and XGBoost for ML predictions to automate order ingestion, credit checks, fraud detection, cash application, collections, KYC, and dispute handling.

## Configured Agents

The project includes runtime O2C business agents under `backend/agents_maf/`.

### Runtime Agent Layer

Runtime agents are implemented with Microsoft Agent Framework and exposed through the FastAPI backend. Each agent is a thin domain wrapper around shared runtime utilities in `backend/agents_maf/runtime.py` and shared model setup in `backend/agents_maf/llm.py`.

Configured runtime agents:

| Agent key | Agent name | Entity | Main file | Purpose |
|---|---|---|---|---|
| `collections` | `collections_agent` | Invoice | `backend/agents_maf/collections/agent.py` | Decides and executes the next collections action for overdue invoices. |
| `credit` | `credit_agent` | Customer | `backend/agents_maf/credit/agent.py` | Screens fraud and credit risk, proposes terms, and records credit decisions. |
| `kyc` | `kyc_agent` | KYC request | `backend/agents_maf/kyc/agent.py` | Verifies customer onboarding data, validates GSTINs, checks sanctions, and approves or rejects KYC requests. |
| `cash` | `cash_application_agent` | Invoice | `backend/agents_maf/cash_application/agent.py` | Matches remittances to invoices, posts payments, and escalates ambiguous cash application cases. |
| `disputes` | `disputes_agent` | Dispute | `backend/agents_maf/disputes/agent.py` | Triages customer disputes, extracts dispute details, resolves cases, or issues credit memos when allowed. |

The registry in `backend/agents_maf/registry.py` maps the short keys above to their Python modules and run functions. This lets the proactive monitor and handoff processor dispatch agents without hard-coding each caller.

### Agent Capabilities

#### Collections Agent

The Collections Agent works on overdue invoices. It loads invoice, customer, segment, days-overdue, balance, and weekly contact-limit context before running.

Main tools:

- `get_dunning_history` reads prior dunning contacts.
- `predict_segment` classifies the customer as Premium, Standard, At-Risk, or Problem.
- `count_weekly_contacts` enforces weekly contact limits.
- `draft_dunning_email` prepares a segment-aware email draft.
- `send_dunning_email` sends and logs a dunning email when contact limits allow it.
- `log_promise_to_pay` records promise-to-pay activity.
- `schedule_followup` schedules a future follow-up without Celery.
- `escalate_to_hitl` pauses the run for human review.

Collections has dedicated API routes under `/api/collections/agent/*` because it also owns collection-specific run listing and resume flows.

#### Credit Agent

The Credit Agent works on customer credit decisions. It loads customer tier and credit limit, then evaluates requested order credit.

Main tools:

- `get_customer_credit_profile` reads current credit tier, limits, open AR, and payment history.
- `screen_fraud` evaluates fraud risk for the order amount.
- `assess_credit_risk` produces LOW, MEDIUM, or HIGH risk and probability of default.
- `propose_terms` recommends credit limit and payment terms.
- `record_credit_decision` persists an ECOA-auditable decision.
- `escalate_to_hitl` pauses borderline cases for a human controller.

#### KYC Agent

The KYC Agent works on pending onboarding requests in `customer_kyc_requests`.

Main tools:

- `get_kyc_request` fetches submitted onboarding details.
- `verify_gstin` validates GSTIN format and checksum.
- `check_sanctions` screens the company name against the denylist.
- `approve_kyc` approves verified requests.
- `reject_kyc` rejects invalid or blocked requests.
- `escalate_to_hitl` pauses uncertain cases for a compliance officer.

#### Cash Application Agent

The Cash Application Agent works on invoice remittances and open balances.

Main tools:

- `get_invoice_balance` reads invoice balance and status.
- `match_payment` scores remittance-to-invoice match confidence.
- `apply_payment` posts a matched payment to the invoice and AR ledger.
- `escalate_to_hitl` pauses ambiguous matches for human review.
- `handoff_to_collections` queues a follow-on Collections Agent run when payment issues need collections action.

#### Disputes Agent

The Disputes Agent works on customer portal disputes.

Main tools:

- `get_dispute` fetches the dispute and message thread.
- `extract_dispute_entities` extracts dispute type, amount, and invoice references.
- `summarize_dispute` produces a short reviewer summary.
- `issue_credit_memo` issues credit memos within SOX limits.
- `resolve_dispute` marks a dispute resolved with a decision note.
- `escalate_to_hitl` pauses the run for a disputes manager.
- `handoff_to_collections` queues Collections follow-up when the dispute outcome affects collection activity.

### Agent APIs

Non-collections agents share a generic control plane at `/api/agents`:

- `POST /api/agents/{domain}/run` starts `disputes`, `cash`, `credit`, or `kyc` for one entity.
- `POST /api/agents/{domain}/resume` resumes a human-in-the-loop paused run.
- `GET /api/agents/runs` lists agent runs across non-collections agents.
- `GET /api/agents/runs/{run_id}` reads one run record.
- `GET /api/agents/handoffs` lists agent-to-agent handoff records.

Collections uses dedicated routes under `/api/collections/agent`:

- `POST /api/collections/agent/run` starts the Collections Agent for an invoice.
- `POST /api/collections/agent/resume` resumes a paused collections run.
- `GET /api/collections/agent/runs` lists collections runs.
- `GET /api/collections/agent/runs/{run_id}` reads one collections run record.

Access is role-protected through staff dependencies. Generic agent routes allow `admin`, `controller`, `collections_analyst`, and `dispute_manager`. Collections routes use the collections role set defined in `backend/api/collections.py`.

### Runtime Behavior

All runtime agents run in-process through FastAPI `BackgroundTasks`; they do not require Celery for agent execution. Celery is still used elsewhere in the application for background task queues.

Run lifecycle is stored in PostgreSQL:

- `agent_runs` records thread IDs, agent names, entity references, run status, HITL payloads, human decisions, summaries, and errors.
- `agent_handoffs` records queued agent-to-agent handoffs with a depth limit to prevent loops.
- `followups` records delayed collection follow-ups swept by the backend process.
- `maf_checkpoints` is created by `PostgresCheckpointStorage` for durable MAF checkpoint storage.

Common statuses include:

- `running` while the agent is executing.
- `done` when the agent completes successfully.
- `paused_hitl` when the agent escalates to a human.
- `error` when execution or resume fails.

### Human-In-The-Loop Escalation

Agents pause through tool-level HITL escalation rather than relying on internal MAF message structure. The escalation tool writes an `audit_log` sentinel such as `COLLECTIONS_HITL`, `CREDIT_HITL`, `KYC_HITL`, `CASH_HITL`, or `DISPUTES_HITL`.

After the model run finishes, the runtime checks whether a matching HITL event was written during that run. If found, the run is saved as `paused_hitl` with a payload describing the reason and suggested action. A staff user can then resume the run with a decision through the resume API. The agent receives the human decision in the resume prompt and finishes the action.

### Proactive Monitor And Agent Chaining

`backend/agents_maf/monitor.py` starts a long-lived proactive monitor from the FastAPI lifespan when `proactive_monitor_enabled=True`.

The monitor scans for work every `proactive_poll_seconds` and starts at most `proactive_max_per_cycle` agents per scan. It avoids repeatedly triggering the same entity within `proactive_cooldown_minutes`.

Default proactive triggers:

- Pending KYC requests trigger `kyc_agent`.
- Pending portal disputes trigger `disputes_agent`.
- Overdue invoices without recent dunning activity trigger `collections_agent`.

Agent chaining is enabled by `agent_chain_enabled`. When a tool records a handoff, a row is added to `agent_handoffs`; the monitor drains pending handoffs and dispatches the target agent through `registry.dispatch_run`. `agent_chain_max_depth` prevents runaway loops.

### LLM Provider Configuration

The MAF agents use `backend/agents_maf/llm.py`, which builds an OpenAI-compatible chat completion client from `backend/config.py`. The provider can be switched without code changes.

Supported provider keys:

| `llm_provider` | Key setting | Base URL setting | Primary model setting | Fallback model setting |
|---|---|---|---|---|
| `openrouter` | `openrouter_api_key` | `openrouter_base_url` | `openrouter_model_primary` | `openrouter_model_fallback` |
| `ollama_cloud` | `ollama_cloud_api_key` | `ollama_cloud_base_url` | `ollama_cloud_model_primary` | `ollama_cloud_model_fallback` |
| `google` | `google_api_key` | `google_base_url` | `gemini_model_primary` | `gemini_model_fallback` |
| `groq` | `groq_api_key` | built-in Groq URL | `groq_model_primary` | `groq_model_fallback` |
| `ollama` | local dummy key | `ollama_base_url` | `ollama_model_primary` | `ollama_model_fallback` |

If the primary model hits a rate limit or quota error and the fallback differs from the primary model, `run_agent_with_fallback()` retries once with the fallback model.

## 🚀 Prerequisites

Before you start, make sure you have the following installed:
- **Python 3.10+** (v3.13 recommended)
- **Node.js 18+** & npm
- **PostgreSQL 14+**
- **Redis Server** (For Celery task queues and WebSocket pub/sub)
- **Git**

---

## 🛠️ Setup Instructions

### 1. Clone the Repository
```bash
git clone https://github.com/TSP2005/O2C.git
cd O2C/o2c-agent
```

### 2. Database Setup (PostgreSQL)
1. Open PostgreSQL (pgAdmin or psql) and create a new database and user:
```sql
CREATE USER o2c_admin WITH PASSWORD 'changeme';
CREATE DATABASE o2c_agent OWNER o2c_admin;
```
*(If you use different credentials, update `backend/.env`).*

### 3. Redis Setup
The application uses Celery for background tasks, which requires Redis.
- **Mac/Linux:** `brew install redis` and `brew services start redis`
- **Windows:** Download a pre-compiled Windows binary (Memurai or the older Microsoft archive), extract it, and run `redis-server.exe`.

### 4. Backend Setup
Open a terminal in the repo root:
```bash
# Create and activate a virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
# source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Copy the example env file and fill in your credentials
copy backend\.env.example backend\.env   # Windows
# cp backend/.env.example backend/.env  # Mac/Linux

# Run migrations and seed the database
python seed_data/rich_seed.py
```

> **Note:** `rich_seed.py` creates the tables and loads synthetic datasets (customers, products,
> invoices, etc.) so you don't start with an empty system.
> Development staff users (admin/admin123, controller/ctrl123, inventory_manager/inv123, etc.) are seeded **only** when `APP_ENV=development`
> (the default). Set `APP_ENV=production` to skip them.

### 5. Frontend Setup
Open a *new* terminal in the `frontend` folder:
```bash
cd frontend
npm install
```

---

## 🏃‍♂️ Running the Application Locally

You will need **3 separate terminal windows** to run the full stack:

### Terminal 1: Backend API (FastAPI)
```bash
# from repo root, venv activated
uvicorn backend.main:app --reload --port 8000
```

### Terminal 2: Celery Worker (Background tasks & AI processing)
```bash
# from repo root, venv activated
# On Windows (requires gevent/eventlet or solo pool):
celery -A backend.workers.celery_worker.celery_app worker --loglevel=info --pool=solo
# On Mac/Linux:
# celery -A backend.workers.celery_worker.celery_app worker --loglevel=info
```

### Terminal 3: Frontend (React/Vite)
```bash
cd frontend
npm run dev
```

The app will be running at [http://localhost:5173](http://localhost:5173).

---

## 🧪 Running Tests

From the **repo root** (venv activated):
```bash
python -m pytest backend/tests -q
```

---

## 📦 Inventory Capabilities

The inventory module includes backend APIs and staff UI pages for:

- Inventory dashboard with low-stock, backorder, incoming PO, and transaction summaries.
- Products page and product detail view with available/on-hand/reserved/incoming stock.
- Purchase order creation, confirmation, receiving, and incoming-stock tracking.
- Order reservation, fulfillment, and cancellation flows that mutate stock only through `inventory_service.py`.
- Forecast snapshot APIs for demand, depletion date, and reorder recommendations.

Key staff routes:

- `/inventory`
- `/products`
- `/products/:skuId`
- `/purchase-orders`

`inventory_manager` can access these inventory routes plus order inventory actions, without finance, dispute, analytics, or compliance access.

Key backend routes:

- `/api/inventory/*`
- `/api/products/*`
- `/api/purchase-orders/*`
- `/api/orders/{order_id}/fulfill`
- `/api/orders/{order_id}/cancel`

---

## 🔑 Environment Variables & API Keys

`backend/.env` is **not committed** to the repository. Copy the example file and fill in your values:
```bash
copy backend\.env.example backend\.env   # Windows
# cp backend/.env.example backend/.env  # Mac/Linux
```

Key variables to configure:

| Variable | Description |
|---|---|
| `LLM_PROVIDER` | Selects the provider used by `backend/agents_maf/llm.py`; supported values include `openrouter`, `ollama_cloud`, `google`, `groq`, and `ollama` |
| `OLLAMA_CLOUD_API_KEY` | Required when `LLM_PROVIDER=ollama_cloud`; used by the configured MAF agents |
| `GROQ_API_KEY` | Required when `LLM_PROVIDER=groq`; used by MAF agents and older Groq-backed utilities |
| `OPENROUTER_API_KEY` | Required when `LLM_PROVIDER=openrouter` |
| `GOOGLE_API_KEY` | Required when `LLM_PROVIDER=google` |
| `SMTP_USER` / `SMTP_PASSWORD` | Gmail credentials for outbound email (collections, OTPs) |
| `POSTGRES_*` | PostgreSQL connection details |
| `JWT_SECRET_KEY` | Change this in production (min 32 chars) |
| `APP_ENV` | `development` (default) seeds staff demo users; set to `production` to skip |
| `PROACTIVE_MONITOR_ENABLED` | Enables the autonomous monitor that starts eligible agents without an API call |
| `PROACTIVE_POLL_SECONDS` | Scan interval for proactive agent triggering |
| `PROACTIVE_MAX_PER_CYCLE` | Maximum number of agents auto-started per monitor cycle |
| `AGENT_CHAIN_ENABLED` | Enables handoffs between agents through `agent_handoffs` |
| `AGENT_CHAIN_MAX_DEPTH` | Loop guard for chained agent handoffs |
