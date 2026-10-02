"""Workflow rules engine (ADR 0020, 0034): code-defined triggers and a fixed, reviewed action set. Idempotent; every action audited with the rule as the actor."""
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import current_actor, current_actor_id
from ..db import utcnow
from ..models.core import Contact, Company, Property
from ..models.core_sys import AuditEvent, User
from ..models.deals import Deal, Stage
from ..models.pipeline import Lead, Listing
from ..models.platform import AppSetting
from ..models.security import ACTION_TYPES, RULE_ENTITIES, TRIGGER_TYPES, Rule, RuleActionLog, RuleRun
from ..models.work import Activity, ActivityAssociation, CadenceTemplate, Notification
from . import filters as flt
from . import prospecting, work
from .jobs import job

ENTITY_MODELS = {"contact": Contact, "company": Company, "property": Property, "listing": Listing, "deal": Deal, "lead": Lead}
TABLE_ENTITY = {"contacts": "contact", "companies": "company", "properties": "property", "listings": "listing", "deals": "deal", "leads": "lead"}
SET_FIELD_WHITELIST = {"contact": {"lifecycle_stage": ["prospect", "active_relationship", "client", "past_client", "inactive"], "status": ["active", "inactive"]},
                       "property": {"hold_intent": ["unknown", "hold", "open_to_sell", "selling_soon"]}, "lead": {"status": ["new", "contacted", "qualified"]}, "company": {}, "listing": {}, "deal": {}}
DATE_FIELDS = {"property": ["loan_maturity_date"], "listing": ["expiration_date", "agreement_date"], "deal": ["expected_close_date", "dd_expiry_date", "listing_expiration_date", "loan_contingency_date"], "contact": [], "company": [], "lead": []}
OUTREACH = {"call", "email", "text"}


# ---------------- validation ----------------
def validate_rule(db: Session, data: dict, user: User):
    ent, trig = data["entity"], data["trigger_type"]
    if ent not in RULE_ENTITIES:
        raise HTTPException(422, f"entity must be one of {RULE_ENTITIES}")
    if trig not in TRIGGER_TYPES:
        raise HTTPException(422, f"trigger_type must be one of {TRIGGER_TYPES}")
    cfg = data.get("trigger_config") or {}
    fields = flt.fields_for(db, ent, user)
    if trig == "field_changed":
        if not cfg.get("field"):
            raise HTTPException(422, "field_changed needs trigger_config.field")
        M = ENTITY_MODELS[ent]
        if cfg["field"] not in M.__table__.columns:
            raise HTTPException(422, f"Unknown {ent} field: {cfg['field']}")
    elif trig == "stage_changed":
        if ent != "deal":
            raise HTTPException(422, "stage_changed applies to deals")
    elif trig == "date_reached":
        if cfg.get("date_field") not in DATE_FIELDS.get(ent, []):
            raise HTTPException(422, f"date_reached on {ent} supports {DATE_FIELDS.get(ent)}")
        if not isinstance(cfg.get("offset_days", 0), int):
            raise HTTPException(422, "offset_days must be an integer")
    elif trig == "scheduled":
        if not isinstance(cfg.get("cooldown_days", 365), int) or cfg.get("cooldown_days", 365) < 1:
            raise HTTPException(422, "cooldown_days must be a positive integer")
    if data.get("conditions"):
        flt.validate(data["conditions"], fields)
    actions = data.get("actions") or []
    if not actions:
        raise HTTPException(422, "A rule needs at least one action")
    for a in actions:
        t, p = a.get("type"), a.get("params") or {}
        if t not in ACTION_TYPES:
            raise HTTPException(422, f"Action type must be one of {ACTION_TYPES} (rules cannot send email or messages)")
        if t == "assign_owner":
            if not db.get(User, p.get("user_id") or 0):
                raise HTTPException(422, "assign_owner needs a valid user_id")
        elif t == "create_task":
            if not p.get("subject"):
                raise HTTPException(422, "create_task needs a subject")
            if not isinstance(p.get("days_due", 0), int) or p.get("days_due", 0) < 0:
                raise HTTPException(422, "days_due must be a non-negative integer")
            if p.get("type", "other") not in work.ACTIVITY_TYPES:
                raise HTTPException(422, f"task type must be one of {work.ACTIVITY_TYPES}")
            if p.get("assignee", "owner") != "owner" and not db.get(User, p["assignee"]):
                raise HTTPException(422, "assignee must be 'owner' or a user id")
        elif t == "apply_cadence":
            c = db.get(CadenceTemplate, p.get("cadence_id") or 0)
            if not c:
                raise HTTPException(422, "apply_cadence needs a valid cadence_id")
            if c.record_type not in ("any", ent):
                raise HTTPException(422, f"That cadence applies to {c.record_type} records, not {ent}")
        elif t == "create_lead":
            if ent != "property":
                raise HTTPException(422, "create_lead applies to property rules")
        elif t == "notify":
            if not p.get("message"):
                raise HTTPException(422, "notify needs a message")
            if p.get("user", "owner") != "owner" and not db.get(User, p["user"]):
                raise HTTPException(422, "notify user must be 'owner' or a user id")
        elif t == "set_field":
            allowed = SET_FIELD_WHITELIST.get(ent, {})
            if p.get("field") not in allowed:
                raise HTTPException(422, f"set_field on {ent} supports {list(allowed) or 'nothing'}")
            if p.get("value") not in allowed[p["field"]]:
                raise HTTPException(422, f"{p['field']} must be one of {allowed[p['field']]}")


# ---------------- action execution ----------------
def _owner_of(obj):
    return getattr(obj, "owner_user_id", None)


def _contact_of(db, entity, obj):
    if entity == "contact":
        return obj
    if entity == "lead" and obj.contact_id:
        return db.get(Contact, obj.contact_id)
    return None


def run_action(db: Session, rule: Rule, entity: str, obj, idx: int, action: dict, trigger_key: str, dry: bool) -> str:
    key = f"r{rule.id}:{entity}:{obj.id}:{trigger_key}:a{idx}"
    if db.scalar(select(RuleActionLog.id).where(RuleActionLog.key == key)):
        return "already done"
    t, p = action["type"], action.get("params") or {}
    result = "done"
    today = date.today()
    if t == "assign_owner":
        if not dry:
            obj.owner_user_id = p["user_id"]
        result = f"assigned to user {p['user_id']}"
    elif t == "create_task":
        ttype = p.get("type", "other")
        c = _contact_of(db, entity, obj)
        if ttype in OUTREACH and c is not None and c.do_not_contact:
            result = "skipped: do-not-contact"
        else:
            assignee = _owner_of(obj) if p.get("assignee", "owner") == "owner" else p["assignee"]
            due = datetime.combine(today + timedelta(days=p.get("days_due", 0)), datetime.min.time()) + timedelta(hours=9)
            if not dry:
                a = Activity(type=ttype, subject=p["subject"].replace("{name}", _label(entity, obj)), status="planned", due_at=due, assignee_user_id=assignee, priority=p.get("priority", "normal"), source_key=key)
                a.associations.append(ActivityAssociation(record_type=entity, record_id=obj.id))
                db.add(a)
            result = f"task due {due.date().isoformat()}"
    elif t == "apply_cadence":
        cad = db.get(CadenceTemplate, p["cadence_id"])
        c = _contact_of(db, entity, obj)
        if c is not None and c.do_not_contact and any(s.get("type") in OUTREACH for s in cad.steps):
            result = "skipped: do-not-contact"
        else:
            if not dry:
                work.apply_cadence(db, cad, entity, obj.id, today, _owner_of(obj), _owner_of(obj) or 0)
            result = f"cadence '{cad.name}' applied"
    elif t == "create_lead":
        if db.scalar(select(Lead.id).where(Lead.property_id == obj.id, Lead.status.in_(["new", "contacted", "qualified"]))):
            result = "skipped: open lead exists"
        else:
            if not dry:
                from ..models.pipeline import LeadSource
                src = db.scalar(select(LeadSource).where(LeadSource.name == "Workflow rule")) or LeadSource(name="Workflow rule")
                db.add(src)
                db.flush()
                contact, company = prospecting.primary_principal(db, obj)
                score, comp = prospecting.score_lead(db, obj, [], obj.last_contact_at)
                db.add(Lead(name=contact.full_name if contact else (company.name if company else "Unknown owner"), company_name=company.name if company else None, stream="seller", source_id=src.id,
                            score=score, score_components=comp, owner_user_id=prospecting.pick_assignee(db, obj), property_id=obj.id, contact_id=contact.id if contact else None,
                            company_id=company.id if company else None, trigger_reason={"matches": [{"rule": rule.name, "kind": "workflow", "detail": f"Rule '{rule.name}' fired"}]}))
            result = "seller lead created"
    elif t == "notify":
        uid = _owner_of(obj) if p.get("user", "owner") == "owner" else p["user"]
        if uid is None:
            result = "skipped: no owner to notify"
        else:
            if not dry:
                db.add(Notification(user_id=uid, kind="rule", message=p["message"].replace("{name}", _label(entity, obj)), record_type=entity, record_id=obj.id, key=key))
            result = f"notified user {uid}"
    elif t == "set_field":
        if not dry:
            setattr(obj, p["field"], p["value"])
        result = f"{p['field']} = {p['value']}"
    if not dry:
        db.add(RuleActionLog(rule_id=rule.id, key=key, entity=entity, entity_id=obj.id, action_type=t, result=result[:200], at=utcnow()))
        db.flush()
    return result


def _label(entity, obj) -> str:
    return {"contact": lambda o: o.full_name, "company": lambda o: o.name, "property": lambda o: o.address, "listing": lambda o: o.property.address, "deal": lambda o: o.name, "lead": lambda o: o.name}[entity](obj)


# ---------------- evaluation ----------------
_SYSTEM = User(id=0, email="rules@system", name="rules", role="admin", salt="", password_hash="")


def conditions_match(db: Session, rule: Rule, obj, ctx: dict, fields) -> bool:
    if not rule.conditions:
        return True
    return flt.evaluate(db, rule.conditions, obj, fields, ctx, date.today())


def fire(db: Session, rule: Rule, entity: str, obj, trigger_key: str, run: RuleRun, dry: bool, details: list | None = None):
    run.matched += 1
    for i, a in enumerate(rule.actions):
        r = run_action(db, rule, entity, obj, i, a, trigger_key, dry)
        if r == "already done":
            run.skipped += 1
        elif r.startswith("skipped"):
            run.skipped += 1
        else:
            run.actions_taken += 1
        if details is not None:
            details.append({"entity_id": obj.id, "label": _label(entity, obj), "action": a["type"], "result": r})


def _begin(db, rule, dry) -> RuleRun:
    run = RuleRun(rule_id=rule.id, started_at=utcnow(), dry_run=dry)
    db.add(run)
    db.flush()
    return run


def evaluate_scan_rule(db: Session, rule: Rule, dry: bool = False, today: date | None = None) -> tuple[RuleRun, list]:
    """date_reached and scheduled rules scan all visible records of the entity."""
    today = today or date.today()
    run, details = _begin(db, rule, dry), []
    actor_before = current_actor.get()
    current_actor.set(f"rule:{rule.name}")
    db.info["actor"], db.info["actor_id"] = f"rule:{rule.name}", None
    try:
        M = ENTITY_MODELS[rule.entity]
        fields = flt.fields_for(db, rule.entity, _SYSTEM)
        ctx: dict = {}
        stmt = select(M)
        if hasattr(M, "deleted_at"):
            stmt = stmt.where(M.deleted_at.is_(None))
        for obj in db.scalars(stmt).unique():
            run.evaluated += 1
            if rule.trigger_type == "date_reached":
                d = getattr(obj, rule.trigger_config["date_field"], None)
                if not d:
                    continue
                if isinstance(d, datetime):
                    d = d.date()
                due = d + timedelta(days=int(rule.trigger_config.get("offset_days", 0)))
                if not (due <= today <= due + timedelta(days=int(rule.trigger_config.get("grace_days", 30)))):
                    continue
                key = f"date:{d.isoformat()}"
            else:
                cool = int(rule.trigger_config.get("cooldown_days", 365))
                key = f"sched:{today.toordinal() // cool}"
            if not conditions_match(db, rule, obj, ctx, fields):
                continue
            fire(db, rule, rule.entity, obj, key, run, dry, details)
        run.status = "ok"
    except Exception as e:  # noqa: BLE001
        run.status, run.error = "failed", str(e)[:290]
    finally:
        current_actor.set(actor_before)
    run.finished_at = utcnow()
    db.flush()
    return run, details


def cursor(db: Session) -> int:
    s = db.get(AppSetting, "rules_cursor")
    return (s.value or {}).get("id", 0) if s else 0


def set_cursor(db: Session, v: int):
    s = db.get(AppSetting, "rules_cursor")
    if s:
        s.value = {"id": v}
    else:
        db.add(AppSetting(key="rules_cursor", value={"id": v}))


def process_events(db: Session, limit: int = 5000) -> dict:
    """Event rules (created / field changed / stage changed) read new audit events after a stored cursor."""
    rules = db.scalars(select(Rule).where(Rule.enabled.is_(True), Rule.trigger_type.in_(["record_created", "field_changed", "stage_changed"]))).all()
    last = cursor(db)
    events = db.scalars(select(AuditEvent).where(AuditEvent.id > last, AuditEvent.entity_type.in_(list(TABLE_ENTITY)), AuditEvent.action.in_(["create", "update"])).order_by(AuditEvent.id).limit(limit)).all()
    stages = {s.id: s.key for s in db.scalars(select(Stage))}
    stats = {"events": len(events), "matched": 0, "actions": 0}
    runs: dict[int, RuleRun] = {}
    actor_before = current_actor.get()
    for ev in events:
        if (ev.actor or "").startswith("rule:"):
            continue  # a rule's own writes never trigger rules (prevents loops)
        entity = TABLE_ENTITY[ev.entity_type]
        M = ENTITY_MODELS[entity]
        obj = db.get(M, ev.entity_id)
        if obj is None or getattr(obj, "deleted_at", None):
            continue
        for rule in rules:
            if rule.entity != entity or ev.timestamp < rule.created_at:
                continue  # rules only react to changes made after they exist
            tc = rule.trigger_config or {}
            key = None
            if rule.trigger_type == "record_created" and ev.action == "create":
                key = "created"
            elif rule.trigger_type == "field_changed" and ev.action == "update" and tc.get("field") in (ev.changes or {}):
                old, new = ev.changes[tc["field"]]
                if ("to" not in tc or str(new) == str(tc["to"])) and ("from" not in tc or str(old) == str(tc["from"])):
                    key = f"chg:{ev.id}"
            elif rule.trigger_type == "stage_changed" and ev.action == "update" and "stage_id" in (ev.changes or {}):
                new_key = stages.get(ev.changes["stage_id"][1])
                if "to_stage" not in tc or new_key == tc["to_stage"]:
                    key = f"stg:{ev.id}"
            if key is None:
                continue
            fields = flt.fields_for(db, entity, _SYSTEM)
            if not conditions_match(db, rule, obj, {}, fields):
                continue
            current_actor.set(f"rule:{rule.name}")
            db.info["actor"], db.info["actor_id"] = f"rule:{rule.name}", None
            run = runs.get(rule.id) or _begin(db, rule, False)
            runs[rule.id] = run
            run.evaluated += 1
            before = run.actions_taken
            fire(db, rule, entity, obj, key, run, False)
            stats["matched"] += 1
            stats["actions"] += run.actions_taken - before
    current_actor.set(actor_before)
    for run in runs.values():
        run.finished_at, run.status = utcnow(), "ok"
    if events:
        # events written by the actions above are consumed on the next pass but skipped by the rule: actor check
        set_cursor(db, max(e.id for e in events))
    db.flush()
    return stats


def preview_rule(db: Session, rule: Rule, limit: int = 25) -> dict:
    """Dry run: which records would match right now and what would happen. Writes nothing."""
    if rule.trigger_type in ("date_reached", "scheduled"):
        run, details = evaluate_scan_rule(db, rule, dry=True)
        out = {"matched": run.matched, "evaluated": run.evaluated, "sample": details[:limit]}
        db.rollback()
        return out
    M = ENTITY_MODELS[rule.entity]
    fields = flt.fields_for(db, rule.entity, _SYSTEM)
    ctx: dict = {}
    stmt = select(M)
    if hasattr(M, "deleted_at"):
        stmt = stmt.where(M.deleted_at.is_(None))
    hits = [o for o in db.scalars(stmt).unique() if conditions_match(db, rule, o, ctx, fields)]
    return {"matched": len(hits), "evaluated": None, "note": "Event rules fire when a matching change happens. These records satisfy the conditions now.",
            "sample": [{"entity_id": o.id, "label": _label(rule.entity, o)} for o in hits[:limit]]}


@job("rules_events", "Process new audit events for created / field-changed / stage-changed rules")
def _job_events(db: Session) -> dict:
    return process_events(db)


@job("rules_scheduled", "Evaluate date-reached and scheduled rules")
def _job_scheduled(db: Session) -> dict:
    n = a = 0
    for rule in db.scalars(select(Rule).where(Rule.enabled.is_(True), Rule.trigger_type.in_(["date_reached", "scheduled"]))).all():
        run, _ = evaluate_scan_rule(db, rule)
        n += run.matched
        a += run.actions_taken
    return {"matched": n, "actions": a}
