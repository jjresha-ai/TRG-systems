# 19. Custom Fields

Date: 2026-10-02

## Status

Proposed

## Context

No stock model fits every firm; custom fields let the schema adapt without code changes. The research notes that the usual failure in CRE is cramming property data into contact fields, which is solved by first-class Property, Listing and Entity objects (ADR 0005), not by a generic object builder. Fully custom objects, layouts and formulas are a large investment with an unclear payoff for a two-brand firm.

## Decision

- Core CRE entities (Contact, Company, Property, Listing, Deal, Investor Profile, Fund) are **real, typed tables**, not custom objects.
- **Custom fields** are supported on those entities through **FieldDefinition** metadata: entity, key, label, type (text, long text, number, currency, date, checkbox, single-select, multi-select, lookup to a user or record), options, required flag, and optional conditions (required or shown only for a given pipeline or property type).
- Values are stored together on the record in a typed, validated structure (the storage form follows the database ADR). The backend validates values against definitions.
- Custom fields appear in the API schema and are usable in filters, lists, saved views, imports, exports and reports (ADR 0015, ADR 0016, ADR 0021).
- Field changes are audited (ADR 0018), and field-level permissions apply (ADR 0017).
- Retiring a field hides it but keeps its data.
- **Not included:** custom objects, formula fields, custom page layouts, and validation scripting. They need a new ADR if a real need appears.

## Consequences

- Admins can add fields like "tenant concentration" or "seller motivation" without a release.
- Dynamic fields complicate typing, indexing and OpenAPI generation; the frontend gets a field-definition endpoint to render them.
- Reporting and search performance on custom fields may lag typed columns and may require promotion of heavily used fields to real columns.
- Keeping custom objects out of scope limits flexibility, deliberately.
