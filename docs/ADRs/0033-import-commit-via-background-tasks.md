# 33. Import commit runs as a resumable background task

Date: 2026-10-02

## Status

Accepted

## Context

ADR 0016 wants imports to run asynchronously and be resumable, and ADR 0026 defers a real worker or queue until hosting is chosen.

## Decision

- Uploading a file parses it, stores the bytes, and returns a **preview** (a dry run through the duplicate service) without writing business data.
- **Commit** starts a FastAPI background task that opens its own database session and processes rows one at a time, each inside a savepoint, so one bad row becomes an error row and never aborts the batch.
- Every row records whether it was processed and which records it created. Calling commit again on a job that is still `running` or ended `failed` continues with the unprocessed rows, so a crash or restart never duplicates records.
- The job's progress is polled through `GET /api/imports/{id}`.

## Consequences

The task runs inside the API process, so very large imports compete with request handling. Moving to a worker later changes only where the commit function is invoked, not the data model.
