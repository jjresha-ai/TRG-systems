# AGENTS.md

Guidance for AI coding agents working in this repository. (`CLAUDE.md` is a symlink to this file; edit `AGENTS.md`.)

## What we are building

TRG Systems is a CRM for The Resha Group (commercial real estate investment sales, Southern California retail and industrial) and 1880 Capital (investor/syndicator relationships). The goal is to fill the listing pipeline and track sale listings and closed deals.

Core domain concepts: contacts, owner entities (LLCs), properties, listings, deals, buyer interest, investor profiles, and funds/syndications. Key workflows: owner prospecting with hold/sell triggers (hold period, loan maturity, ownership change), listing and closed-deal pipelines, and matching investors to listings.

The application is built (stages 0-11 in `docs/PLAN.md`): a FastAPI backend in `backend/` and a React frontend in `frontend/`, with a deterministic demo seed.

## Read first

- `docs/ADRs/`: architecture decisions. Read the relevant ones before architectural changes, and add a new ADR for significant decisions. ADRs are immutable once accepted; supersede instead of editing.
- `docs/research/`: CRM feature research (basic, advanced, exotic) with a commercial real estate section in each.
  - `01-basic-crm-features.md` holds the suggested entity model and MVP build order; start there.
  - Much of the research is from working knowledge, not verified sources. Re-verify vendor claims, costs and legal points (TCPA/DNC, Reg D) before relying on them.

## Decisions in force

- **Frontend (ADR 0002):** React, Tailwind CSS, shadcn/ui. Use the frontend-design skill (if available in the session) to make the UI aesthetically distinctive, not default-styled.
- **Backend (ADR 0003):** Python with FastAPI and Pydantic. The OpenAPI schema is the contract with the frontend.
- **Backend first (ADR 0004):** For every feature, build and test the backend (model, logic, endpoints, automated tests passing) before building any UI for it. Business rules live in the backend; the frontend presents and collects data only.

## How to work

1. Pick a small vertical slice of the MVP (see the build order in `01-basic-crm-features.md`).
2. Write the backend: data model, logic, FastAPI endpoints, and tests. Tests must pass before UI work starts.
3. Then build the frontend against the tested API, using the generated OpenAPI schema.
4. If UI work exposes a backend gap, go back to the backend, add the fix with tests, then resume the UI.
5. Record significant decisions as new ADRs, numbered sequentially (`NNNN-short-title.md`).

## Decisions recorded since (ADRs 0023-0034)

Database and ORM (SQLAlchemy 2.x on SQLite, portable to Postgres), pytest with a real database and no mocks, token auth with roles, in-process job scheduler, hosting, Vite + TanStack Query, Playwright with an isolated e2e environment, Python-evaluated filters, import commit via background tasks, rules triggered from the audit trail. Email uses a provider interface with database-backed capture: no Microsoft 365/Google sync yet, and sending returns 501 until a provider is chosen (ADR 0029). Still open: owner-data vendors, and the final mail provider.

## Running it

- Backend: `cd backend && pip install -r requirements.txt && python -m app.seed && uvicorn app.main:app --reload` (port 8000). Demo logins use password `demo1234` (jim@resha.group is admin).
- Frontend: `cd frontend && npm install && npm run dev` (port 5173, proxies `/api`).
- Tests: `cd backend && python -m pytest -q`; `cd frontend && npx playwright test` (starts its own isolated backend, database and Vite on ports 8100/5273 and reseeds each run).
- Build progress shown on the home page comes from `backend/app/stages.py`; update it with `python setstage.py <stage> <backend|frontend> <done|building|next|soon>`.

## Known limits (flag before relying on them)

- Filters are evaluated in Python (ADR 0032); move to SQL before data grows well past tens of thousands of rows.
- SQLite-specific JSON `LIKE` queries must be revisited when moving to Postgres.
- The scheduler is single-process (`TRG_SCHEDULER`); run one worker or move jobs to a real queue.
- "Must be accredited to commit to a fund" is an assumption to confirm with securities counsel (Reg D).
- Default record visibility (firm-open versus team-scoped) is an `AppSetting`; confirm the default with the firm.

## Conventions

- Develop on the branch specified for the session; commit with clear messages. Do not open pull requests unless asked.
- Keep commits focused, and keep docs in Markdown under `docs/`.
- The user is an expert in commercial real estate: favor bottom-line-first summaries, and flag risks and tradeoffs.
