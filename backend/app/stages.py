"""Build progress shown on the live home page. Updated as each stage lands."""
STAGES = [
    {"id": 0, "name": "Foundation", "adrs": "0001-0004, 0023-0030", "backend": "done", "frontend": "done", "blurb": "Database, login, audit trail, API contract"},
    {"id": 1, "name": "Contacts, Companies & Properties", "adrs": "0005, 0006, 0015", "backend": "done", "frontend": "done", "blurb": "Owner graph, duplicate detection, global search"},
    {"id": 2, "name": "Leads & Listings", "adrs": "0007, 0008", "backend": "done", "frontend": "done", "blurb": "Hold/sell triggers, listing pipeline, buyer interest"},
    {"id": 3, "name": "Deals & Pipelines", "adrs": "0010", "backend": "done", "frontend": "done", "blurb": "Kanban pipeline, commission splits, stage history"},
    {"id": 4, "name": "Activities, Notes & Documents", "adrs": "0011, 0012, 0013", "backend": "done", "frontend": "done", "blurb": "Tasks, cadences, timeline, document versions"},
    {"id": 5, "name": "Investors & Funds", "adrs": "0009", "backend": "done", "frontend": "done", "blurb": "Investor profiles, syndications, listing matching"},
    {"id": 6, "name": "Reports & Dashboard", "adrs": "0021", "backend": "building", "frontend": "soon", "blurb": "Production, forecast, owner recency"},
    {"id": 7, "name": "Platform", "adrs": "0014, 0016-0020, 0022", "backend": "soon", "frontend": "soon", "blurb": "Email, import/export, permissions, custom fields, rules, mobile"},
    {"id": 8, "name": "Hardening", "adrs": "all", "backend": "soon", "frontend": "soon", "blurb": "Full test run, demo polish"},
]
