# 22. Mobile Access

Date: 2026-10-02

## Status

Proposed

## Context

Brokers are in cars and at site tours. The highest-value mobile functions are owner lookup from the street (by address or location), quick note and task capture, photos, caller-ID context, and voice-to-note. The research treats mobile as the last item in the MVP order, and native apps are a heavy build for a small team. See research section 12.

## Decision

- **Phase one is a responsive, installable web app (PWA)** using the same React frontend (ADR 0002) and the same API. No native app is built in this phase.
- No new entities are required. Mobile uses the existing API with these backend additions:
  - a **quick-add** endpoint creating a note, task or call log against a record in one request;
  - **lookup by address or coordinates** returning the property, its owners and principals, and last-contact data (ADR 0005, ADR 0015);
  - **photo and file upload** through the document model (ADR 0013);
  - **caller lookup by phone number** returning the matching Contact and recent history.
- **Voice notes** are captured with on-device speech-to-text where available. Server-side transcription is a later decision and a possible vendor dependency.
- Offline support is limited to read-only access to recently viewed and starred records, and queued quick-adds. Full offline editing is not included.
- Push notifications for task reminders are deferred until the background job runner and hosting decisions are made.
- Native iOS or Android apps, and OS-level caller ID, would require a new ADR.

## Consequences

- Mobile ships with no separate codebase, and every API improvement benefits it.
- PWA limits (notably on iOS) mean no true caller-ID overlay or deep device integration.
- Offline queues need conflict handling rules when queued edits sync later.
- Voice transcription quality and privacy depend on the approach chosen later.
