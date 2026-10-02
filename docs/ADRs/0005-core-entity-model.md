# 5. Core Entity Model: Contacts, Companies, Properties, Ownership

Date: 2026-10-02

## Status

Proposed

## Context

Generic CRMs model a flat Contact and Account. Commercial real estate breaks that model: owners hold property through multiple LLCs, principals sit behind entities, and a person can be an owner, buyer, lender and investor at once. Every other feature (listings, deals, activities, search) hangs off these records, so this is the foundation. See `docs/research/01-basic-crm-features.md`, sections 1, 10, 11 and the entity model summary.

## Decision

We will model these first-class entities. Property, Listing and Entity are real tables, not custom objects (see ADR 0019).

- **Contact** (a person): name, multiple emails and phones as child records (normalized), title, addresses, owner user, source, status, tags, lifecycle stage, and one or more contact types (owner, buyer, investor, lender, attorney, tenant, other).
- **Company** (an organization or entity): name, kind (LLC, trust, fund, family office, brokerage, lender, other), website, address, optional parent company, owner user. LLC and trust holding entities are Companies, not a separate type.
- **ContactCompanyRole**: many-to-many between Contact and Company with role (principal, manager, asset manager, representative, attorney), primary flag, and start/end dates. Distinguishes the decision-maker from the representative.
- **Property**: address, APN, county, property type and subtype, market and submarket, building SF, land acres, units, year built, zoning, and physical and financial fields (NOI, cap rate) as nullable structured columns.
- **PropertyOwnership**: Property to Company (and, where unknown, to Contact) with ownership percentage, acquired date, and disposed date. History is kept, so "current owner" is the row with no disposed date.
- **Debt fields**, held as structured data and not notes: lender, original amount, rate type, and **loan maturity date**. Together with acquisition date these drive hold/sell triggers (see ADR 0007).
- Every record carries `owner_user_id`, `source`, `created_at`, `updated_at`, and provenance (see ADR 0016).

The owner graph (Contact to Company to Property) must be traversable in both directions: "who owns 123 Main?" and "what does John Smith own?"

## Consequences

- The model supports entity-to-principal resolution, which owner prospecting depends on.
- More tables and joins than a flat model. API responses should offer both summary and expanded views of the graph.
- Unknown ownership is common in imported data, so the model must allow a Property with an unresolved owner.
- Field-level detail (financials, debt) is structured now so triggers, filters and reports work without parsing text.
- Dedupe of people and entities is required from day one (ADR 0006).
- Database and ORM choice is a separate decision; this ADR defines the shape, not the storage.
