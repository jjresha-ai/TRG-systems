# 6. Duplicate Detection and Merge

Date: 2026-10-02

## Status

Proposed

## Context

Duplicate or stale records destroy trust in a CRM. CRE makes it worse: owner lists from multiple vendors, spreadsheets and Outlook contacts all overlap, and the same LLC appears under spelling variants ("123 Main LLC", "123 Main, L.L.C."). The research lists dedupe and merge as table stakes for contacts, imports and data hygiene.

## Decision

Duplicate handling is a backend service used by manual entry, imports (ADR 0016), email capture (ADR 0014) and lead conversion (ADR 0007).

- **Match keys.** Contacts: normalized email, normalized phone, and name plus company. Companies: normalized name (case, punctuation, and suffixes such as LLC, L.L.C., Inc. stripped), website domain, and registered address. Properties: APN plus county first, then normalized address.
- **Normalization is stored.** Normalized email, phone (E.164) and address values are persisted alongside the originals so matching is indexable.
- **Confidence tiers.** Exact key match is a *definite* duplicate and is blocked or auto-linked on entry. Fuzzy match is a *possible* duplicate and is queued for human review.
- **Merge.** A merge picks a surviving record, moves all child records and associations (activities, notes, deals, ownership, email links), and resolves field conflicts by explicit user choice with per-field defaults.
- **Merge log.** Every merge records the surviving and absorbed IDs and the field decisions, and absorbed records are soft-deleted so a merge can be reversed within a retention window.
- **External IDs.** Absorbed records keep their external IDs mapped to the survivor so re-imports do not recreate them.

## Consequences

- Cleaner data and trustworthy relationship history, at the cost of a review queue someone must work.
- Fuzzy matching will produce false positives and negatives; thresholds need tuning on real data.
- Merge touches every table that references people, companies or properties, so each new association type must register with the merge service.
- Undoable merges require soft-delete and retention rules across the model.
