# 31. Isolated environment for end-to-end tests

Date: 2026-10-02

## Status

Accepted. Refines the "run against the running servers" detail of ADR 0030.

## Context

ADR 0030 had Playwright run against the same servers and database that serve the live demo. End-to-end tests create, merge and convert records. Running them against the demo database would pollute the data being shown and make the tests order-dependent.

## Decision

- The Playwright config starts its own stack: a FastAPI process on its own port, a freshly seeded SQLite file in a temporary location, and its own Vite dev server proxying to that backend.
- It is still the real backend, real database engine, real seed and real browser. No mocks, stubs or intercepted network calls.
- The demo servers and database are never touched by tests.

## Consequences

Each Playwright run reseeds a database (a few seconds). Tests may freely create and change data. The seed is exercised on every run.
