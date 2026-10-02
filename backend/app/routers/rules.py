from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.core_sys import User
from ..models.security import ACTION_TYPES, RULE_ENTITIES, TRIGGER_TYPES, Rule, RuleActionLog, RuleRun
from ..security import require
from ..services import rules as svc
from ..services.common import user_names

router = APIRouter(prefix="/api", tags=["automation"])


class RuleIn(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    entity: str
    trigger_type: str
    trigger_config: dict = {}
    conditions: dict | None = None
    actions: list[dict]
    enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_config: dict | None = None
    conditions: dict | None = None
    actions: list[dict] | None = None
    enabled: bool | None = None


def rule_out(db: Session, r: Rule, names: dict) -> dict:
    last = db.scalar(select(RuleRun).where(RuleRun.rule_id == r.id, RuleRun.dry_run.is_(False)).order_by(RuleRun.id.desc()))
    n = db.query(RuleActionLog).filter(RuleActionLog.rule_id == r.id).count()
    return {"id": r.id, "name": r.name, "description": r.description, "owner": names.get(r.owner_user_id), "owner_user_id": r.owner_user_id, "enabled": r.enabled, "entity": r.entity, "trigger_type": r.trigger_type,
            "trigger_config": r.trigger_config, "conditions": r.conditions, "actions": r.actions, "actions_logged": n,
            "last_run": {"at": last.finished_at, "status": last.status, "matched": last.matched, "actions_taken": last.actions_taken} if last else None}


def _rule(db, rid) -> Rule:
    r = db.get(Rule, rid)
    if not r:
        raise HTTPException(404, "Rule not found")
    return r


@router.get("/rules/meta")
def meta(_: User = Depends(require("view"))):
    return {"entities": RULE_ENTITIES, "triggers": TRIGGER_TYPES, "actions": ACTION_TYPES, "date_fields": svc.DATE_FIELDS, "set_field": svc.SET_FIELD_WHITELIST}


@router.get("/rules")
def rules(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    names = user_names(db)
    return {"items": [rule_out(db, r, names) for r in db.scalars(select(Rule).order_by(Rule.id))]}


@router.post("/rules", status_code=201)
def add_rule(body: RuleIn, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    svc.validate_rule(db, body.model_dump(), user)
    r = Rule(**body.model_dump(), owner_user_id=user.id)
    db.add(r)
    db.commit()
    return rule_out(db, r, user_names(db))


@router.patch("/rules/{rid}")
def patch_rule(rid: int, body: RulePatch, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    r = _rule(db, rid)
    d = body.model_dump(exclude_unset=True)
    svc.validate_rule(db, {"entity": r.entity, "trigger_type": r.trigger_type, "trigger_config": d.get("trigger_config", r.trigger_config), "conditions": d.get("conditions", r.conditions),
                           "actions": d.get("actions", r.actions)}, user)
    for k, v in d.items():
        setattr(r, k, v)
    db.commit()
    return rule_out(db, r, user_names(db))


@router.delete("/rules/{rid}", status_code=204)
def delete_rule(rid: int, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    r = _rule(db, rid)
    r.enabled = False  # rules with history are disabled, not deleted, so their run log stays attributable
    if not db.query(RuleActionLog).filter(RuleActionLog.rule_id == rid).count():
        db.query(RuleRun).filter(RuleRun.rule_id == rid).delete()
        db.delete(r)
    db.commit()


@router.post("/rules/{rid}/preview")
def preview(rid: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return svc.preview_rule(db, _rule(db, rid))


@router.post("/rules/{rid}/run")
def run_now(rid: int, db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    r = _rule(db, rid)
    if r.trigger_type in ("date_reached", "scheduled"):
        run, details = svc.evaluate_scan_rule(db, r)
        db.commit()
        return {"matched": run.matched, "actions_taken": run.actions_taken, "skipped": run.skipped, "status": run.status, "sample": details[:25]}
    stats = svc.process_events(db)
    db.commit()
    return stats


@router.get("/rules/{rid}/runs")
def runs(rid: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    _rule(db, rid)
    return {"items": [{"id": x.id, "started_at": x.started_at, "finished_at": x.finished_at, "status": x.status, "dry_run": x.dry_run, "evaluated": x.evaluated, "matched": x.matched, "actions_taken": x.actions_taken,
                       "skipped": x.skipped, "error": x.error} for x in db.scalars(select(RuleRun).where(RuleRun.rule_id == rid).order_by(RuleRun.id.desc()).limit(30))]}


@router.get("/rules/{rid}/log")
def action_log(rid: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    _rule(db, rid)
    return {"items": [{"at": x.at, "entity": x.entity, "entity_id": x.entity_id, "action": x.action_type, "result": x.result} for x in db.scalars(select(RuleActionLog).where(RuleActionLog.rule_id == rid).order_by(RuleActionLog.id.desc()).limit(100))]}
