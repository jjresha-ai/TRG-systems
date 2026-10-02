"""Activities, tasks, cadences, notes, documents (ADR 0011-0013). Business rules live here."""
import hashlib
import hmac
import re
import time
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..db import utcnow
from ..models.core import Company, Contact, Property
from ..models.core_sys import User
from ..models.deals import Deal
from ..models.pipeline import Lead, Listing
from ..models.work import (ACTIVITY_TYPES, DOC_TYPES, OUTCOMES, PRIORITIES, RECORD_TYPES, Activity, ActivityAssociation, CadenceTemplate, Document,
                           DocumentAssociation, Note, NoteAssociation, NoteVersion, Notification)
from . import merge as merge_svc

RECORD_MODELS = {"contact": Contact, "company": Company, "property": Property, "listing": Listing, "deal": Deal, "lead": Lead}
TOUCH_OUTCOMES = {"spoke", "meeting_set", "not_interested"}
OUTREACH_TYPES = {"call", "email", "text"}

for _m, _t, _i in ((ActivityAssociation, "record_type", "record_id"), (NoteAssociation, "record_type", "record_id"), (DocumentAssociation, "record_type", "record_id")):
    merge_svc.register_assoc(_m, _t, _i)


def check_record(db: Session, rtype: str, rid: int):
    if rtype not in RECORD_TYPES:
        raise HTTPException(422, f"record_type must be one of {RECORD_TYPES}")
    obj = db.get(RECORD_MODELS[rtype], rid)
    if not obj or getattr(obj, "deleted_at", None):
        raise HTTPException(422, f"Unknown {rtype} #{rid}")
    return obj


def record_label(db: Session, rtype: str, rid: int) -> str:
    o = db.get(RECORD_MODELS[rtype], rid)
    if not o:
        return f"{rtype} #{rid}"
    if rtype == "contact":
        return o.full_name
    if rtype == "company":
        return o.name
    if rtype == "property":
        return o.address
    if rtype == "listing":
        return f"Listing: {o.property.address}"
    return o.name


# ---------------- activities ----------------
def _assert_not_dnc(db: Session, a: Activity):
    if a.type not in OUTREACH_TYPES:
        return
    for x in a.associations:
        if x.record_type == "contact":
            c = db.get(Contact, x.record_id)
            if c and c.do_not_contact:
                raise HTTPException(409, f"{c.full_name} is marked do-not-contact; outreach is blocked")


def create_activity(db: Session, data: dict, user_id: int) -> Activity:
    if data["type"] not in ACTIVITY_TYPES:
        raise HTTPException(422, f"type must be one of {ACTIVITY_TYPES}")
    if data.get("priority", "normal") not in PRIORITIES:
        raise HTTPException(422, f"priority must be one of {PRIORITIES}")
    if data.get("outcome") and data["outcome"] not in OUTCOMES:
        raise HTTPException(422, f"outcome must be one of {OUTCOMES}")
    status = data.get("status", "planned")
    if status not in ("planned", "completed"):
        raise HTTPException(422, "status must be planned or completed")
    links = data.pop("associations", None) or []
    if not links:
        raise HTTPException(422, "At least one associated record is required")
    for l in links:
        check_record(db, l["record_type"], l["record_id"])
    if data.get("recurrence_days") is not None and data["recurrence_days"] < 1:
        raise HTTPException(422, "recurrence_days must be at least 1")
    if status == "planned" and not data.get("due_at"):
        raise HTTPException(422, "A planned task needs a due date")
    a = Activity(**{k: v for k, v in data.items() if k != "status"}, status=status, created_by_user_id=user_id)
    a.assignee_user_id = a.assignee_user_id or user_id
    seen = set()
    for l in links:
        k = (l["record_type"], l["record_id"])
        if k not in seen:
            seen.add(k)
            a.associations.append(ActivityAssociation(record_type=k[0], record_id=k[1]))
    _assert_not_dnc(db, a)
    if status == "completed":
        a.completed_at = data.get("completed_at") or utcnow()
    db.add(a)
    db.flush()
    if a.status == "completed":
        apply_last_contact(db, a)
    return a


def apply_last_contact(db: Session, a: Activity):
    """Last-contact fields are derived from completed activities (ADR 0011)."""
    if a.type == "call" and a.outcome not in TOUCH_OUTCOMES:
        return
    when = a.completed_at or utcnow()
    for x in a.associations:
        o = db.get(RECORD_MODELS[x.record_type], x.record_id)
        if o is not None and hasattr(o, "last_contact_at") and (o.last_contact_at is None or o.last_contact_at < when):
            o.last_contact_at = when
            if hasattr(o, "last_contact_user_id"):
                o.last_contact_user_id = a.assignee_user_id


def complete_activity(db: Session, a: Activity, data: dict, user_id: int) -> Activity:
    if a.status == "completed":
        raise HTTPException(409, "Already completed")
    if a.status == "cancelled":
        raise HTTPException(409, "Cancelled tasks cannot be completed")
    if data.get("outcome"):
        if data["outcome"] not in OUTCOMES:
            raise HTTPException(422, f"outcome must be one of {OUTCOMES}")
        a.outcome = data["outcome"]
    if data.get("body"):
        a.body = (a.body + "\n" if a.body else "") + data["body"]
    _assert_not_dnc(db, a)
    a.status, a.completed_at = "completed", data.get("completed_at") or utcnow()
    db.flush()
    apply_last_contact(db, a)
    if a.recurrence_days:  # next instance is created on completion
        nxt = Activity(type=a.type, subject=a.subject, body=None, status="planned", due_at=(a.due_at or a.completed_at) + timedelta(days=a.recurrence_days),
                       assignee_user_id=a.assignee_user_id, created_by_user_id=a.created_by_user_id, priority=a.priority, recurrence_days=a.recurrence_days,
                       recurrence_parent_id=a.recurrence_parent_id or a.id, cadence_id=a.cadence_id)
        for x in a.associations:
            nxt.associations.append(ActivityAssociation(record_type=x.record_type, record_id=x.record_id))
        db.add(nxt)
        db.flush()
    return a


def activity_out(db: Session, a: Activity, names: dict) -> dict:
    now = utcnow()
    return {"id": a.id, "type": a.type, "subject": a.subject, "body": a.body, "status": a.status, "due_at": a.due_at, "completed_at": a.completed_at,
            "assignee_user_id": a.assignee_user_id, "assignee": names.get(a.assignee_user_id), "created_by": names.get(a.created_by_user_id), "priority": a.priority, "outcome": a.outcome,
            "recurrence_days": a.recurrence_days, "reminder_at": a.reminder_at, "cadence_id": a.cadence_id, "source_key": a.source_key,
            "overdue": a.status == "planned" and a.due_at is not None and a.due_at < now,
            "associations": [{"record_type": x.record_type, "record_id": x.record_id, "label": record_label(db, x.record_type, x.record_id)} for x in a.associations],
            "created_at": a.created_at}


# ---------------- cadences ----------------
def apply_cadence(db: Session, t: CadenceTemplate, rtype: str, rid: int, start: date | None, assignee: int | None, user_id: int) -> list[Activity]:
    check_record(db, rtype, rid)
    if rtype != t.record_type and t.record_type != "any":
        raise HTTPException(422, f"This cadence applies to {t.record_type} records")
    start = start or date.today()
    out = []
    for i, st in enumerate(t.steps):
        key = f"cadence:{t.id}:{rtype}:{rid}:{start.isoformat()}:{i}"
        if db.scalar(select(Activity).where(Activity.source_key == key)):
            continue  # idempotent
        due = datetime.combine(start + timedelta(days=int(st.get("day_offset", 0))), datetime.min.time()) + timedelta(hours=9)
        a = Activity(type=st.get("type", "call"), subject=st["subject"], status="planned", due_at=due, assignee_user_id=assignee or user_id, created_by_user_id=user_id,
                     priority=st.get("priority", "normal"), cadence_id=t.id, source_key=key)
        a.associations.append(ActivityAssociation(record_type=rtype, record_id=rid))
        db.add(a)
        out.append(a)
    db.flush()
    return out


# ---------------- deal key dates -> tasks ----------------
KEY_DATES = [("listing_expiration_date", "Listing expires: renewal conversation", 30, "high"), ("dd_expiry_date", "Due diligence expires", 3, "high"),
             ("loan_contingency_date", "Loan contingency deadline", 5, "high"), ("expected_close_date", "Closing", 7, "normal")]


def sync_key_date_tasks(db: Session, deal: Deal):
    for field, label, lead_days, prio in KEY_DATES:
        key = f"deal:{deal.id}:{field}"
        d = getattr(deal, field)
        existing = db.scalar(select(Activity).where(Activity.source_key == key))
        active = d is not None and deal.status == "open"
        if not active:
            if existing and existing.status == "planned":
                existing.status = "cancelled"
            continue
        due = datetime.combine(d - timedelta(days=lead_days), datetime.min.time()) + timedelta(hours=9)
        if due.date() < date.today() - timedelta(days=1) and not existing:
            due = datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=9)
        subject = f"{label}: {deal.name}"
        if existing:
            if existing.status == "planned":
                existing.due_at, existing.subject = due, subject
            continue
        a = Activity(type="other", subject=subject, status="planned", due_at=due, assignee_user_id=deal.owner_user_id, priority=prio, source_key=key,
                     body=f"Key date {d.isoformat()}")
        a.associations.append(ActivityAssociation(record_type="deal", record_id=deal.id))
        if deal.property_id:
            a.associations.append(ActivityAssociation(record_type="property", record_id=deal.property_id))
        db.add(a)
    db.flush()


def _install_key_date_hook():
    from . import deals as deals_svc
    if sync_key_date_tasks not in deals_svc.KEY_DATE_HOOKS:
        deals_svc.KEY_DATE_HOOKS.append(sync_key_date_tasks)


_install_key_date_hook()


# ---------------- notes ----------------
TAG_RE = re.compile(r"<[^>]*>")
MENTION_RE = re.compile(r"@\[([^\]]+)\]")


def sanitize(body: str) -> str:
    return TAG_RE.sub("", body).strip()


def notify_mentions(db: Session, note: Note, author: User):
    names = {u.name.lower(): u for u in db.scalars(select(User).where(User.active.is_(True)))}
    for m in set(MENTION_RE.findall(note.body)):
        u = names.get(m.lower())
        if not u or u.id == author.id:
            continue
        key = f"mention:{note.id}:{note.version}:{u.id}"
        if db.scalar(select(Notification).where(Notification.key == key)):
            continue
        first = note.associations[0] if note.associations else None
        db.add(Notification(user_id=u.id, kind="mention", message=f"{author.name} mentioned you: {note.body[:120]}", record_type=first.record_type if first else None,
                            record_id=first.record_id if first else None, key=key))


def create_note(db: Session, data: dict, user: User) -> Note:
    body = sanitize(data["body"])
    if not body:
        raise HTTPException(422, "Note body is required")
    links = data.get("associations") or []
    if not links:
        raise HTTPException(422, "At least one associated record is required")
    if data.get("visibility", "team") not in ("team", "private"):
        raise HTTPException(422, "visibility must be team or private")
    for l in links:
        check_record(db, l["record_type"], l["record_id"])
    n = Note(body=body, author_user_id=user.id, pinned=data.get("pinned", False), visibility=data.get("visibility", "team"))
    for k in {(l["record_type"], l["record_id"]) for l in links}:
        n.associations.append(NoteAssociation(record_type=k[0], record_id=k[1]))
    n.versions.append(NoteVersion(version=1, body=body, edited_by_user_id=user.id, edited_at=utcnow()))
    db.add(n)
    db.flush()
    notify_mentions(db, n, user)
    # a note that is about a person also counts as relationship memory but not as a touch
    return n


def edit_note(db: Session, n: Note, data: dict, user: User) -> Note:
    if n.author_user_id != user.id and user.role not in ("admin", "manager"):
        raise HTTPException(403, "Only the author or a manager can edit a note")
    if "body" in data and data["body"] is not None:
        body = sanitize(data["body"])
        if not body:
            raise HTTPException(422, "Note body is required")
        if body != n.body:
            n.version += 1
            n.body = body
            n.versions.append(NoteVersion(version=n.version, body=body, edited_by_user_id=user.id, edited_at=utcnow()))
            db.flush()
            notify_mentions(db, n, user)
    if data.get("pinned") is not None:
        n.pinned = data["pinned"]
    if data.get("visibility"):
        if data["visibility"] not in ("team", "private"):
            raise HTTPException(422, "visibility must be team or private")
        if n.author_user_id != user.id:
            raise HTTPException(403, "Only the author can change visibility")
        n.visibility = data["visibility"]
    db.flush()
    return n


def note_visible(n: Note, user: User) -> bool:
    return n.deleted_at is None and (n.visibility == "team" or n.author_user_id == user.id)


def note_out(db: Session, n: Note, names: dict, with_versions=False) -> dict:
    out = {"id": n.id, "body": n.body, "author_user_id": n.author_user_id, "author": names.get(n.author_user_id), "pinned": n.pinned, "visibility": n.visibility,
           "version": n.version, "created_at": n.created_at, "updated_at": n.updated_at, "edited": n.version > 1,
           "associations": [{"record_type": x.record_type, "record_id": x.record_id, "label": record_label(db, x.record_type, x.record_id)} for x in n.associations]}
    if with_versions:
        out["versions"] = [{"version": v.version, "body": v.body, "edited_at": v.edited_at, "edited_by": names.get(v.edited_by_user_id)} for v in n.versions]
    return out


# ---------------- documents ----------------
ALLOWED_EXT = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "csv": "text/csv", "txt": "text/plain"}
MAX_BYTES = 10 * 1024 * 1024
MAGIC = {"pdf": b"%PDF", "png": b"\x89PNG", "jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff", "docx": b"PK", "xlsx": b"PK", "pptx": b"PK"}


def store_document(db: Session, filename: str, content: bytes, data: dict, user: User) -> Document:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"File type .{ext} is not allowed")
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "File exceeds the 10 MB limit")
    if not content:
        raise HTTPException(422, "Empty file")
    if ext in MAGIC and not content.startswith(MAGIC[ext]):
        raise HTTPException(415, f"File content does not look like a .{ext}")
    if data.get("doc_type", "other") not in DOC_TYPES:
        raise HTTPException(422, f"doc_type must be one of {DOC_TYPES}")
    if data.get("visibility", "team") not in ("team", "confidential"):
        raise HTTPException(422, "visibility must be team or confidential")
    links = data["associations"]
    for l in links:
        check_record(db, l["record_type"], l["record_id"])
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", filename.split("/")[-1].split("\\")[-1])
    digest = hashlib.sha256(content).hexdigest()
    path = config.STORAGE_DIR / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(content)
    first = links[0]
    prev = db.scalars(select(Document).join(DocumentAssociation).where(Document.file_name == safe, Document.deleted_at.is_(None),
                                                                        DocumentAssociation.record_type == first["record_type"], DocumentAssociation.record_id == first["record_id"])
                      .order_by(Document.version.desc())).first()
    doc = Document(file_name=safe, doc_type=data.get("doc_type", "other"), content_type=ALLOWED_EXT[ext], size=len(content), content_hash=digest, storage_path=str(path),
                   uploader_user_id=user.id, visibility=data.get("visibility", "team"), version=(prev.version + 1) if prev else 1, group_id=prev.group_id if prev else None)
    for k in {(l["record_type"], l["record_id"]) for l in links}:
        doc.associations.append(DocumentAssociation(record_type=k[0], record_id=k[1]))
    db.add(doc)
    db.flush()
    if not doc.group_id:
        doc.group_id = doc.id
    return doc


def doc_out(db: Session, d: Document, names: dict) -> dict:
    n_versions = db.scalar(select(func.count()).select_from(Document).where(Document.group_id == d.group_id, Document.deleted_at.is_(None)))
    return {"id": d.id, "file_name": d.file_name, "doc_type": d.doc_type, "content_type": d.content_type, "size": d.size, "visibility": d.visibility, "version": d.version,
            "versions": n_versions, "group_id": d.group_id, "uploader": names.get(d.uploader_user_id), "uploaded_at": d.created_at,
            "associations": [{"record_type": x.record_type, "record_id": x.record_id, "label": record_label(db, x.record_type, x.record_id)} for x in d.associations]}


def can_open_document(d: Document, user: User) -> bool:
    return d.visibility == "team" or user.role in ("admin", "manager", "broker")


def sign_download(doc_id: int, user_id: int, ttl: int = 300) -> str:
    exp = int(time.time()) + ttl
    msg = f"doc:{doc_id}:{user_id}:{exp}"
    return f"{exp}.{user_id}." + hmac.new(config.SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()


def verify_download(doc_id: int, token: str) -> int | None:
    try:
        exp, uid, sig = token.split(".")
        msg = f"doc:{doc_id}:{uid}:{exp}"
        good = hmac.new(config.SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, good) and int(exp) >= time.time():
            return int(uid)
    except Exception:
        return None
    return None


def _search_notes(db, q, ql, toks, want):
    if not want("note"):
        return []
    out = []
    for n in db.scalars(select(Note).where(Note.deleted_at.is_(None), Note.visibility == "team", Note.body.ilike(f"%{q}%")).limit(10)):  # private notes never appear in others' search
        a = n.associations[0] if n.associations else None
        out.append({"type": "note", "id": n.id, "title": n.body[:70], "subtitle": f"Note on {record_label(db, a.record_type, a.record_id)}" if a else "Note",
                    "score": 40, "url": f"/{a.record_type}s/{a.record_id}" if a else "/", "connections": []})
    return out


from .search import SEARCH_PROVIDERS  # noqa: E402
SEARCH_PROVIDERS.append(_search_notes)
