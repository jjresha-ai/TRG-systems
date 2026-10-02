from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.core_sys import JobRun, User
from ..security import require
from ..services import jobs as jobs_svc

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    out = []
    for name, desc in jobs_svc.DESCRIPTIONS.items():
        last = db.scalar(select(JobRun).where(JobRun.name == name).order_by(JobRun.id.desc()))
        out.append({"name": name, "description": desc, "last_run": {"status": last.status, "started_at": last.started_at, "finished_at": last.finished_at, "summary": last.summary} if last else None})
    return out


@router.post("/{name}/run")
def run(name: str, db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    if name not in jobs_svc.REGISTRY:
        raise HTTPException(404, "Unknown job")
    r = jobs_svc.run_job(db, name)
    return {"id": r.id, "status": r.status, "summary": r.summary}


@router.get("/runs")
def runs(limit: int = 25, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return [{"id": r.id, "name": r.name, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at, "summary": r.summary}
            for r in db.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(limit))]
