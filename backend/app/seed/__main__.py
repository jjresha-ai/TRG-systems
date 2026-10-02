"""Rebuild the demo database: python -m app.seed  (real rows, deterministic, one year of history)."""
import importlib
import random

from ..audit import audit_suppressed
from ..db import Base, SessionLocal, engine
from .. import models  # noqa: F401
from .users import seed_users

# Each stage appends its seeder module name here as it lands.
STAGE_SEEDERS = [
    "core_seed",
    "pipeline_seed",
    "deals_seed",
    "work_seed",
    "investors_seed",
    "reports_seed",
    "platform_seed",
    "imports_seed",
    "security_seed",
]


def main():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    random.seed(1880)
    audit_suppressed.set(True)
    with SessionLocal() as db:
        ctx = {"users": seed_users(db)}
        for name in STAGE_SEEDERS:
            importlib.import_module(f"app.seed.{name}").seed(db, ctx)
        db.commit()
    print("Seeded demo database.")


if __name__ == "__main__":
    main()
