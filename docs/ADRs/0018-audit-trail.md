# 18. Audit Trail

Date: 2026-10-02

## Status

Proposed

## Context

An audit trail supports dispute resolution (who changed a commission split, who exported the owner list), compliance, and departing-broker investigations. The research lists it as a cross-cutting requirement and a security feature. It also underpins field history, stage history and merge reversal.

## Decision

- **AuditEvent**: timestamp, actor (user, API token, or system job), action, entity type and ID, and a before/after change set for edits. Events are append-only and cannot be edited or deleted through the application.
- The backend writes audit events inside the same transaction as the change, through a shared mechanism, so no code path can skip it.
- **Always audited**: create, update and delete of core entities, ownership transfers, merges, permission and role changes, commission and split changes, imports, exports, document downloads of confidential files, logins and failed logins, and API token use.
- **Field history** for selected fields (price, stage, commission, owner) is queryable per record, built from the audit events.
- Sensitive field values may be recorded as "changed" without the value, as set per field.
- An admin-only audit view supports filtering by user, record and action.
- Retention defaults to indefinite for core events; any purge policy requires a superseding ADR.

## Consequences

- Strong accountability, at the cost of storage growth and some write overhead.
- The shared mechanism must cover bulk operations and background jobs, which are easy to miss.
- Audit data itself holds sensitive values and must follow the same permission rules (ADR 0017).
- Deal stage history (ADR 0010) is a purpose-built table for reporting; the audit log is the general record.
