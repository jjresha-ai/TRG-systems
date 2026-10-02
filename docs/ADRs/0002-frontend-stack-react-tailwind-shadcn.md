# 2. Frontend Stack: React, Tailwind CSS, and shadcn/ui

Date: 2026-10-02

## Status

Accepted

## Context

TRG Systems needs a frontend that is fast to build, easy to maintain, and visually polished. The primary users are commercial real estate brokers and investors who will judge the tool on clarity and professionalism as much as on features. We also expect AI coding agents to do a significant share of the UI work, so the stack should be one they know well and that produces consistent results.

## Decision

We will build the frontend with:

- **React** for the component model and UI logic.
- **Tailwind CSS** for styling, using design tokens (colors, spacing, type scale) defined in the Tailwind config / CSS variables rather than ad hoc values.
- **shadcn/ui** for the component foundation. Components are copied into the repository (not installed as an opaque dependency), so we own and can freely customize them. They build on Radix UI primitives for accessibility.

To make the interface aesthetically pleasing rather than generic, UI work will be done with the **frontend-design skill**. Agents and contributors building or restyling screens should use it, and should aim for a deliberate, cohesive visual identity (typography, color, spacing, motion) instead of default component styling.

## Consequences

- Consistent, accessible components with minimal custom CSS.
- Full ownership of component code; no upgrade lock-in to a UI library, but we maintain the copied components ourselves.
- Tailwind class-heavy markup has a learning curve and needs discipline (shared tokens, extracted components) to stay readable.
- Relying on the frontend-design skill gives better visual quality, but results still need human review for brand fit and usability.
- Build tooling (e.g. Vite or Next.js), state management, and data fetching are not decided here and will get their own ADRs.
