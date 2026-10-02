# 7. Leads and Owner Prospecting

Date: 2026-10-02

## Status

Proposed

## Context

The goal of the system is to fill the listing pipeline. Prospects must be triaged without polluting the clean contact database. In CRE, "lead" means two different things: a prospective seller (listing origination) and a buyer inquiry on a listing. Owner prospecting is driven by hold/sell triggers: hold period, loan maturity, and ownership change. HubSpot treats leads as a lifecycle stage on contacts; Salesforce and Pipedrive use a separate staging object. See research section 2.

## Decision

We will use a distinct **Lead** object as a staging area, separate from Contact and Company.

- **Lead**: name, company, source, status, score, owner user, stream (`seller` or `buyer`), optional links to a Property, created_at, converted_at, and conversion outcome.
- **Seller-side leads** feed the listing pipeline. **Buyer-side inquiries** are not generic leads: they attach to a Listing as Buyer Interest (ADR 0008) and create or link a Contact directly.
- **Conversion** creates or links a Contact, Company and optional Deal in one backend transaction, running duplicate checks first (ADR 0006).
- **Lead source** is a managed list, with campaign attribution. Web-form submission is captured through an API endpoint.
- **Assignment** by simple rules (owner by market or property type, round-robin) configured in the backend.
- **Triggers.** A backend job evaluates configurable rules over Property and PropertyOwnership data (ADR 0005): acquisition date older than N years, loan maturity within N months, or a recorded ownership change. A match creates a seller-side Lead (or a task on the existing owner) with the triggering reason stored.
- **Scoring** starts as transparent additive rules (trigger matches, recency of contact, property fit), with the score's components stored. No black-box model in this phase.

## Consequences

- A clean contact base, and a measurable seller-origination funnel with source quality.
- Conversion logic must be tested carefully, since it spans several entities.
- Triggers depend on the quality of acquisition and debt data, so data vendors and import (ADR 0016) directly affect usefulness. Vendor selection is a separate decision.
- A background job runner is required for trigger evaluation; that choice is a separate ADR.
- Outreach compliance (TCPA, Do Not Call) must be checked before any outreach tooling is built; the research is unverified on this point.
