# 15. Search, Filters and Saved Lists

Date: 2026-10-02

## Status

Proposed

## Context

Retrieval speed determines adoption. Users must find records by address, APN, entity name, or owner principal interchangeably ("who owns 123 Main?" and "what does John Smith own?"). Prospecting and investor outreach run on filtered lists (property type, size, hold period, loan maturity, investor criteria). Map search is increasingly expected. See research section 10.

## Decision

- **Global search** is one backend endpoint returning ranked results across Contact, Company, Property, Listing and Deal, with typeahead support. It supports full-text matching plus fuzzy matching on names, and exact matching on normalized phone, email, APN and address.
- **Graph-aware lookup**: searching a property address also returns its current owners and principals, and searching a person returns the entities and properties they are connected to (ADR 0005).
- **Filter builder**: a structured filter definition (field, operator, value, AND/OR groups) that can reference related records, such as properties whose owner entity has a loan maturing within 12 months. The same definition powers list views, saved lists and report filters (ADR 0021).
- **SavedView**: a named filter definition with columns and sort, private or shared.
- **List**: *dynamic* (stored filter, recomputed) or *static* (fixed membership snapshot), used for call campaigns, cadences and email sends.
- **Tags** are free-form labels on any entity.
- Results always apply the requesting user's permissions (ADR 0017); private notes and emails are excluded for other users.
- Map and radius search is planned as a later extension, using stored property coordinates (geocoded on import).
- The search technology (database features versus a dedicated engine) is decided with the database ADR.

## Consequences

- One filter language is reused across lists, saved views and reports, so it must be designed carefully and versioned.
- Permission-aware search requires filtering inside the query, not after, to avoid leaks.
- Fuzzy and graph search can be slow on large owner datasets; index design is needed before bulk imports.
- Geocoding adds a vendor dependency when map search is built.
