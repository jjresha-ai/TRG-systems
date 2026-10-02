"""Audit trail (ADR 0018): events are written in the same transaction as the change,
through a session hook, so no code path can skip it."""
import contextvars
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect, insert
from sqlalchemy.orm import Session

from .db import utcnow

current_actor: contextvars.ContextVar[str] = contextvars.ContextVar("current_actor", default="system")
current_actor_id: contextvars.ContextVar[int | None] = contextvars.ContextVar("current_actor_id", default=None)
audit_suppressed: contextvars.ContextVar[bool] = contextvars.ContextVar("audit_suppressed", default=False)

SKIP_FIELDS = {"updated_at", "password_hash", "salt"}
SENSITIVE_FIELDS = {"accreditation_status", "commission_rate", "gross_commission"}


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (dict, list)):
        return v
    return str(v)


def _is_audited(obj) -> bool:
    return getattr(obj, "__audited__", False)


def _changes(obj) -> dict:
    out = {}
    for attr in inspect(obj).mapper.column_attrs:
        if attr.key in SKIP_FIELDS:
            continue
        hist = inspect(obj).attrs[attr.key].history
        if hist.has_changes():
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            if attr.key in SENSITIVE_FIELDS:
                out[attr.key] = ["changed", "changed"]
            else:
                out[attr.key] = [_jsonable(old), _jsonable(new)]
    return out


@event.listens_for(Session, "before_flush")
def _collect(session: Session, ctx, instances):
    if audit_suppressed.get():
        return
    pending = session.info.setdefault("_audit_pending", [])
    for obj in session.dirty:
        if _is_audited(obj) and session.is_modified(obj, include_collections=False):
            ch = _changes(obj)
            if ch:
                pending.append(("update", obj, ch))
    for obj in session.deleted:
        if _is_audited(obj):
            pending.append(("delete", obj, {}))
    for obj in session.new:
        if _is_audited(obj):
            pending.append(("create", obj, None))


@event.listens_for(Session, "after_flush")
def _write(session: Session, ctx):
    from .models.core_sys import AuditEvent

    pending = session.info.pop("_audit_pending", [])
    if not pending:
        return
    rows = []
    for action, obj, ch in pending:
        if action == "create":
            ch = {k.key: [None, _jsonable(getattr(obj, k.key))]
                  for k in inspect(obj).mapper.column_attrs
                  if k.key not in SKIP_FIELDS and k.key not in SENSITIVE_FIELDS and getattr(obj, k.key) is not None}
        rows.append(dict(
            timestamp=utcnow(), actor=current_actor.get(), actor_user_id=current_actor_id.get(),
            action=action, entity_type=obj.__tablename__, entity_id=obj.id, changes=ch,
        ))
    session.connection().execute(insert(AuditEvent.__table__), rows)


def log_event(db: Session, action: str, entity_type: str = "system", entity_id: int | None = None, changes: dict | None = None):
    from .models.core_sys import AuditEvent
    db.add(AuditEvent(timestamp=utcnow(), actor=current_actor.get(), actor_user_id=current_actor_id.get(),
                      action=action, entity_type=entity_type, entity_id=entity_id, changes=changes or {}))
