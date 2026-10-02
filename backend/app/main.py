import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import Base, engine
from .routers import auth, system, contacts, companies, properties, search, leads, listings, jobs, deals, work, investors, reports, platform, data, admin, rules, email, mobile
from . import models  # noqa: F401  (register tables)
from .services import prospecting, listings as listings_svc, deals as deals_svc, work as work_svc, investors as investors_svc, reports as reports_svc, rules as rules_svc  # noqa: F401  (register jobs, hooks)

ROUTERS = [system.router, auth.router, contacts.router, companies.router, properties.router, search.router, leads.router, listings.router, jobs.router, deals.router, work.router, investors.router, reports.router, platform.router, data.router, admin.router, rules.router, email.router, mobile.router]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    if os.environ.get("TRG_SCHEDULER", "1") == "1":
        from .services.jobs import start_scheduler
        start_scheduler()
    yield


app = FastAPI(title="TRG Systems API", version="0.1.0", lifespan=lifespan,
              description="CRM for The Resha Group and 1880 Capital")
for r in ROUTERS:
    app.include_router(r)
