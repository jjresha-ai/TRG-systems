# 34. Workflow rules react to audit events through a cursor

Date: 2026-10-02

## Status

Accepted

## Context

ADR 0020 requires rules triggered by record creation, field changes and stage changes, run in the background job runner, idempotent, with every action audited. ADR 0018 already guarantees that every create and update of a core entity writes an audit event in the same transaction.

## Decision

- Event-based triggers (record created, field changed, stage changed) are evaluated by a background job that reads **new audit events** after a stored cursor. There is no second event mechanism, so no code path can change data without the rules engine being able to see it.
- Date-reached and scheduled rules are evaluated by scanning records on the job's schedule.
- Every action has an **idempotency key** (rule, record, trigger instance, action index). A retry, a re-run or a restart never repeats an action. Scheduled rules use a cooldown window in the key.
- Events written by a rule (actor `rule:<name>`) are not re-processed, which prevents loops.
- Actions are a fixed set (assign owner, create task, apply cadence, create lead, notify, set field). There is no email or messaging action in this phase. Outreach tasks respect do-not-contact flags.

## Consequences

Rules fire when the job runs (on a schedule or on demand), not synchronously inside the request that caused the change. That delay is acceptable for follow-up work and keeps request latency independent of rule complexity.
