# 10. Deals and Pipelines

Date: 2026-10-02

## Status

Proposed

## Context

Closed deals are the second half of the scorecard. CRE deals differ from generic opportunities: separate processes (seller-side, buyer-rep, capital placement, leasing), a sale price distinct from the commission, co-broker and agent splits, many parties, and 6 to 18 month cycles. Management needs stage discipline, forecasts and stall detection. See research section 3.

## Decision

- **Pipeline** and **Stage** are configurable data: stage order, default probability, and a "rotting" threshold in days. Initial pipelines: seller-side, buyer-side, capital, leasing. The seller-side default stages are prospect, pitch, listing agreement, marketing, offers, under contract, due diligence, closed.
- **Deal**: pipeline, stage, Property, optional Listing, deal type, **price**, **gross commission** (amount or rate), probability, expected and actual close dates, owner, source, and lost reason (required to mark lost).
- **DealParty**: Deal, Contact or Company, and role (seller, buyer, lender, attorney, title, 1031 party, co-broker).
- **DealStageHistory**: every stage change appended with timestamp and user. Time in stage and stall reports derive from it. It is never edited.
- **CommissionSplit**: Deal, recipient (internal broker or external co-broker), percentage or amount, and type. The backend validates that splits do not exceed 100 percent.
- **Key dates**: listing expiration, due-diligence expiry, loan contingency, closing. Each can generate tasks (ADR 0011).
- Forecast is weighted by stage probability, shown both by sale volume and by expected commission. Commission is the primary figure.
- Stage transitions are validated in the backend, for example requiring a lost reason and a price before closing.

## Consequences

- Commission forecasting and GCI reporting work from day one (ADR 0021).
- Commission fields are confidential and require field-level control (ADR 0017).
- Listing status and seller-side Deal stage must remain consistent (ADR 0008).
- Configurable stages mean reports must handle stage renames and removals using stage IDs and history.
- Accounting integration and commission payment workflows are not covered.
