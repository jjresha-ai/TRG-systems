# 4. Backend-First Development

Date: 2026-10-02

## Status

Accepted

## Context

Features can be built starting from the user interface and working backward, or starting from the backend and working forward. Starting from the UI tends to shape business logic around screens, scatters rules into frontend code, and makes behavior hard to test without a browser. TRG Systems is a CRM with real business rules (ownership, pipelines, scoring, compliance), and AI agents will do much of the implementation. Logic that is exercised through an API and automated tests is far easier for both people and agents to verify.

## Decision

For every feature, we will build and test the backend functionality before creating the frontend user interface for it.

- The backend work comes first: data model, business logic, and FastAPI endpoints (see ADR 0003), with automated tests that pass before UI work begins.
- Business rules live in the backend. The frontend (see ADR 0002) presents and collects data; it does not own logic.
- The frontend for a feature is built against a working, tested API, using the generated OpenAPI schema.
- A feature is not considered ready for UI work until its backend tests pass.

## Consequences

- The backend stays highly testable, with behavior verified directly through tests and API calls rather than through the UI.
- Logic is reusable by other consumers (integrations, automation, AI agents, future clients) without rework.
- Frontend work depends on backend completion for each feature, so UI progress can look slower early on. Small vertical slices keep this manageable.
- API design must be thought through up front. Gaps discovered during UI work return to the backend first, with tests, before the UI changes.
- Test tooling and conventions for the backend are not decided here and will get their own ADR.
