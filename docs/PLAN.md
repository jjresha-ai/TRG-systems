# Implementation plan

Order follows the MVP build order in `research/01-basic-crm-features.md` and ADR 0004 (backend, tests, then UI for each stage). Each stage ends with passing backend tests (pytest), a Playwright spec for the UI, and a commit.

| Stage | ADRs | Backend | Frontend |
|---|---|---|---|
| 0 | 0001-0004, 0023-0030 | Scaffold, DB, auth, health, audit core | App shell, login, live build-progress home |
| 1 | 0005, 0006, 0015 | Contacts, companies, properties, ownership, dedupe/merge, search | Contacts, companies, properties, owner graph, global search |
| 2 | 0007, 0008 | Leads, hold/sell triggers, scoring, listings, buyer interest | Prospecting board, listings, buyer interest |
| 3 | 0010 | Pipelines, stages, deals, parties, splits, stage history | Kanban pipeline, deal detail |
| 4 | 0011, 0012, 0013 | Activities/tasks, cadences, notes, documents | Tasks, timeline, notes, documents |
| 5 | 0009 | Investors, funds, commitments, matching | Investors, funds, match view |
| 6 | 0021 | Report catalog, goals, snapshots | Dashboard and reports |
| 7 | 0014, 0016, 0017, 0018, 0019, 0020, 0022 | Email capture, import/export, permissions, audit view, custom fields, rules, mobile endpoints | Inbox, import, admin, audit, mobile quick-add |
| 8 | all | Full-suite run, demo data integrity | Full Playwright run, polish |

Demo data is real rows in the database from a one-year deterministic seed (200+ contacts, 200+ activities and supporting records), not mocks.
