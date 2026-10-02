# 17. Permissions and Access Control

Date: 2026-10-02

## Status

Proposed

## Context

A brokerage must protect confidential deal data and limit exfiltration by departing brokers, yet firms disagree on whether owner relationships are open to all brokers (avoiding conflicting outreach) or private to each broker. Commission, buyer identity under NDA, seller pricing and investor data need tighter control. This ADR covers authorization; **authentication** (login, SSO, MFA) is a separate open ADR. See research section 9.

## Decision

- **Roles**: admin, manager, broker, assistant, read-only. Permissions are defined as action (view, create, edit, delete, export) per entity, held in the backend and checked in every endpoint and query.
- **Ownership**: every record has an owner user. Owners can be transferred singly or in bulk, and deactivating a user requires reassigning their records first.
- **Default visibility is firm-open** for Contact, Company, Property, Listing and Deal. Everyone in the firm can see owner relationships, which prevents conflicting outreach. This default is **provisional and needs Jim's confirmation**; the model must also support a team-scoped visibility without schema change.
- **Private by exception**: notes marked private (ADR 0012), email privacy (ADR 0014), and records explicitly marked confidential.
- **Field-level restrictions** for commission and split fields, seller pricing guidance, buyer identity on confidential listings, and investor accreditation data. A restricted field is omitted from API responses, exports, search and reports for unauthorized users.
- **Export control**: export is a separate permission, and bulk exports are rate-limited and audit-logged (ADR 0018).
- **API tokens** are scoped, revocable and attributable to a user.
- Authorization is enforced in the backend only. The frontend may hide controls but is never the control.

## Consequences

- Authorization checks must run inside list and search queries, not afterward, to avoid leaks (ADR 0015).
- Field-level security touches serialization, exports and reports, so these need a shared mechanism and tests.
- Firm-open defaults trade broker privacy for coordination; the choice must be made explicitly and may be revisited by a superseding ADR.
- Offboarding becomes a defined workflow (reassign, revoke tokens, revoke email connections, disable export).
