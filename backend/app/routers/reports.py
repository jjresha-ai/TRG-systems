from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..db import get_db
from ..models.core_sys import User
from ..models.reports import GOAL_METRICS, GOAL_PERIODS, Goal
from ..security import ROLE_ACTIONS, current_user, require
from ..services import reports as svc

router = APIRouter(prefix="/api", tags=["reports"])


def respond(db: Session, user: User, name: str, report: dict, fmt: str | None):
    if fmt == "csv":
        if "export" not in ROLE_ACTIONS.get(user.role, set()):
            raise HTTPException(403, f"Role '{user.role}' may not export")
        db.info["actor"], db.info["actor_id"] = user.name, user.id
        log_event(db, "export", "reports", None, {"report": name, "rows": len(report["rows"])})  # exports are audited (ADR 0018)
        db.commit()
        return Response(svc.to_csv(report), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    if fmt not in (None, "json"):
        raise HTTPException(422, "format must be json or csv")
    return report


@router.get("/reports/production")
def production(period: str | None = None, start: date | None = None, end: date | None = None, group_by: str = "broker", property_type: str | None = None, owner_id: int | None = None,
               format: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return respond(db, user, "production", svc.production(db, user, period, start, end, group_by, property_type, owner_id), format)


@router.get("/reports/pipeline")
def pipeline(group_by: str = "stage", pipeline: str | None = None, format: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return respond(db, user, "pipeline", svc.pipeline_report(db, user, group_by, pipeline), format)


@router.get("/reports/listings")
def listings(expiring_within_days: int = Query(60, ge=1, le=365), format: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return respond(db, user, "listings", svc.listings_report(db, user, expiring_within_days), format)


@router.get("/reports/buyer-interest")
def buyer_interest(status: str = "active", format: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return respond(db, user, "buyer-interest", svc.buyer_interest_report(db, user, status), format)


@router.get("/reports/prospecting")
def prospecting(period: str | None = None, start: date | None = None, end: date | None = None, format: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return respond(db, user, "prospecting", svc.prospecting(db, user, period, start, end), format)


@router.get("/reports/owner-recency")
def recency(days: int = Query(90, ge=1), entity: str = "contact", owner_id: int | None = None, format: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return respond(db, user, "owner-recency", svc.recency(db, user, days, entity, owner_id), format)


@router.get("/reports/time-in-stage")
def time_in_stage(pipeline: str = "seller", format: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return respond(db, user, "time-in-stage", svc.time_in_stage(db, user, pipeline), format)


@router.get("/reports/investor-capital")
def investor_capital(format: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return respond(db, user, "investor-capital", svc.investor_capital(db, user), format)


@router.get("/reports/pipeline-trend")
def trend(weeks: int = Query(52, ge=1, le=156), db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return svc.pipeline_trend(db, user, weeks)


@router.post("/reports/snapshot")
def snapshot(db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    r = svc.take_snapshot(db)
    db.commit()
    return r


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.dashboard(db, user)


# ---------------- goals ----------------
class GoalIn(BaseModel):
    user_id: int | None = None
    metric: str
    period_type: str
    period_start: date
    target: int = Field(gt=0)


@router.get("/goals")
def goals(year: int | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return svc.goals_actuals(db, user, year)


@router.post("/goals", status_code=201)
def add_goal(body: GoalIn, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    if body.metric not in GOAL_METRICS:
        raise HTTPException(422, f"metric must be one of {GOAL_METRICS}")
    if body.period_type not in GOAL_PERIODS:
        raise HTTPException(422, f"period_type must be one of {GOAL_PERIODS}")
    ps = body.period_start
    if (body.period_type == "year" and (ps.month, ps.day) != (1, 1)) or (body.period_type == "quarter" and (ps.month not in (1, 4, 7, 10) or ps.day != 1)) or (body.period_type == "month" and ps.day != 1):
        raise HTTPException(422, "period_start must be the first day of the period")
    if db.scalar(select(Goal).where(Goal.user_id.is_(body.user_id) if body.user_id is None else Goal.user_id == body.user_id, Goal.metric == body.metric, Goal.period_type == body.period_type, Goal.period_start == ps)):
        raise HTTPException(409, "A goal for that user, metric and period already exists")
    g = Goal(**body.model_dump())
    db.add(g)
    db.commit()
    return {"id": g.id}


@router.patch("/goals/{gid}")
def patch_goal(gid: int, body: dict, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    g = db.get(Goal, gid)
    if not g:
        raise HTTPException(404, "Goal not found")
    t = body.get("target")
    if not isinstance(t, int) or t <= 0:
        raise HTTPException(422, "target must be a positive integer")
    g.target = t
    db.commit()
    return {"id": g.id, "target": g.target}
