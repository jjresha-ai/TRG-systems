# AGENTS.md

Guidance for AI coding agents working in this repository. (`CLAUDE.md` is a symlink to this file; edit `AGENTS.md`.)

## What we are building

TRG Systems is a CRM for The Resha Group (commercial real estate investment sales, Southern California retail and industrial) and 1880 Capital (investor/syndicator relationships). The goal is to fill the listing pipeline and track sale listings and closed deals.

Core domain concepts: contacts, owner entities (LLCs), properties, listings, deals, buyer interest, investor profiles, and funds/syndications. Key workflows: owner prospecting with hold/sell triggers (hold period, loan maturity, ownership change), listing and closed-deal pipelines, and matching investors to listings.

The repo currently holds docs only: no application code exists yet.

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

## Open decisions (each needs its own ADR before implementation)

Database and ORM/migrations, backend test tooling, authentication, background jobs, hosting, frontend build tooling (Vite or Next.js), state management and data fetching, email provider (Microsoft 365 or Google), and owner-data vendors.

## Conventions

- Develop on the branch specified for the session; commit with clear messages. Do not open pull requests unless asked.
- Keep commits focused, and keep docs in Markdown under `docs/`.
- The user is an expert in commercial real estate: favor bottom-line-first summaries, and flag risks and tradeoffs.
