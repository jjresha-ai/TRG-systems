# 32. Evaluate filters in the application layer for now

Date: 2026-10-02

## Status

Accepted

## Context

ADR 0015 requires one structured filter definition (AND/OR groups, related-record conditions) powering list views, saved lists, search filters, report filters and workflow rule conditions. Translating arbitrary related-record conditions (for example "contacts whose properties have a loan maturing within 12 months") to SQL for both SQLite and PostgreSQL is a large piece of work. The current datasets are hundreds to low thousands of rows per entity.

## Decision

- A single filter engine in the backend validates a filter definition against a per-entity field registry (field, type, allowed operators, restriction flag, related-record paths) and evaluates it in Python over the visible, non-deleted records.
- Related paths use *any-match* semantics (a contact matches `holdings.loan_maturity_date within 12 months` if any held property does).
- Everything that filters (query endpoint, saved views, lists, rules, exports) calls this one engine, so semantics cannot drift.
- Field restrictions (ADR 0017) are enforced in the registry: a restricted field is neither filterable nor returnable for unauthorized roles.

## Consequences

Cost grows linearly with record count per query. This is acceptable up to roughly tens of thousands of records. When the dataset or the Postgres migration requires it, the same registry can be compiled to SQL (fields declare a column or join) without changing the filter definition or any client. A superseding ADR will record that move.
