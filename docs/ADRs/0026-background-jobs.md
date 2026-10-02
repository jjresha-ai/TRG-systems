# 026. Background jobs

Date: 2026-10-02

## Status

Accepted

## Context

ADR 0007, 0016 and 0020 need scheduled and asynchronous work (hold-period triggers, imports, rules).

## Decision

- Jobs are plain, idempotent Python functions in a job registry, runnable on demand through an admin endpoint and on an interval by a lightweight in-process scheduler thread started with the app.
- Job runs are recorded (name, start, end, status, result summary) so the UI can show them.
- A separate worker process or queue (Celery, RQ, cloud scheduler) is deferred until hosting is chosen.

## Consequences

In-process scheduling runs once per app process, so it is only safe with a single worker. Revisit with the hosting ADR.
