# 13. Document Storage

Date: 2026-10-02

## Status

Proposed

## Context

Offering memoranda, confidentiality agreements, LOIs, PSAs, rent rolls and photos attach to deals, listings and properties. The research lists document storage as a cross-cutting table-stakes item, and field photos and voice notes are key mobile inputs. Documents are often confidential and subject to NDA.

## Decision

- **Document** metadata: file name, type (OM, CA, LOI, PSA, rent roll, flyer, photo, other), uploader, uploaded_at, size, content hash, visibility, and version number.
- Documents associate to Property, Listing, Deal, Contact, Company and Note via the generic association mechanism (ADR 0011).
- File bytes are stored in object storage behind the backend, never directly exposed. Access is through short-lived signed URLs issued after a permission check (ADR 0017). The storage provider is chosen with the hosting decision.
- New uploads of the same document create a new version; prior versions remain accessible.
- Uploads are size-limited and type-checked, with malware scanning decided at hosting time.
- Every download of a confidential document is audit-logged (ADR 0018).
- No e-signature, document generation, or data-room features are included.

## Consequences

- A single attachment mechanism serves notes, deals, listings and mobile photo capture.
- Object storage adds an infrastructure dependency and cost that hosting must cover.
- Confidential documents (buyer identities, NDAs) need field-level or per-document restriction, not just record-level access.
- Full-text search inside documents is out of scope for now.
