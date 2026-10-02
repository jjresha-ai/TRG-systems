"""Custom fields on core entities (ADR 0019): typed, validated, audited; retiring hides but keeps data."""
import re
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.core_sys import User
from ..models.platform import FIELD_TYPES, FieldDefinition
from ..security import can_see_commission

ENTITIES = ["contact", "company", "property", "listing", "deal", "investor", "fund"]
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def definitions(db: Session, entity: str, active_only=True) -> list[FieldDefinition]:
    stmt = select(FieldDefinition).where(FieldDefinition.entity == entity)
    if active_only:
        stmt = stmt.where(FieldDefinition.active.is_(True))
    return list(db.scalars(stmt.order_by(FieldDefinition.position, FieldDefinition.id)))


def _context(entity: str, obj) -> dict:
    """Facts that required_when/show_when can test."""
    ctx = {}
    if obj is None:
        return ctx
    if entity == "property":
        ctx["property_type"] = obj.property_type
    if entity == "listing":
        ctx["property_type"] = obj.property.property_type
        ctx["status"] = obj.status
    if entity == "deal":
        ctx["pipeline"] = obj.pipeline.key
        ctx["property_type"] = obj.property.property_type if obj.property else None
    if entity == "contact":
        ctx["lifecycle_stage"] = obj.lifecycle_stage
    return ctx


def _match(cond: dict | None, ctx: dict) -> bool:
    return bool(cond) and all(ctx.get(k) == v for k, v in cond.items())


def _check_value(d: FieldDefinition, v):
    t = d.type
    if v is None:
        return None
    if t in ("text", "long_text"):
        if not isinstance(v, str):
            raise HTTPException(422, f"{d.label} must be text")
        if len(v) > (4000 if t == "long_text" else 300):
            raise HTTPException(422, f"{d.label} is too long")
        return v
    if t in ("number", "currency"):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise HTTPException(422, f"{d.label} must be a number")
        return v
    if t == "date":
        try:
            return date.fromisoformat(str(v)[:10]).isoformat()
        except ValueError:
            raise HTTPException(422, f"{d.label} must be an ISO date")
    if t == "checkbox":
        if not isinstance(v, bool):
            raise HTTPException(422, f"{d.label} must be true or false")
        return v
    if t == "single_select":
        if v not in d.options:
            raise HTTPException(422, f"{d.label} must be one of {d.options}")
        return v
    if t == "multi_select":
        if not isinstance(v, list) or any(x not in d.options for x in v):
            raise HTTPException(422, f"{d.label} must be a list drawn from {d.options}")
        return sorted(set(v))
    if t == "lookup_user":
        return v
    if t == "lookup_record":
        if not isinstance(v, int):
            raise HTTPException(422, f"{d.label} must be a record id")
        return v
    return v


def validate_custom(db: Session, entity: str, existing: dict | None, updates: dict | None, obj, user: User | None, creating: bool = False) -> dict:
    """Returns the new custom dict. Unknown and retired keys are rejected; required fields are enforced when custom data is written."""
    defs = {d.key: d for d in definitions(db, entity)}
    out = dict(existing or {})
    for k, v in (updates or {}).items():
        d = defs.get(k)
        if d is None:
            raise HTTPException(422, f"Unknown or retired custom field: {k}")
        if d.restricted and user is not None and not can_see_commission(user):
            raise HTTPException(403, f"Your role may not edit {d.label}")
        if d.type == "lookup_user" and v is not None and not db.get(User, v):
            raise HTTPException(422, f"{d.label}: unknown user")
        val = _check_value(d, v)
        if val is None:
            out.pop(k, None)
        else:
            out[k] = val
    if creating or updates:
        ctx = _context(entity, obj)
        for d in defs.values():
            req = d.required or _match(d.required_when, ctx)
            if req and out.get(d.key) in (None, "", []):
                raise HTTPException(422, f"{d.label} is required")
    return out


def visible_custom(db: Session, entity: str, custom: dict | None, user: User) -> dict:
    """Only active, permitted fields are exposed (retired data is kept but hidden)."""
    if not custom:
        return {}
    allowed = {d.key for d in definitions(db, entity) if not (d.restricted and not can_see_commission(user))}
    return {k: v for k, v in custom.items() if k in allowed}


def create_definition(db: Session, data: dict) -> FieldDefinition:
    if data["entity"] not in ENTITIES:
        raise HTTPException(422, f"entity must be one of {ENTITIES}")
    if data["type"] not in FIELD_TYPES:
        raise HTTPException(422, f"type must be one of {FIELD_TYPES}")
    if not KEY_RE.match(data["key"]):
        raise HTTPException(422, "key must be lowercase letters, digits and underscores, starting with a letter")
    if db.scalar(select(FieldDefinition).where(FieldDefinition.entity == data["entity"], FieldDefinition.key == data["key"])):
        raise HTTPException(409, "A field with that key already exists on this entity (retired fields keep their key)")
    if data["type"] in ("single_select", "multi_select") and not data.get("options"):
        raise HTTPException(422, "Select fields need options")
    if data["type"] == "lookup_record" and not data.get("options"):
        raise HTTPException(422, "lookup_record needs the target record type in options")
    d = FieldDefinition(**data)
    d.position = len(definitions(db, data["entity"], active_only=False))
    db.add(d)
    db.flush()
    return d
