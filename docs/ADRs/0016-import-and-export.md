# 16. Import and Export

Date: 2026-10-02

## Status

Proposed

## Context

Data arrives as spreadsheets: CoStar exports, public-record owner lists, data vendor files, Outlook contacts, and the brokers' own lists. A single owner often maps to many properties and entities. Provenance must be preserved, refreshed vendor data must update existing records, and the firm must always be able to take its data out. See research section 8.

## Decision

- **ImportJob**: file, target entity, field mapping, mode (create only, update only, create or update), status, and per-row results. Jobs run asynchronously (background runner decided separately) and are resumable.
- **Preview before commit**: a dry run reports rows to create, update, skip and flag as duplicates, using the duplicate service (ADR 0006), before any data is written.
- **Related-record import**: a single file can create linked Contact, Company, Property and ownership rows (one owner, many properties), with entity name matching.
- **Provenance**: every imported record stores source name, import job ID and import date. **ExternalId** maps each source system's ID to the record, so refreshed feeds update instead of duplicating.
- **Row error report** is downloadable, and an import can be **rolled back** by job ID while its created records are unmodified.
- **Export** of any entity, list or saved view to CSV and XLSX, permission-aware and audit-logged (ADR 0018). Full export includes relationship history (activities, notes metadata, ownership history) so data is portable.
- A documented REST API and webhooks provide programmatic access (ADR 0003); API tokens are covered by ADR 0017.
- Field-level export restrictions (for example commissions) apply to exports.

## Consequences

- Imports are the main source of duplicate and bad data; the preview step and rollback are mandatory, not optional.
- Mapping rules for each vendor file format will accumulate over time and may need saved mapping templates.
- Rollback is complicated once imported records are edited or linked; the rule is "unmodified records only".
- Vendor licensing terms may restrict storing or exporting purchased owner data; check before relying on bulk import.
