# 029. Email provider and owner-data vendors

Date: 2026-10-02

## Status

Accepted

## Context

ADR 0014 is provider-agnostic. The provider (Microsoft 365 vs Google) and owner-data vendors are not yet chosen by the business.

## Decision

- Email is implemented behind a `MailProvider` interface. The first implementation is **database-backed capture** (messages stored via the capture endpoint and BCC-to-CRM style ingestion). No live Microsoft 365 or Google connection is made until Jim chooses a provider.
- Owner and property data enters through CSV/XLSX import (ADR 0016). No vendor integration (Reonomy, PropertyRadar, CoStar) is built.

## Consequences

Live inbox sync is not part of this release. When the provider is chosen, a new adapter is added without changing the stored model.
