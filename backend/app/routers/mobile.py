import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models.core import Contact, ContactPhone, Property
from ..models.core_sys import User
from ..models.deals import Deal, DealParty
from ..models.mail import QuickAddLog, Star
from ..models.work import Activity, ActivityAssociation, Note, NoteAssociation
from ..security import require
from ..services import entities as ent
from ..services import work as work_svc
from ..services.common import user_names, years_between
from ..services.normalize import norm_phone
from ..services.search import current_owners, holdings_of_contact, search
from ..services.visibility import Visibility

router = APIRouter(prefix="/api", tags=["mobile"])


class QuickAdd(BaseModel):
    kind: str  # note | task | call_log
    record_type: str
    record_id: int
    text: str | None = None
    subject: str | None = None
    due_at: datetime | None = None
    outcome: str | None = None
    client_id: str | None = Field(default=None, max_length=80)  # lets an offline queue retry without creating duplicates


@router.post("/quick-add", status_code=201)
def quick_add(body: QuickAdd, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    """One request creates a note, a task or a call log against a record (ADR 0022)."""
    if body.client_id:
        prev = db.scalar(select(QuickAddLog).where(QuickAddLog.user_id == user.id, QuickAddLog.client_id == body.client_id))
        if prev:
            return {**prev.result, "duplicate": True}
    obj = work_svc.check_record(db, body.record_type, body.record_id)
    if not Visibility(db, user).can_see(obj):
        raise HTTPException(404, "Record not found")
    link = [{"record_type": body.record_type, "record_id": body.record_id}]
    if body.kind == "note":
        if not body.text:
            raise HTTPException(422, "text is required for a note")
        n = work_svc.create_note(db, {"body": body.text, "associations": link}, user)
        res = {"kind": "note", "id": n.id}
    elif body.kind == "task":
        if not (body.subject or body.text):
            raise HTTPException(422, "subject is required for a task")
        due = body.due_at or (datetime.combine((utcnow() + timedelta(days=1)).date(), datetime.min.time()) + timedelta(hours=9))
        a = work_svc.create_activity(db, {"type": "other", "subject": body.subject or body.text, "due_at": due, "associations": link}, user.id)
        res = {"kind": "task", "id": a.id, "due_at": due.isoformat()}
    elif body.kind == "call_log":
        if body.record_type not in ("contact", "company", "property", "lead"):
            raise HTTPException(422, "call_log applies to a contact, company, property or lead")
        a = work_svc.create_activity(db, {"type": "call", "subject": body.subject or "Call", "status": "completed", "outcome": body.outcome or "spoke", "body": body.text, "associations": link}, user.id)
        res = {"kind": "call_log", "id": a.id}
    else:
        raise HTTPException(422, "kind must be note, task or call_log")
    if body.client_id:
        db.add(QuickAddLog(user_id=user.id, client_id=body.client_id, result=res))
    db.commit()
    return res


def _haversine(lat1, lng1, lat2, lng2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _prop_card(db, p: Property, names: dict, distance=None) -> dict:
    owners = current_owners(db, p.id)
    open_deals = db.scalars(select(Deal).where(Deal.property_id == p.id, Deal.status == "open", Deal.deleted_at.is_(None))).all()
    return {"id": p.id, "address": p.address, "city": p.city, "property_type": p.property_type, "subtype": p.subtype, "building_sf": p.building_sf, "estimated_value": p.estimated_value,
            "hold_intent": p.hold_intent, "loan_maturity_date": p.loan_maturity_date, "lender": p.lender, "last_contact_at": p.last_contact_at, "last_contact_by": names.get(p.last_contact_user_id),
            "broker": names.get(p.owner_user_id), "owners": owners, "open_deals": [{"id": d.id, "name": d.name, "stage": d.stage.name} for d in open_deals], "distance_m": round(distance) if distance is not None else None,
            "hold_years": ent.hold_years(db, p)}


@router.get("/lookup/address")
def lookup_address(q: str | None = None, lat: float | None = None, lng: float | None = None, radius_m: int = Query(250, ge=10, le=5000), limit: int = Query(8, le=25),
                   db: Session = Depends(get_db), user: User = Depends(require("view"))):
    """Who owns this building? By typed address/APN, or by GPS coordinates (ADR 0022)."""
    names = user_names(db)
    vis = Visibility(db, user)
    if lat is not None and lng is not None:
        rows = []
        for p in db.scalars(select(Property).where(Property.deleted_at.is_(None), Property.lat.is_not(None))):
            d = _haversine(lat, lng, p.lat, p.lng)
            if d <= radius_m and vis.can_see(p):
                rows.append((d, p))
        rows.sort(key=lambda x: x[0])
        return {"items": [_prop_card(db, p, names, d) for d, p in rows[:limit]]}
    if not q or len(q.strip()) < 2:
        raise HTTPException(422, "Provide q (address, APN or owner) or lat and lng")
    res = search(db, q, limit, {"property"}, user=user)
    return {"items": [_prop_card(db, db.get(Property, r["id"]), names) for r in res]}


@router.get("/lookup/caller")
def lookup_caller(phone: str, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    """Caller ID: who is calling, what do they own, what did we last discuss (ADR 0022)."""
    n = norm_phone(phone)
    if not n:
        raise HTTPException(422, "Not a valid phone number")
    names = user_names(db)
    vis = Visibility(db, user)
    matches = []
    for c in db.scalars(select(Contact).join(ContactPhone).where(ContactPhone.normalized == n, Contact.deleted_at.is_(None))).unique():
        if not vis.can_see(c):
            continue
        acts = db.scalars(select(Activity).where(Activity.id.in_(select(ActivityAssociation.activity_id).where(ActivityAssociation.record_type == "contact", ActivityAssociation.record_id == c.id)), Activity.status == "completed")
                          .order_by(Activity.completed_at.desc()).limit(5)).all()
        notes = db.scalars(select(Note).where(Note.deleted_at.is_(None), Note.id.in_(select(NoteAssociation.note_id).where(NoteAssociation.record_type == "contact", NoteAssociation.record_id == c.id)))
                           .order_by(Note.created_at.desc()).limit(10)).all()
        deals = db.scalars(select(Deal).join(DealParty, DealParty.deal_id == Deal.id).where(DealParty.contact_id == c.id, Deal.status == "open", Deal.deleted_at.is_(None))).unique().all()
        roles = ent.contact_summary(db, c, names, with_holdings=False)
        matches.append({"contact": {"id": c.id, "full_name": c.full_name, "title": c.title, "company": roles["company"], "contact_types": c.contact_types, "do_not_contact": c.do_not_contact,
                                    "do_not_contact_reason": c.do_not_contact_reason, "broker": names.get(c.owner_user_id), "last_contact_at": c.last_contact_at, "last_contact_by": names.get(c.last_contact_user_id)},
                        "holdings": holdings_of_contact(db, c.id)[:6], "recent_activity": [{"type": a.type, "subject": a.subject, "outcome": a.outcome, "at": a.completed_at} for a in acts],
                        "recent_notes": [{"body": x.body[:200], "at": x.created_at} for x in notes if work_svc.note_visible(x, user)][:3], "open_deals": [{"id": d.id, "name": d.name, "stage": d.stage.name} for d in deals]})
    return {"phone": n, "match": bool(matches), "matches": matches}


class StarIn(BaseModel):
    record_type: str
    record_id: int


@router.get("/stars")
def stars(db: Session = Depends(get_db), user: User = Depends(require("view"))):
    out = []
    for s in db.scalars(select(Star).where(Star.user_id == user.id).order_by(Star.id.desc())):
        o = db.get(work_svc.RECORD_MODELS[s.record_type], s.record_id)
        if o is None or getattr(o, "deleted_at", None):
            continue
        out.append({"record_type": s.record_type, "record_id": s.record_id, "label": work_svc.record_label(db, s.record_type, s.record_id)})
    return {"items": out}


@router.post("/stars", status_code=201)
def star(body: StarIn, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    work_svc.check_record(db, body.record_type, body.record_id)
    if not db.scalar(select(Star).where(Star.user_id == user.id, Star.record_type == body.record_type, Star.record_id == body.record_id)):
        db.add(Star(user_id=user.id, **body.model_dump()))
        db.commit()
    return {"starred": True}


@router.delete("/stars/{record_type}/{record_id}", status_code=204)
def unstar(record_type: str, record_id: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    s = db.scalar(select(Star).where(Star.user_id == user.id, Star.record_type == record_type, Star.record_id == record_id))
    if s:
        db.delete(s)
        db.commit()
