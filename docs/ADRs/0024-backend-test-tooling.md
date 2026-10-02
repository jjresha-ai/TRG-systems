# 024. Backend test tooling

Date: 2026-10-02

## Status

Accepted

## Context

ADR 0004 requires passing backend tests before UI work. The product must not use mocked data or stubs.

## Decision

- **pytest** with FastAPI's `TestClient`, running against a real SQLite database file created fresh per test session, through the real app and real migrations/schema.
- No mocks, stubs or fakes. Tests create real rows through the API or services and assert on real responses.
- A test run seeds nothing implicitly; tests build their own data. The demo seed is tested separately for volume and referential integrity.

## Consequences

Tests are slower than mocked unit tests but exercise the real stack. Frontend tests are covered by ADR 0030.
