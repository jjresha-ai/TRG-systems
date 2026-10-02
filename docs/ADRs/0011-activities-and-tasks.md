# 11. Activities and Tasks

Date: 2026-10-02

## Status

Proposed

## Context

Follow-through is the main behavior a CRM must enforce. Brokerage work is call-heavy, with site visits and recurring owner check-ins (for example every 90 days). Activities must tie to a Property, Contact and Deal at once. Relationship recency ("not touched in 90 days") is a core prospecting report. See research section 4.

## Decision

- **Activity** (logged, past) and **Task** (planned, future) are one model with a status, so a completed task becomes a logged activity without copying. Fields: type (call, email, meeting, site visit, text, other), subject, body, due and completed timestamps, assignee, priority, and **outcome** (spoke, left voicemail, no answer, not interested, meeting set).
- **Associations** are many-to-many to Contact, Company, Property, Listing, Deal and Lead, through one generic association table with the record type validated in the backend. Referential integrity beyond the type check is enforced by the service layer.
- **Reminders** on tasks, plus overdue and today/this-week agenda queries.
- **Recurrence**: a task can repeat on a schedule (for example every 90 days) and the next instance is created on completion.
- **Cadence templates**: an ordered set of tasks with day offsets that can be applied to a record (owner prospecting, post-listing follow-up). Applying a template creates ordinary tasks.
- **Last-contact fields** (date, user) are derived from completed activities and email (ADR 0014), and exposed on Contact, Company and Property for recency queries.
- Deal key dates (ADR 0010) can create tasks automatically.

## Consequences

- One timeline per record, assembled from activities, notes and emails.
- Last-contact derivation must be kept correct when activities are edited, deleted or merged (ADR 0006).
- A generic association table trades database-level foreign keys for flexibility; tests must cover orphan prevention.
- Click-to-call and call dialing integrations are not decided here. Calls are logged manually first.
- Reminder delivery needs the background job runner (separate ADR).
