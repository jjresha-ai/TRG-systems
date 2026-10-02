# 20. Workflow Automation Basics

Date: 2026-10-02

## Status

Proposed

## Context

The research lists assignment rules, reminders and stage-change triggers as table stakes. Several accepted and proposed ADRs already imply automation: lead assignment and hold/sell triggers (ADR 0007), cadence tasks (ADR 0011), and key-date tasks (ADR 0010). Without a shared mechanism each would be built differently. A general visual workflow builder is a large investment and is not basic.

## Decision

We will provide a small, shared **rules engine** inside the backend, with code-defined trigger types and admin-configurable parameters.

- **Triggers**: record created, field changed, stage changed, date reached (relative to a record's date field), and scheduled evaluation (for example nightly hold-period checks).
- **Conditions**: the same filter definition used by lists and search (ADR 0015).
- **Actions** (a fixed, reviewed set): assign owner, create task, apply cadence template, create a lead, send an in-app notification, and set a field.
- Each rule has a name, owner, enabled flag and run log. Every action it takes is audited with the rule as the actor (ADR 0018).
- Rules run in the background job runner (separate ADR) and are idempotent, so a retry or re-run never duplicates tasks.
- Rules cannot send external email or messages in this phase.
- Outreach actions must respect do-not-contact flags (ADR 0012).

## Consequences

- Prospecting, reminders and assignment share one tested mechanism and one audit trail.
- A fixed action set limits power but keeps the system predictable and safe.
- Idempotency and loop prevention (a rule's change triggering itself) need explicit design and tests.
- A visual builder, multi-step branching and external actions would require a new ADR.
