import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..db import get_db, utcnow
from ..models.core import Company, Contact, Property
from ..models.core_sys import AuditEvent, User
from ..models.deals import Deal
from ..models.investors import InvestorProfile
from ..models.pipeline import Lead, Listing
from ..models.platform import AppSetting
from ..models.security import ApiToken
from ..models.work import Activity
from ..security import ROLE_ACTIONS, ROLES, current_user, hash_api_token, hash_password, new_salt, require

router = APIRouter(prefix="/api", tags=["admin"])

OWNED = {"contact": Contact, "company": Company, "property": Property, "listing": Listing, "deal": Deal, "lead": Lead, "investor": InvestorProfile}


def _user(db, uid) -> User:
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


def user_admin_out(db: Session, u: User) -> dict:
    owned = {k: db.scalar(select(func.count()).select_from(M).where(M.owner_user_id == u.id, *([M.deleted_at.is_(None)] if hasattr(M, "deleted_at") else []))) for k, M in OWNED.items()}
    tasks = db.scalar(select(func.count()).select_from(Activity).where(Activity.assignee_user_id == u.id, Activity.status == "planned"))
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "title": u.title, "team": u.team, "active": u.active, "owned": owned, "open_tasks": tasks, "owns_records": sum(owned.values()) + tasks}


def _active_admins(db) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True)))


class UserIn(BaseModel):
    email: str
    name: str = Field(min_length=1)
    role: str = "broker"
    title: str | None = None
    team: str | None = None
    password: str = Field(min_length=8)


class UserPatch(BaseModel):
    name: str | None = None
    title: str | None = None
    team: str | None = None
    role: str | None = None


@router.get("/admin/users")
def admin_users(db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    return {"items": [user_admin_out(db, u) for u in db.scalars(select(User).order_by(User.active.desc(), User.name))], "roles": ROLES, "role_actions": {r: sorted(a) for r, a in ROLE_ACTIONS.items()}}


@router.post("/admin/users", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(422, "A valid email is required")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "A user with that email exists")
    salt = new_salt()
    u = User(email=email, name=body.name, role=body.role, title=body.title, team=body.team, salt=salt, password_hash=hash_password(body.password, salt))
    db.add(u)
    db.commit()
    return user_admin_out(db, u)


@router.patch("/admin/users/{uid}")
def patch_user(uid: int, body: UserPatch, db: Session = Depends(get_db), admin: User = Depends(require("admin"))):
    u = _user(db, uid)
    d = body.model_dump(exclude_unset=True)
    if "role" in d:
        if d["role"] not in ROLES:
            raise HTTPException(422, f"role must be one of {ROLES}")
        if u.role == "admin" and d["role"] != "admin" and u.active and _active_admins(db) <= 1:
            raise HTTPException(409, "There must be at least one active admin")
        if d["role"] != u.role:
            log_event(db, "role_change", "users", u.id, {"from": u.role, "to": d["role"], "by": admin.name})  # permission and role changes are always audited
    for k, v in d.items():
        setattr(u, k, v)
    db.commit()
    return user_admin_out(db, u)


class PasswordIn(BaseModel):
    password: str = Field(min_length=8)


@router.post("/admin/users/{uid}/reset-password")
def reset_password(uid: int, body: PasswordIn, db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    u = _user(db, uid)
    u.salt = new_salt()
    u.password_hash = hash_password(body.password, u.salt)
    log_event(db, "password_reset", "users", u.id, {})
    db.commit()
    return {"ok": True}


class DeactivateIn(BaseModel):
    reassign_to: int | None = None


def reassign_all(db: Session, from_id: int, to_id: int) -> dict:
    moved = {}
    for k, M in OWNED.items():
        rows = db.scalars(select(M).where(M.owner_user_id == from_id)).all()
        for r in rows:
            r.owner_user_id = to_id
        moved[k] = len(rows)
    acts = db.scalars(select(Activity).where(Activity.assignee_user_id == from_id, Activity.status == "planned")).all()
    for a in acts:
        a.assignee_user_id = to_id
    moved["open_tasks"] = len(acts)
    log_event(db, "ownership_transfer", "users", from_id, {"to": to_id, "moved": moved})
    return moved


@router.post("/admin/users/{uid}/deactivate")
def deactivate(uid: int, body: DeactivateIn, db: Session = Depends(get_db), admin: User = Depends(require("admin"))):
    u = _user(db, uid)
    if u.id == admin.id:
        raise HTTPException(409, "You cannot deactivate yourself")
    if not u.active:
        raise HTTPException(409, "Already inactive")
    if u.role == "admin" and _active_admins(db) <= 1:
        raise HTTPException(409, "There must be at least one active admin")
    info = user_admin_out(db, u)
    moved = None
    if info["owns_records"]:
        if not body.reassign_to:
            raise HTTPException(409, {"message": "This user still owns records. Reassign them first.", "owned": info["owned"], "open_tasks": info["open_tasks"]})
        target = _user(db, body.reassign_to)
        if not target.active or target.id == u.id:
            raise HTTPException(422, "reassign_to must be a different, active user")
        moved = reassign_all(db, u.id, target.id)
    u.active = False
    for t in db.scalars(select(ApiToken).where(ApiToken.user_id == u.id, ApiToken.revoked_at.is_(None))):
        t.revoked_at = utcnow()  # offboarding revokes API access
    log_event(db, "user_deactivated", "users", u.id, {"reassigned": moved})
    db.commit()
    return {"user": user_admin_out(db, u), "reassigned": moved}


@router.post("/admin/users/{uid}/reactivate")
def reactivate(uid: int, db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    u = _user(db, uid)
    u.active = True
    db.commit()
    return user_admin_out(db, u)


class TransferIn(BaseModel):
    entity: str
    ids: list[int] = Field(min_length=1)
    to_user_id: int


@router.post("/ownership/transfer")
def transfer(body: TransferIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    M = OWNED.get(body.entity)
    if not M:
        raise HTTPException(422, f"entity must be one of {list(OWNED)}")
    target = db.get(User, body.to_user_id)
    if not target or not target.active:
        raise HTTPException(422, "to_user_id must be an active user")
    rows = []
    for i in body.ids:
        o = db.get(M, i)
        if not o or getattr(o, "deleted_at", None):
            raise HTTPException(422, f"Unknown {body.entity} #{i}")
        if user.role not in ("admin", "manager") and o.owner_user_id != user.id:
            raise HTTPException(403, f"You can only transfer records you own (#{i} belongs to someone else)")
        rows.append(o)
    for o in rows:
        log_event(db, "ownership_transfer", M.__tablename__, o.id, {"from": o.owner_user_id, "to": target.id})
        o.owner_user_id = target.id
    db.commit()
    return {"transferred": len(rows), "to": target.name}


# ---------------- API tokens ----------------
class TokenIn(BaseModel):
    name: str = Field(min_length=1)
    scopes: list[str] = Field(min_length=1)
    expires_days: int | None = Field(default=90, ge=1, le=730)


def _token_out(t: ApiToken, names: dict) -> dict:
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "scopes": t.scopes, "user_id": t.user_id, "owner": names.get(t.user_id), "created_at": t.created_at, "expires_at": t.expires_at,
            "revoked_at": t.revoked_at, "last_used_at": t.last_used_at, "active": t.revoked_at is None and (t.expires_at is None or t.expires_at > utcnow())}


@router.get("/tokens")
def tokens(all: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(ApiToken).order_by(ApiToken.id.desc())
    if not (all and user.role == "admin"):
        stmt = stmt.where(ApiToken.user_id == user.id)
    names = {u.id: u.name for u in db.scalars(select(User))}
    return {"items": [_token_out(t, names) for t in db.scalars(stmt)]}


@router.post("/tokens", status_code=201)
def create_token(body: TokenIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if getattr(user, "token_scopes", None) is not None:
        raise HTTPException(403, "API tokens cannot create other tokens")
    allowed = ROLE_ACTIONS.get(user.role, set()) - {"admin"}
    bad = [s for s in body.scopes if s not in allowed]
    if bad:
        raise HTTPException(422, f"Scopes not allowed for role '{user.role}': {bad}")
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    token = f"trg_{prefix}_{secret}"
    t = ApiToken(user_id=user.id, name=body.name, prefix=prefix, token_hash=hash_api_token(token), scopes=sorted(set(body.scopes)), expires_at=utcnow() + timedelta(days=body.expires_days) if body.expires_days else None)
    db.add(t)
    db.commit()
    return {**_token_out(t, {user.id: user.name}), "token": token, "note": "Copy this token now. It is shown only once."}


@router.delete("/tokens/{tid}", status_code=204)
def revoke_token(tid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = db.get(ApiToken, tid)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Token not found")
    t.revoked_at = utcnow()
    db.commit()


# ---------------- audit view (admin only) ----------------
def _audit_out(e: AuditEvent) -> dict:
    return {"id": e.id, "timestamp": e.timestamp, "actor": e.actor, "actor_user_id": e.actor_user_id, "action": e.action, "entity_type": e.entity_type, "entity_id": e.entity_id, "changes": e.changes}


@router.get("/audit")
def audit(user_id: int | None = None, actor: str | None = None, entity_type: str | None = None, entity_id: int | None = None, action: str | None = None, start: datetime | None = None,
          end: datetime | None = None, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    stmt = select(AuditEvent)
    if user_id:
        stmt = stmt.where(AuditEvent.actor_user_id == user_id)
    if actor:
        stmt = stmt.where(AuditEvent.actor.ilike(f"%{actor}%"))
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if start:
        stmt = stmt.where(AuditEvent.timestamp >= start)
    if end:
        stmt = stmt.where(AuditEvent.timestamp <= end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AuditEvent.id.desc()).offset((page - 1) * limit).limit(limit)).all()
    return {"total": total, "page": page, "limit": limit, "items": [_audit_out(e) for e in rows]}


@router.get("/audit/facets")
def audit_facets(db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    return {"actions": sorted(x for (x,) in db.execute(select(AuditEvent.action).distinct())), "entity_types": sorted(x for (x,) in db.execute(select(AuditEvent.entity_type).distinct()))}


FIELD_HISTORY = {"deals": ["price", "stage_id", "gross_commission", "commission_rate_bps", "owner_user_id", "status"], "listings": ["list_price", "status", "commission_rate_bps", "owner_user_id"],
                 "properties": ["estimated_value", "owner_user_id", "hold_intent", "loan_maturity_date"], "contacts": ["owner_user_id", "lifecycle_stage"], "companies": ["owner_user_id"]}


@router.get("/audit/field-history")
def field_history(entity_type: str, entity_id: int, field: str, db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    """Per-record history of selected fields (price, stage, commission, owner), built from audit events (ADR 0018)."""
    if entity_type not in FIELD_HISTORY or field not in FIELD_HISTORY[entity_type]:
        raise HTTPException(422, f"Field history is available for {FIELD_HISTORY}")
    from ..models.deals import Stage
    names = {u.id: u.name for u in db.scalars(select(User))}
    stages = {s.id: s.name for s in db.scalars(select(Stage))}
    out = []
    for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id, AuditEvent.action.in_(["create", "update"])).order_by(AuditEvent.id)):
        if field in e.changes:
            old, new = e.changes[field]
            if field == "owner_user_id":
                old, new = names.get(old, old), names.get(new, new)
            elif field == "stage_id":
                old, new = stages.get(old, old), stages.get(new, new)
            out.append({"at": e.timestamp, "actor": e.actor, "from": old, "to": new, "event_id": e.id})
    return {"entity_type": entity_type, "entity_id": entity_id, "field": field, "items": out}


# ---------------- settings ----------------
class VisibilityIn(BaseModel):
    mode: str


@router.get("/settings")
def settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    from ..services.visibility import visibility_mode
    return {"visibility_mode": visibility_mode(db)}


@router.put("/settings/visibility")
def set_visibility(body: VisibilityIn, db: Session = Depends(get_db), admin: User = Depends(require("admin"))):
    if body.mode not in ("firm_open", "team_scoped"):
        raise HTTPException(422, "mode must be firm_open or team_scoped")
    s = db.get(AppSetting, "visibility")
    old = (s.value or {}).get("mode", "firm_open") if s else "firm_open"
    if s:
        s.value = {"mode": body.mode}
    else:
        db.add(AppSetting(key="visibility", value={"mode": body.mode}))
    log_event(db, "setting_change", "app_settings", None, {"setting": "visibility", "from": old, "to": body.mode})
    db.commit()
    return {"visibility_mode": body.mode}


class PwChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@router.post("/auth/change-password")
def change_password(body: PwChange, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if getattr(user, "token_scopes", None) is not None:
        raise HTTPException(403, "API tokens cannot change passwords")
    if hash_password(body.current_password, user.salt) != user.password_hash:
        raise HTTPException(403, "Current password is incorrect")
    user.salt = new_salt()
    user.password_hash = hash_password(body.new_password, user.salt)
    log_event(db, "password_change", "users", user.id, {})
    db.commit()
    return {"ok": True}
