"""Background jobs (ADR 0026): idempotent functions in a registry, run on demand or by an in-process scheduler."""
import threading
import time
import traceback
from typing import Callable

from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from ..models.core_sys import JobRun

REGISTRY: dict[str, Callable[[Session], dict]] = {}
DESCRIPTIONS: dict[str, str] = {}


def job(name: str, description: str):
    def deco(fn):
        REGISTRY[name] = fn
        DESCRIPTIONS[name] = description
        return fn
    return deco


def run_job(db: Session, name: str) -> JobRun:
    run = JobRun(name=name, started_at=utcnow(), status="running")
    db.add(run)
    db.commit()
    try:
        summary = REGISTRY[name](db) or {}
        run.status, run.summary = "ok", summary
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        run = db.get(JobRun, run.id)
        run.status, run.summary = "failed", {"error": str(e), "trace": traceback.format_exc()[-800:]}
    run.finished_at = utcnow()
    db.commit()
    return run


_started = False


def start_scheduler(interval_seconds: int = 3600):
    """One lightweight thread. Only safe with a single worker process (see ADR 0026)."""
    global _started
    if _started:
        return
    _started = True

    def loop():
        time.sleep(30)
        while True:
            for name in list(REGISTRY):
                with SessionLocal() as db:
                    run_job(db, name)
            time.sleep(interval_seconds)

    threading.Thread(target=loop, daemon=True, name="trg-scheduler").start()
