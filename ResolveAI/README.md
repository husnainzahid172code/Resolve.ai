# ResolveAI — Agentic E-commerce Order, Return & Refund Resolution

A university project (CSC-348, Agentic AI). A LangGraph agent investigates customer complaints with tools, retrieves store policies, proposes a resolution, validates it independently and waits for a human administrator. **No refund or payment is ever executed.**

* Customer chat: `/` · Admin dashboard: `/admin`
* Deploy a public demo link: [docs/deployment.md](docs/deployment.md)
* Docs: [architecture](docs/architecture.md) · [workflow](docs/workflow.md) · [testing report](docs/testing_report.md) · [failure report](docs/failure_report.md) · [slides outline](docs/presentation_outline.md) · [demo script](docs/demo_script.md) · [instructor Q&A](docs/instructor_qa.md)

## 1. Requirements
Python 3.11+ and Node 18+.

## 2. Quick start (demo mode — no keys needed)
```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # then set ADMIN_PASSWORD
uvicorn app.main:app --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev            # http://localhost:5173  (proxies /api to :8000)
```
To serve everything from one process, run `npm run build` once. FastAPI then serves `frontend/dist` at http://localhost:8000.

Admin login: user `admin`, plus the password you set in `.env`.

Without keys, the banner shows **DEMO MODE · OFFLINE DEMO PLANNER · LOCAL DEMO DATA (not Google Sheets)**.

## 3. Turn on the real LLM agent
Put **one** of these in `backend/.env` and restart:
```
GOOGLE_API_KEY=...          # free key from https://aistudio.google.com/apikey
GEMINI_MODEL=gemini-3.8-flash
# or
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```
`LLM_PROVIDER=auto` picks OpenAI first, then Gemini, then offline. The banner shows which planner is active.

## 4. Connect Google Sheets
1. Google Cloud Console → create a project → enable the **Google Sheets API** and the **Google Drive API**.
2. Create a **service account**, then add a JSON key and save it as `backend/credentials/service_account.json` (this path is git-ignored).
3. Create an empty Google Sheet and share it (Editor) with the service account's `client_email`.
4. In `.env`, set `GOOGLE_SHEETS_SPREADSHEET_ID` (the long ID in the sheet URL) and `GOOGLE_SERVICE_ACCOUNT_FILE=./credentials/service_account.json`.
5. `cd backend && python -m scripts.seed_google_sheets`. This creates the **Orders**, **Store Policies** and **Resolution Logs** tabs. Order dates are relative to today, so re-run it before each demo.
6. Restart. The banner should show **Data: Google Sheets**.

## 5. Connect Gmail (customer emails after approval)
Approving or rejecting a case emails the customer. That is the system's one irreversible action, and it only runs after a human decision.
1. Turn on **2-Step Verification** for your Google account.
2. Open https://myaccount.google.com/apppasswords, create an app password named `ResolveAI` and copy the 16 characters.
3. In `.env`, add:
   ```
   GMAIL_ADDRESS=yourname@gmail.com
   GMAIL_APP_PASSWORD=abcdabcdabcdabcd
   EMAIL_DEMO_RECIPIENT=yourname@gmail.com
   ```
   `EMAIL_DEMO_RECIPIENT` sends every email to you instead of the fake demo customers (`@example.com`).
4. Restart. The banner shows **Email: Gmail (...)**. Without these values it shows **DEMO OUTBOX**: emails are recorded and visible in the admin case page, but not sent.

## 6. Demo data (order IDs)
| Order | Situation | Try |
|---|---|---|
| ORD1001 | Headphones delivered 2 days ago | damaged → photo → proposal |
| ORD1002 | Watch delivered 12 days ago | return outside 7-day window |
| ORD1003 | Shoes delivered after 11 days | late + wrong item |
| ORD1004 | Speaker **already refunded** | duplicate refund |
| ORD1005 | Toothbrush, **opened** | hygiene exclusion |
| ORD1006 | Mug set, **processing** | cancellation allowed |
| ORD1007 | Backpack in transit 10 days | not arrived → carrier investigation |
| ORD1008 | Lamp delivered 2 days ago | missing photo → resume |
| ORD1009 | Yoga mat delivered yesterday | wrong item (second order in multi-order case) |
| ORD9999 | does not exist | nonexistent order |

Scenario 8 (outage): Admin → Overview → **Simulate outage** (labelled demo control).

## 7. Tests
```bash
cd backend && python -m pytest tests -v
```
69 tests (unit, integration, end-to-end). Results: [docs/testing_report.md](docs/testing_report.md).

## 8. API
Customer: `POST /api/complaints`, `POST /api/cases/{id}/messages`, `POST /api/cases/{id}/evidence`, `GET /api/cases/{id}`
Admin (Bearer token from `POST /api/auth/login`): `GET /api/cases`, `GET /api/cases/pending`, `GET /api/cases/{id}`, `POST /api/cases/{id}/approve|reject|request-information|retry|resend-email`, `GET /api/dashboard/stats`, `GET /api/resolution-logs`
Comparison: `POST /api/comparison/run` (or from a terminal with progress: `py -m scripts.run_comparison`), `GET /api/comparison/results`. Interactive docs: http://localhost:8000/docs

## 9. Project structure
```
backend/app/
  agents/     planner (LLM + offline), prompts, safety, validator
  graph/      LangGraph state, nodes, builder, assessment bridge
  tools/      tool schemas + implementations
  services/   data sources (Sheets/demo), email (Gmail/outbox), policy engine, case service, evidence, responses
  baseline/   traditional workflow, scenarios, comparison runner
  api/ core/ database/ schemas/  main.py
backend/tests/   69 tests
backend/scripts/ seed_google_sheets.py
frontend/src/    pages, components, layouts, services, hooks
docs/            all academic deliverables
```

## 10. Safety summary
The LLM cannot approve anything, change policies or set amounts. Every proposal is validated deterministically and stopped for human approval. Admin endpoints need auth, decisions are idempotent, uploads are type- and size-checked, and secrets stay in `.env`.
