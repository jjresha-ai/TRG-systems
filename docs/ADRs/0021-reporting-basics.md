# 21. Reporting Basics

Date: 2026-10-02

## Status

Proposed

## Context

Jim's scorecard is sale listings and closed deals, so reporting must answer pipeline and production questions first. In CRE, expected commission and GCI matter more than deal amount. Trend reporting needs history, which must be captured from the start because it cannot be reconstructed later. See research section 7.

## Decision

Reports are a fixed catalog of **backend-defined report endpoints** with filters, grouping and CSV export. A user-built report designer is not included.

Initial catalog:
- **Production**: listings taken and closed deals by broker, period and property type; closed volume and GCI versus goal.
- **Pipeline**: by stage, owner, property type and market; weighted forecast by volume and by expected commission, by close month (ADR 0010).
- **Listings**: by status, days on market, and expiring in the next N days (ADR 0008).
- **Buyer interest** per listing: inquiries, CAs, OM sends, tours, offers.
- **Prospecting**: leads by source and conversion rate (ADR 0007), activity counts per user, and owner-contact recency (records untouched for 90 days).
- **Time in stage** and stalled deals.
- **Investor capital** raised by fund and commitment status (ADR 0009).

Rules:
- Reports reuse the shared filter definition (ADR 0015) and apply permissions and field-level restrictions (ADR 0017).
- **History** needed for trends comes from DealStageHistory and the audit trail. **Periodic snapshots** of pipeline totals are stored (daily or weekly) so past forecasts can be compared with outcomes.
- Goals (production targets per user and period) are stored data.
- Scheduled email delivery of reports waits on the email and job runner decisions.

## Consequences

- The scorecard metrics are available as soon as listings and deals exist.
- A fixed catalog is fast to build and test but cannot answer arbitrary questions; ad hoc analysis is served by export.
- Snapshots begin accumulating only once enabled, so they should be turned on early.
- Dashboards in the UI present these endpoints and own no calculation logic (ADR 0004).
