# 1. Use Architecture Decision Records

Date: 2026-10-02

## Status

Accepted

## Context

We need a lightweight way to record significant architectural and technical decisions for this project, along with the reasoning behind them, so that future contributors (human or AI agents) can understand why things are the way they are.

## Decision

We will use Architecture Decision Records (ADRs), as described by Michael Nygard, to document significant decisions.

- ADRs live in `docs/ADRs/`.
- Files are named `NNNN-short-title.md`, numbered sequentially.
- Each ADR has a title, date, status (Proposed, Accepted, Deprecated, Superseded), context, decision, and consequences.
- ADRs are immutable once accepted. To change a decision, write a new ADR that supersedes the old one and update the old one's status.

## Consequences

- Decisions and their rationale are discoverable in the repository.
- Writing an ADR adds a small amount of overhead to significant changes.
- Agents and contributors should check `docs/ADRs/` before making architectural changes.
