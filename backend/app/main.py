from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import Base, engine
from .routers import auth, system
from . import models  # noqa: F401  (register tables)

ROUTERS = [system.router, auth.router]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="TRG Systems API", version="0.1.0", lifespan=lifespan,
              description="CRM for The Resha Group and 1880 Capital")
for r in ROUTERS:
    app.include_router(r)
