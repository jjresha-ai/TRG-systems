# 8. Listings and Buyer Interest

Date: 2026-10-02

## Status

Proposed

## Context

Sale listings are the primary scorecard. A listing is an engagement to sell a property, with its own status, team, key dates and marketing activity. Buyer response per listing (CA signed, OM downloaded, tour, offer) is how a listing is judged and how buyers are followed up. The research treats Listing and Buyer Interest as distinct entities, and Buildout is the reference for this workflow.

## Decision

- **Listing**: Property, seller (Contact and/or Company), listing type (sale, lease), status (prospect, active, under contract, closed, expired, withdrawn), list price, commission terms, listing agreement date and **expiration date**, broker team with roles and split shares, and confidentiality flag. Days on market is derived from the active date, not stored.
- A Property can have many Listings over time but only one active sale listing at once, enforced in the backend.
- **BuyerInterest**: Listing, Contact (and optional Company), and a stage progression: inquiry, CA sent, CA signed, OM sent, tour, offer, declined. Each event is timestamped, and offers record amount and terms.
- A buyer response may arrive from an email, a form, or manual entry; all paths create the same record through one service.
- A Listing links to a Deal when it goes under contract (ADR 0010); the Deal inherits the parties and key dates.
- Marketing documents (OM, CA, flyers) attach through the document model (ADR 0013).

## Consequences

- Reports on listings by status, days on market, and buyer activity per listing become simple queries.
- Seller-side Deal pipeline and Listing status overlap and must stay consistent; the backend owns that sync, not the UI.
- Public listing syndication (CoStar, LoopNet, Crexi) and OM/CA e-sign automation are not included here and need separate decisions.
- Matching investors to listings builds on this plus ADR 0009.
