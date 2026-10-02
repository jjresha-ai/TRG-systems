# 9. Investor Profiles and Funds/Syndications

Date: 2026-10-02

## Status

Proposed

## Context

1880 Capital needs investor and syndicator relationships tracked alongside the brokerage pipeline. Investors are a distinct contact type with investment criteria, accreditation status and commitment history. Matching investors to listings is a key workflow. Post-close LP reporting (distributions, capital calls) is handled by tools like Juniper Square and is out of scope here. See the research entity model summary and open questions.

## Decision

- **InvestorProfile**: attached to a Contact or Company, with asset classes, geographies and markets, check size range, target return notes, 1031 exchange status and deadlines, accreditation status with date verified, and preferred contact channel.
- **Fund** (syndication or capital raise vehicle): name, sponsor, status, target raise, minimum investment, related Properties and Deals.
- **Commitment**: Investor, Fund, amount, status (interested, soft-circled, committed, funded), and dates.
- **Matching** is a backend query that ranks InvestorProfiles against a Listing by asset class, market, price versus check size and 1031 timing, returning the reasons for each match. It is a ranked suggestion, not an automated action.
- Accreditation and investor data are treated as sensitive: access is role-restricted (ADR 0017) and audited (ADR 0018).
- No LP portal, capital calls or distributions are built. Those remain with an external tool if needed.

## Consequences

- Investor outreach for a new listing is a query plus a list (ADR 0015), not a manual search.
- Securities rules (Reg D, general solicitation, accreditation verification) constrain how fund marketing is done. The research is unverified on these points and must be checked with counsel before any fund-facing feature is built.
- Keeping investor criteria structured, not in notes, is what makes matching possible; data entry discipline matters.
