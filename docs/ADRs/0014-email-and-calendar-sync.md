# 14. Email and Calendar Sync

Date: 2026-10-02

## Status

Proposed

## Context

Brokers will not log manually, so auto-capture decides whether the CRM is used. Brokers live in Outlook, but Microsoft 365 versus Google has not been decided. Principals negotiate confidentially, so privacy controls are essential. Buyer email blasts also bring CAN-SPAM obligations. See research section 6.

## Decision

Email and calendar sync is built against a provider-agnostic interface, so the provider choice (a separate ADR, listed in open decisions) does not reshape the model.

- **EmailAccountConnection**: user, provider, OAuth tokens (encrypted), granted scopes, sync cursor, and status.
- **EmailMessage** and **CalendarEvent** are stored with thread ID, participants, subject, body, timestamps and direction.
- **Auto-association** matches participant addresses to Contact emails (normalized, ADR 0006) and links the message to those Contacts, and to related open Deals and Properties where unambiguous.
- **Privacy.** Each user has exclusion rules (domains, addresses, keywords). Excluded messages are never stored. Messages are `private` to the connecting user by default and can be shared to the team per message or per contact. Only metadata (date, participants, subject if permitted) is shared by default.
- Email and meetings update last-contact data (ADR 0011).
- **Templates** with merge fields, and **BCC-to-CRM** as a fallback capture path.
- **Bulk send** (listing blasts) is a separate path with unsubscribe handling and do-not-contact checks (ADR 0012). Tracking (opens, clicks) is optional and off by default.
- Start with one-way capture (read and associate), then add sending and scheduling links.

## Consequences

- OAuth token handling is security-critical and needs encryption and rotation rules, covered in the authentication and hosting decisions.
- Provider API limits, consent screens and app verification can take weeks. This should start early.
- Storing email bodies raises retention and privacy exposure; a retention policy is needed.
- Privacy-by-default may reduce firm-wide visibility of "who last spoke to this owner"; metadata sharing is the compromise.
- Meeting and email tracking features are not decided here.
