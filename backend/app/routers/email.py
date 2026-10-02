from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import current_actor, current_actor_id, log_event
from ..db import get_db, utcnow
from ..models.core import Contact
from ..models.core_sys import User
from ..models.mail import (VISIBILITY, BulkSend, CalendarEvent, EmailAccountConnection, EmailAssociation, EmailContactShare, EmailMessage, EmailTemplate, ExclusionRule, Unsubscribe)
from ..models.pipeline import Listing
from ..models.platform import ListDef
from ..security import current_user, require
from ..services import filters as flt
from ..services import mail as svc
from ..services.common import user_names
from ..services.visibility import Visibility
from ..services.work import check_record

router = APIRouter(prefix="/api", tags=["email"])


def _conn_out(c: EmailAccountConnection | None, user: User) -> dict:
    p = svc.provider_for(c)
    return {"provider": c.provider if c else "capture", "email_address": c.email_address if c else user.email, "status": c.status if c else "active", "bcc_token": c.bcc_token if c else None,
            "bcc_address": f"capture+{c.bcc_token}@crm.trg.invalid" if c else None, "can_send": p.name != "capture", "providers_available": ["capture"], "planned_providers": ["microsoft365", "google"],
            "last_synced_at": c.last_synced_at if c else None, "has_tokens": bool(c and c.tokens_encrypted)}


@router.get("/email/connection")
def connection(db: Session = Depends(get_db), user: User = Depends(require("view"))):
    c = svc.get_connection(db, user)
    db.commit()
    return _conn_out(c, user)


class ConnIn(BaseModel):
    email_address: str | None = None
    tokens: dict | None = None  # stored encrypted, never returned


@router.put("/email/connection")
def put_connection(body: ConnIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    c = svc.get_connection(db, user)
    if body.email_address:
        if "@" not in body.email_address:
            raise HTTPException(422, "A valid email address is required")
        c.email_address = body.email_address.strip().lower()
    if body.tokens is not None:
        c.tokens_encrypted = svc.encrypt_tokens(body.tokens)
    db.commit()
    return _conn_out(c, user)


class CaptureIn(BaseModel):
    from_addr: str
    to_addrs: list[str] = []
    cc_addrs: list[str] = []
    subject: str | None = None
    body: str | None = None
    sent_at: datetime | None = None
    message_id: str | None = None
    thread_id: str | None = None
    direction: str | None = None
    visibility: str | None = None


@router.post("/email/capture", status_code=201)
def capture(body: CaptureIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    r = svc.capture_message(db, user, body.model_dump(), "api")
    db.commit()
    return r


@router.post("/public/email/bcc/{token}", status_code=201, tags=["public"])
def bcc(token: str, body: CaptureIn, db: Session = Depends(get_db)):
    """BCC-to-CRM fallback: the per-user secret in the URL identifies who is capturing. Captured messages stay private to that user by default."""
    conn = db.scalar(select(EmailAccountConnection).where(EmailAccountConnection.bcc_token == token))
    if not conn or conn.status != "active":
        raise HTTPException(404, "Unknown capture address")
    user = db.get(User, conn.user_id)
    current_actor.set(f"{user.name} (BCC capture)")
    db.info["actor"], db.info["actor_id"] = f"{user.name} (BCC capture)", user.id
    r = svc.capture_message(db, user, body.model_dump(), "bcc")
    db.commit()
    return r


@router.get("/email/messages")
def messages(record_type: str | None = None, record_id: int | None = None, mine: bool = False, unlinked: bool = False, q: str | None = None, direction: str | None = None,
             page: int = Query(1, ge=1), limit: int = Query(30, le=100), db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(EmailMessage)
    if mine:
        stmt = stmt.where(EmailMessage.user_id == user.id)
    else:
        stmt = stmt.where(or_(EmailMessage.user_id == user.id, EmailMessage.visibility != "private"))
    if record_type and record_id:
        stmt = stmt.where(EmailMessage.id.in_(select(EmailAssociation.email_id).where(EmailAssociation.record_type == record_type, EmailAssociation.record_id == record_id)))
    if unlinked:
        stmt = stmt.where(EmailMessage.user_id == user.id, ~EmailMessage.id.in_(select(EmailAssociation.email_id)))
    if direction:
        stmt = stmt.where(EmailMessage.direction == direction)
    if q:
        stmt = stmt.where(EmailMessage.user_id == user.id, or_(EmailMessage.subject.ilike(f"%{q}%"), EmailMessage.from_addr.ilike(f"%{q}%")))  # only your own mail is searchable
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(EmailMessage.sent_at.desc()).offset((page - 1) * limit).limit(limit)).all()
    names = user_names(db)
    return {"total": total, "items": [x for x in (svc.message_out(m, user, names) for m in rows) if x]}


def _mine(db, mid, user) -> EmailMessage:
    m = db.get(EmailMessage, mid)
    if not m or m.user_id != user.id:
        raise HTTPException(404, "Message not found")
    return m


class ShareIn(BaseModel):
    level: str


@router.post("/email/messages/{mid}/share")
def share_message(mid: int, body: ShareIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    if body.level not in VISIBILITY:
        raise HTTPException(422, f"level must be one of {VISIBILITY}")
    m = _mine(db, mid, user)
    m.visibility = body.level
    db.commit()
    return {"id": m.id, "visibility": m.visibility}


class AssocIn(BaseModel):
    record_type: str
    record_id: int


@router.post("/email/messages/{mid}/associate", status_code=201)
def associate(mid: int, body: AssocIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    m = _mine(db, mid, user)
    check_record(db, body.record_type, body.record_id)
    if not any(a.record_type == body.record_type and a.record_id == body.record_id for a in m.associations):
        m.associations.append(EmailAssociation(record_type=body.record_type, record_id=body.record_id, auto=False))
        if body.record_type == "contact":
            c = db.get(Contact, body.record_id)
            if c.last_contact_at is None or c.last_contact_at < m.sent_at:
                c.last_contact_at, c.last_contact_user_id = m.sent_at, user.id
    db.commit()
    return {"id": m.id, "associations": [{"record_type": a.record_type, "record_id": a.record_id} for a in m.associations]}


class ContactShareIn(BaseModel):
    contact_id: int
    level: str


@router.get("/email/shares")
def shares(db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return {"items": [{"contact_id": s.contact_id, "contact": db.get(Contact, s.contact_id).full_name, "level": s.level} for s in db.scalars(select(EmailContactShare).where(EmailContactShare.user_id == user.id))]}


@router.put("/email/shares")
def share_contact(body: ContactShareIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    if body.level not in VISIBILITY:
        raise HTTPException(422, f"level must be one of {VISIBILITY}")
    if not db.get(Contact, body.contact_id):
        raise HTTPException(422, "Unknown contact")
    s = db.scalar(select(EmailContactShare).where(EmailContactShare.user_id == user.id, EmailContactShare.contact_id == body.contact_id))
    if s:
        s.level = body.level
    else:
        db.add(EmailContactShare(user_id=user.id, contact_id=body.contact_id, level=body.level))
    updated = 0
    for m in db.scalars(select(EmailMessage).where(EmailMessage.user_id == user.id, EmailMessage.id.in_(select(EmailAssociation.email_id).where(EmailAssociation.record_type == "contact", EmailAssociation.record_id == body.contact_id)))):
        m.visibility, updated = body.level, updated + 1
    db.commit()
    return {"contact_id": body.contact_id, "level": body.level, "messages_updated": updated}


@router.delete("/email/shares/{contact_id}", status_code=204)
def unshare_contact(contact_id: int, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    s = db.scalar(select(EmailContactShare).where(EmailContactShare.user_id == user.id, EmailContactShare.contact_id == contact_id))
    if s:
        db.delete(s)
    for m in db.scalars(select(EmailMessage).where(EmailMessage.user_id == user.id, EmailMessage.id.in_(select(EmailAssociation.email_id).where(EmailAssociation.record_type == "contact", EmailAssociation.record_id == contact_id)))):
        m.visibility = "private"
    db.commit()


# ---------------- exclusion rules ----------------
class ExclIn(BaseModel):
    kind: str
    value: str = Field(min_length=2)


@router.get("/email/exclusions")
def exclusions(db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return {"items": [{"id": r.id, "kind": r.kind, "value": r.value} for r in db.scalars(select(ExclusionRule).where(ExclusionRule.user_id == user.id).order_by(ExclusionRule.id))]}


@router.post("/email/exclusions", status_code=201)
def add_exclusion(body: ExclIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    if body.kind not in ("domain", "address", "keyword"):
        raise HTTPException(422, "kind must be domain, address or keyword")
    r = ExclusionRule(user_id=user.id, kind=body.kind, value=body.value.strip().lower())
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.delete("/email/exclusions/{rid}", status_code=204)
def del_exclusion(rid: int, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    r = db.get(ExclusionRule, rid)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Not found")
    db.delete(r)
    db.commit()


# ---------------- templates ----------------
class TplIn(BaseModel):
    name: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


@router.get("/email/templates")
def templates(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return {"items": [{"id": t.id, "name": t.name, "subject": t.subject, "body": t.body} for t in db.scalars(select(EmailTemplate).order_by(EmailTemplate.name))], "merge_fields": sorted(svc.MERGE_FIELDS)}


@router.post("/email/templates", status_code=201)
def add_template(body: TplIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    svc.validate_template(body.subject, body.body)
    if db.scalar(select(EmailTemplate).where(EmailTemplate.name == body.name)):
        raise HTTPException(409, "A template with that name exists")
    t = EmailTemplate(**body.model_dump(), owner_user_id=user.id)
    db.add(t)
    db.commit()
    return {"id": t.id}


class RenderIn(BaseModel):
    contact_id: int
    listing_id: int | None = None
    property_id: int | None = None


@router.post("/email/templates/{tid}/render")
def render(tid: int, body: RenderIn, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    t = db.get(EmailTemplate, tid)
    c = db.get(Contact, body.contact_id)
    if not t or not c or c.deleted_at or not Visibility(db, user).can_see(c):
        raise HTTPException(404, "Template or contact not found")
    if c.do_not_contact:
        raise HTTPException(409, f"{c.full_name} is marked do-not-contact; outreach is blocked")
    listing = db.get(Listing, body.listing_id) if body.listing_id else None
    from ..models.core import Property
    prop = db.get(Property, body.property_id) if body.property_id else None
    return svc.render(db, t, c, user, listing, prop)


# ---------------- bulk (prepare only until a provider is chosen) and unsubscribe ----------------
class BulkIn(BaseModel):
    name: str = Field(min_length=1)
    template_id: int
    list_id: int | None = None
    contact_ids: list[int] | None = None
    listing_id: int | None = None


@router.post("/email/bulk", status_code=201)
def prepare_bulk(body: BulkIn, db: Session = Depends(get_db), user: User = Depends(require("export"))):
    t = db.get(EmailTemplate, body.template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    if not body.list_id and not body.contact_ids:
        raise HTTPException(422, "Provide list_id or contact_ids")
    if body.list_id:
        l = db.get(ListDef, body.list_id)
        if not l or l.entity != "contact" or (l.visibility == "private" and l.owner_user_id != user.id):
            raise HTTPException(404, "Contact list not found")
        ids = l.members or [] if l.kind == "static" else flt.matching_ids(db, "contact", l.filter, user)
    else:
        ids = body.contact_ids
    vis = Visibility(db, user)
    contacts = [c for c in (db.get(Contact, i) for i in ids) if c and vis.can_see(c)]
    listing = db.get(Listing, body.listing_id) if body.listing_id else None
    b = svc.prepare_bulk(db, user, body.name, t, contacts, listing, body.list_id)
    db.info["actor"], db.info["actor_id"] = user.name, user.id
    log_event(db, "bulk_email_prepared", "bulk_sends", b.id, {"counts": b.counts})
    db.commit()
    return _bulk_out(b, False)


def _bulk_out(b: BulkSend, full: bool) -> dict:
    return {"id": b.id, "name": b.name, "status": b.status, "counts": b.counts, "list_id": b.list_id, "listing_id": b.listing_id, "tracking_enabled": b.tracking_enabled, "provider_connected": False,
            "created_at": b.created_at, **({"recipients": b.recipients} if full else {"sample": b.recipients[:10]})}


@router.get("/email/bulk")
def bulk_list(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return {"items": [_bulk_out(b, False) for b in db.scalars(select(BulkSend).order_by(BulkSend.id.desc()).limit(30))]}


@router.get("/email/bulk/{bid}")
def bulk_get(bid: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    b = db.get(BulkSend, bid)
    if not b:
        raise HTTPException(404, "Not found")
    return _bulk_out(b, True)


@router.post("/email/bulk/{bid}/send")
def bulk_send(bid: int, db: Session = Depends(get_db), user: User = Depends(require("export"))):
    b = db.get(BulkSend, bid)
    if not b:
        raise HTTPException(404, "Not found")
    svc.provider_for(svc.get_connection(db, user, create=False)).send(None, [], "", "")  # raises 501 until a real provider is connected
    return {"status": "sent"}


@router.get("/public/unsubscribe", tags=["public"])
def unsubscribe_get(token: str, db: Session = Depends(get_db)):
    return _unsub(db, token)


@router.post("/public/unsubscribe", tags=["public"])
def unsubscribe_post(token: str, db: Session = Depends(get_db)):
    return _unsub(db, token)


def _unsub(db: Session, token: str):
    email = svc.read_unsubscribe_token(token)
    if not email:
        raise HTTPException(400, "Invalid unsubscribe link")
    if not db.scalar(select(Unsubscribe).where(Unsubscribe.email == email)):
        db.add(Unsubscribe(email=email, source="bulk email link", at=utcnow()))
        db.commit()
    return {"unsubscribed": email}


# ---------------- calendar ----------------
class AttendeeIn(BaseModel):
    email: str
    name: str | None = None


class EventIn(BaseModel):
    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    start: datetime
    end: datetime
    location: str | None = None
    attendees: list[AttendeeIn] = []
    visibility: str | None = None


@router.post("/calendar/events", status_code=201)
def add_event(body: EventIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    d = body.model_dump()
    if d["visibility"] and d["visibility"] not in VISIBILITY:
        raise HTTPException(422, f"visibility must be one of {VISIBILITY}")
    r = svc.capture_event(db, user, d)
    db.commit()
    return r


@router.get("/calendar/events")
def events(start: datetime | None = None, end: datetime | None = None, record_type: str | None = None, record_id: int | None = None, mine: bool = False,
           db: Session = Depends(get_db), user: User = Depends(require("view"))):
    from ..models.mail import CalendarAssociation
    stmt = select(CalendarEvent).where(CalendarEvent.start_at >= (start or utcnow() - timedelta(days=1)), CalendarEvent.start_at <= (end or utcnow() + timedelta(days=30)))
    stmt = stmt.where(CalendarEvent.user_id == user.id) if mine else stmt.where(or_(CalendarEvent.user_id == user.id, CalendarEvent.visibility != "private"))
    if record_type and record_id:
        stmt = stmt.where(CalendarEvent.id.in_(select(CalendarAssociation.event_id).where(CalendarAssociation.record_type == record_type, CalendarAssociation.record_id == record_id)))
    names = user_names(db)
    return {"items": [x for x in (svc.event_out(e, user, names) for e in db.scalars(stmt.order_by(CalendarEvent.start_at))) if x]}


@router.get("/email/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require("view"))):
    since = utcnow() - timedelta(days=30)
    base = select(func.count()).select_from(EmailMessage).where(EmailMessage.user_id == user.id)
    return {"last_30_days": {"inbound": db.scalar(base.where(EmailMessage.sent_at >= since, EmailMessage.direction == "inbound")), "outbound": db.scalar(base.where(EmailMessage.sent_at >= since, EmailMessage.direction == "outbound"))},
            "unlinked": db.scalar(base.where(~EmailMessage.id.in_(select(EmailAssociation.email_id)))), "private": db.scalar(base.where(EmailMessage.visibility == "private")),
            "shared": db.scalar(base.where(EmailMessage.visibility != "private")), "unsubscribed": db.scalar(select(func.count()).select_from(Unsubscribe))}


# ---------------- timeline integration ----------------
def _timeline(db, record_type, record_id, user, names):
    from ..models.mail import CalendarAssociation
    out = []
    stmt = select(EmailMessage).where(EmailMessage.id.in_(select(EmailAssociation.email_id).where(EmailAssociation.record_type == record_type, EmailAssociation.record_id == record_id)), or_(EmailMessage.user_id == user.id, EmailMessage.visibility != "private")).order_by(EmailMessage.sent_at.desc()).limit(60)
    for m in db.scalars(stmt):
        d = svc.message_out(m, user, names)
        if d:
            out.append({"kind": "email", "at": m.sent_at, "data": d})
    for e in db.scalars(select(CalendarEvent).where(CalendarEvent.id.in_(select(CalendarAssociation.event_id).where(CalendarAssociation.record_type == record_type, CalendarAssociation.record_id == record_id)), or_(CalendarEvent.user_id == user.id, CalendarEvent.visibility != "private")).limit(40)):
        d = svc.event_out(e, user, names)
        if d:
            out.append({"kind": "event", "at": e.start_at, "data": d})
    return out


from .work import TIMELINE_PROVIDERS  # noqa: E402
TIMELINE_PROVIDERS.append(_timeline)
