# 3. Backend: FastAPI

Date: 2026-10-02

## Status

Accepted

## Context

TRG Systems needs a backend to serve the React frontend (see ADR 0002), store CRM data, and run integrations and automation. The research in `docs/research/` points to work that is data- and AI-heavy: owner and LLC entity resolution, enrichment, public-records signals, scoring, and LLM-assisted features. Python has the strongest ecosystem for that work. We also want a typed, self-documenting API that AI coding agents and the frontend can consume reliably.

## Decision

We will build the backend in Python using **FastAPI**.

- The API is JSON over HTTP, described by the OpenAPI schema FastAPI generates.
- Request and response models are defined with Pydantic, so validation and documentation come from the same types.
- Async endpoints are used where we do I/O (database, third-party APIs); synchronous code is fine for CPU-bound or simple paths.
- The frontend can generate a typed client from the OpenAPI schema instead of hand-writing API calls.

## Consequences

- Strong typing and automatic validation and docs reduce integration bugs between frontend and backend.
- Python gives direct access to data, enrichment and AI libraries for the features the research highlights.
- FastAPI is a thin framework: we choose and maintain our own pieces for auth, background jobs, migrations and project structure.
- Running Python (backend) alongside TypeScript (frontend) means two toolchains and two sets of dependencies.
- Database, ORM, authentication, background-job runner and hosting are not decided here and will get their own ADRs.
