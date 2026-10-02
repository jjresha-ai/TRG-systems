# 023. Database, ORM and migrations

Date: 2026-10-02

## Status

Accepted

## Context

ADR 0003 leaves the database open. The first release ships for a customer demo and must run with zero infrastructure. Search (ADR 0015) and JSON custom fields (ADR 0019) depend on this choice.

## Decision

- **SQLAlchemy 2.x** ORM with **Alembic** for migrations.
- **SQLite** (WAL mode, foreign keys on) for the demo and development. All code uses portable SQLAlchemy constructs so the same models run on **PostgreSQL**, which is the production target.
- Custom field values are a JSON column. Search uses normalized columns plus `LIKE` and trigram-style fuzzy scoring in Python for now; Postgres full-text/pg_trgm replaces it on migration.
- Money is stored as integer dollars (or integer basis points for rates), never floats.

## Consequences

SQLite limits concurrent writers and lacks native full-text ranking. Moving to Postgres is a connection-string change plus a search-service swap, and must be done before multi-user production use.
