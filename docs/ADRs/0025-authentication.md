# 025. Authentication

Date: 2026-10-02

## Status

Accepted

## Context

ADR 0017 defines roles and permissions but not how users sign in. Full SSO/MFA is out of scope for the first release.

## Decision

- Email and password sign-in. Passwords hashed with PBKDF2-SHA256 (stdlib) with per-user salt.
- Successful sign-in returns a signed, expiring bearer token (HMAC-SHA256, stdlib). The server signing secret comes from the environment, with a dev default that is refused when `TRG_ENV=production`.
- Failed and successful logins are audited (ADR 0018).
- Every endpoint except login and health requires a token. Role checks follow ADR 0017.
- SSO and MFA are deferred to a superseding ADR.

## Consequences

Short-lived stateless tokens cannot be revoked individually before expiry. Acceptable for the demo; API tokens (ADR 0017) will be stored and revocable.
