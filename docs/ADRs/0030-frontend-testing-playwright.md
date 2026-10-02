# 030. Frontend testing with Playwright

Date: 2026-10-02

## Status

Accepted

## Context

The frontend must be tested with real browsers against the real backend and real data.

## Decision

- **Playwright** end-to-end tests run Chromium against the running Vite dev server and the running FastAPI backend with the seeded demo database.
- No mocked network responses or fixtures. Tests assert on data the backend actually serves.
- Every UI stage adds a spec before the stage is committed.

## Consequences

E2E tests depend on the seeded database being present and are slower than component tests.
