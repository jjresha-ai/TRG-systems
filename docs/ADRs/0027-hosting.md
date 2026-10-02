# 027. Hosting and deployment

Date: 2026-10-02

## Status

Accepted

## Context

A customer demo is needed immediately.

## Decision

- Phase one runs as two processes: **uvicorn** (FastAPI) in reload/development mode and the **Vite** dev server, which proxies `/api` to the backend.
- File storage is a local directory behind the document service (ADR 0013), accessed only through signed URLs.
- Production hosting (container platform, managed Postgres, object storage) needs a later ADR.

## Consequences

Not production-hardened. Development mode is intentional for the live-build demonstration.
