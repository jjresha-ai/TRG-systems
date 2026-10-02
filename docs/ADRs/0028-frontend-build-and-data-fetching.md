# 028. Frontend build tooling, state management and data fetching

Date: 2026-10-02

## Status

Accepted

## Context

ADR 0002 fixes React, Tailwind and shadcn/ui but not the build tool or data layer.

## Decision

- **Vite** with React and TypeScript (single-page app; no server rendering is needed behind login). **Tailwind CSS v4** via its Vite plugin.
- **TanStack Query** for server state, caching and refetching, so screens update as data changes. **React Router** for routing. Local UI state uses React state; no global state library.
- A typed API client in `frontend/src/api` derived from the backend's OpenAPI schema (ADR 0003).

## Consequences

No server rendering means no SEO or first-paint advantages, which are irrelevant to an authenticated CRM.
