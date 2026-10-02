# 12. Notes

Date: 2026-10-02

## Status

Proposed

## Context

Owner motivation, hold-period intent, pricing expectations and family situations are the real value in a relationship business. They must survive broker turnover and be searchable firm-wide. The research also warns that key facts buried in free text cannot be filtered, and that some notes are sensitive. See research section 5.

## Decision

- **Note**: body (rich text stored as sanitized HTML or Markdown, to be fixed in implementation), author, timestamps, pinned flag, and visibility (`team` or `private`).
- Notes associate to Contact, Company, Property, Listing, Deal and Lead through the same generic association mechanism as activities (ADR 0011).
- **Mentions** of users create notifications. Attachments use the document model (ADR 0013).
- Notes are included in global search (ADR 0015), respecting visibility.
- **Structured facts stay structured.** Hold-period intent, pricing expectation, loan maturity, and do-not-contact preference are fields on the relevant records, not note text. The UI may prompt for them when a note is added, but the backend stores them as fields.
- A **do-not-contact** flag with a reason lives on Contact and is checked by every outreach path in the backend.
- Edits keep a version history; deletes are soft deletes.

## Consequences

- Firm-wide searchable memory, with private notes as an explicit exception.
- Rich text requires sanitization to prevent script injection.
- Splitting facts into fields takes more entry effort but enables filtering and triggers.
- Private notes conflict with firm-open visibility defaults (ADR 0017); only the author and admins can read them, and that rule needs explicit tests.
