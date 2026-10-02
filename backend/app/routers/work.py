from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..db import get_db, utcnow
from ..models.core_sys import User
from ..models.work import (Activity, ActivityAssociation, CadenceTemplate, Document, DocumentAssociation, Note, NoteAssociation, Notification)
from ..security import current_user, require
from ..services import work as svc
from ..services.common import paginate, user_names

router = APIRouter(prefix="/api", tags=["work"])


class Link(BaseModel):
    record_type: str
    record_id: int


class ActivityIn(BaseModel):
    type: str
    subject: str = Field(min_length=1)
    body: str | None = None
    status: str = "planned"
    due_at: datetime | None = None
    completed_at: datetime | None = None
    reminder_at: datetime | None = None
    assignee_user_id: int | None = None
    priority: str = "normal"
    outcome: str | None = None
    recurrence_days: int | None = None
    associations: list[Link]


class ActivityPatch(BaseModel):
    subject: str | None = None
    body: str | None = None
    due_at: datetime | None = None
    reminder_at: datetime | None = None
    assignee_user_id: int | None = None
    priority: str | None = None
    recurrence_days: int | None = None


class CompleteIn(BaseModel):
    outcome: str | None = None
    body: str | None = None
    completed_at: datetime | None = None


def _act(db, aid) -> Activity:
    a = db.get(Activity, aid)
    if not a:
        raise HTTPException(404, "Activity not found")
    return a


@router.get("/activities")
def list_activities(status: str | None = None, type: str | None = None, assignee_id: int | None = None, record_type: str | None = None, record_id: int | None = None,
                    bucket: str | None = None, q: str | None = None, sort: str = "due", page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
                    db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(Activity)
    if status:
        stmt = stmt.where(Activity.status == status)
    if type:
        stmt = stmt.where(Activity.type == type)
    if assignee_id:
        stmt = stmt.where(Activity.assignee_user_id == assignee_id)
    if record_type and record_id:
        stmt = stmt.where(Activity.id.in_(select(ActivityAssociation.activity_id).where(ActivityAssociation.record_type == record_type, ActivityAssociation.record_id == record_id)))
    if q:
        stmt = stmt.where(Activity.subject.ilike(f"%{q}%"))
    now = utcnow()
    today0 = datetime.combine(date.today(), datetime.min.time())
    if bucket:
        stmt = stmt.where(Activity.status == "planned")
        if bucket == "overdue":
            stmt = stmt.where(Activity.due_at < today0)
        elif bucket == "today":
            stmt = stmt.where(Activity.due_at >= today0, Activity.due_at < today0 + timedelta(days=1))
        elif bucket == "week":
            stmt = stmt.where(Activity.due_at >= today0, Activity.due_at < today0 + timedelta(days=7))
        else:
            raise HTTPException(422, "bucket must be overdue, today or week")
    order = Activity.due_at.asc() if sort == "due" else Activity.completed_at.desc().nulls_last()
    items, total = paginate(db, stmt.order_by(order, Activity.id), page, limit)
    names = user_names(db)
    return {"items": [svc.activity_out(db, a, names) for a in items], "total": total, "page": page, "limit": limit}


@router.get("/agenda")
def agenda(assignee_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    uid = assignee_id or user.id
    today0 = datetime.combine(date.today(), datetime.min.time())
    base = select(Activity).where(Activity.status == "planned", Activity.assignee_user_id == uid)
    names = user_names(db)
    out = lambda rows: [svc.activity_out(db, a, names) for a in rows]  # noqa: E731
    overdue = db.scalars(base.where(Activity.due_at < today0).order_by(Activity.due_at)).all()
    today = db.scalars(base.where(Activity.due_at >= today0, Activity.due_at < today0 + timedelta(days=1)).order_by(Activity.due_at)).all()
    week = db.scalars(base.where(Activity.due_at >= today0 + timedelta(days=1), Activity.due_at < today0 + timedelta(days=7)).order_by(Activity.due_at)).all()
    return {"overdue": out(overdue[:50]), "today": out(today), "this_week": out(week),
            "counts": {"overdue": len(overdue), "today": len(today), "this_week": len(week)}}


@router.post("/activities", status_code=201)
def create_activity(body: ActivityIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    d = body.model_dump()
    d["associations"] = [l for l in d["associations"]]
    a = svc.create_activity(db, d, user.id)
    db.commit()
    return svc.activity_out(db, a, user_names(db))


@router.get("/activities/{aid}")
def get_activity(aid: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return svc.activity_out(db, _act(db, aid), user_names(db))


@router.patch("/activities/{aid}")
def patch_activity(aid: int, body: ActivityPatch, db: Session = Depends(get_db), _: User = Depends(require("edit"))):
    a = _act(db, aid)
    if a.status != "planned":
        raise HTTPException(409, "Only planned tasks can be edited")
    d = body.model_dump(exclude_unset=True)
    if d.get("priority") and d["priority"] not in ("low", "normal", "high"):
        raise HTTPException(422, "Invalid priority")
    for k, v in d.items():
        setattr(a, k, v)
    db.commit()
    return svc.activity_out(db, a, user_names(db))


@router.post("/activities/{aid}/complete")
def complete(aid: int, body: CompleteIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    a = svc.complete_activity(db, _act(db, aid), body.model_dump(exclude_none=True), user.id)
    db.commit()
    return svc.activity_out(db, a, user_names(db))


@router.post("/activities/{aid}/cancel")
def cancel(aid: int, db: Session = Depends(get_db), _: User = Depends(require("edit"))):
    a = _act(db, aid)
    if a.status != "planned":
        raise HTTPException(409, "Only planned tasks can be cancelled")
    a.status = "cancelled"
    db.commit()
    return svc.activity_out(db, a, user_names(db))


# ---------------- cadences ----------------
class StepIn(BaseModel):
    day_offset: int = Field(ge=0)
    type: str = "call"
    subject: str
    priority: str = "normal"


class CadenceIn(BaseModel):
    name: str
    description: str | None = None
    record_type: str = "contact"
    steps: list[StepIn] = Field(min_length=1)


class ApplyIn(BaseModel):
    record_type: str
    record_id: int
    start_date: date | None = None
    assignee_user_id: int | None = None


@router.get("/cadences")
def cadences(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return [{"id": c.id, "name": c.name, "description": c.description, "record_type": c.record_type, "steps": c.steps} for c in db.scalars(select(CadenceTemplate).order_by(CadenceTemplate.name))]


@router.post("/cadences", status_code=201)
def add_cadence(body: CadenceIn, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    if body.record_type not in ("any", *svc.RECORD_TYPES):
        raise HTTPException(422, "Invalid record_type")
    for s in body.steps:
        if s.type not in svc.ACTIVITY_TYPES:
            raise HTTPException(422, "Invalid step type")
    if db.scalar(select(CadenceTemplate).where(CadenceTemplate.name == body.name)):
        raise HTTPException(409, "A cadence with that name exists")
    c = CadenceTemplate(name=body.name, description=body.description, record_type=body.record_type, steps=[s.model_dump() for s in body.steps])
    db.add(c)
    db.commit()
    return {"id": c.id}


@router.post("/cadences/{cid}/apply", status_code=201)
def apply(cid: int, body: ApplyIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    t = db.get(CadenceTemplate, cid)
    if not t:
        raise HTTPException(404, "Cadence not found")
    made = svc.apply_cadence(db, t, body.record_type, body.record_id, body.start_date, body.assignee_user_id, user.id)
    db.commit()
    names = user_names(db)
    return {"created": len(made), "tasks": [svc.activity_out(db, a, names) for a in made]}


# ---------------- notes ----------------
class NoteIn(BaseModel):
    body: str
    associations: list[Link]
    pinned: bool = False
    visibility: str = "team"


class NotePatch(BaseModel):
    body: str | None = None
    pinned: bool | None = None
    visibility: str | None = None


def _note(db, nid, user) -> Note:
    n = db.get(Note, nid)
    if not n or not svc.note_visible(n, user):
        raise HTTPException(404, "Note not found")
    return n


@router.get("/notes")
def list_notes(record_type: str | None = None, record_id: int | None = None, q: str | None = None, page: int = Query(1, ge=1), limit: int = Query(50, le=200),
               db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(Note).where(Note.deleted_at.is_(None), or_(Note.visibility == "team", Note.author_user_id == user.id))
    if record_type and record_id:
        stmt = stmt.where(Note.id.in_(select(NoteAssociation.note_id).where(NoteAssociation.record_type == record_type, NoteAssociation.record_id == record_id)))
    if q:
        stmt = stmt.where(Note.body.ilike(f"%{q}%"))
    items, total = paginate(db, stmt.order_by(Note.pinned.desc(), Note.created_at.desc()), page, limit)
    names = user_names(db)
    return {"items": [svc.note_out(db, n, names) for n in items], "total": total}


@router.post("/notes", status_code=201)
def add_note(body: NoteIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    n = svc.create_note(db, body.model_dump(), user)
    db.commit()
    return svc.note_out(db, n, user_names(db))


@router.get("/notes/{nid}")
def get_note(nid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return svc.note_out(db, _note(db, nid, user), user_names(db), with_versions=True)


@router.patch("/notes/{nid}")
def patch_note(nid: int, body: NotePatch, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    n = svc.edit_note(db, _note(db, nid, user), body.model_dump(exclude_unset=True), user)
    db.commit()
    return svc.note_out(db, n, user_names(db), with_versions=True)


@router.delete("/notes/{nid}", status_code=204)
def delete_note(nid: int, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    n = _note(db, nid, user)
    if n.author_user_id != user.id and user.role not in ("admin", "manager"):
        raise HTTPException(403, "Only the author or a manager can delete a note")
    n.deleted_at = utcnow()
    db.commit()


# ---------------- documents ----------------
@router.get("/documents")
def list_documents(record_type: str | None = None, record_id: int | None = None, doc_type: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(Document).where(Document.deleted_at.is_(None))
    if record_type and record_id:
        stmt = stmt.where(Document.id.in_(select(DocumentAssociation.document_id).where(DocumentAssociation.record_type == record_type, DocumentAssociation.record_id == record_id)))
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    rows = db.scalars(stmt.order_by(Document.created_at.desc())).all()
    latest = {}
    for d in rows:  # latest version per group
        if d.group_id not in latest or d.version > latest[d.group_id].version:
            latest[d.group_id] = d
    names = user_names(db)
    return {"items": [svc.doc_out(db, d, names) for d in sorted(latest.values(), key=lambda x: x.created_at, reverse=True)]}


@router.post("/documents", status_code=201)
async def upload(file: UploadFile = File(...), record_type: str = Form(...), record_id: int = Form(...), doc_type: str = Form("other"), visibility: str = Form("team"),
                 db: Session = Depends(get_db), user: User = Depends(require("create"))):
    content = await file.read(svc.MAX_BYTES + 1)
    d = svc.store_document(db, file.filename or "upload", content, {"doc_type": doc_type, "visibility": visibility, "associations": [{"record_type": record_type, "record_id": record_id}]}, user)
    db.commit()
    return svc.doc_out(db, d, user_names(db))


@router.get("/documents/{did}/versions")
def versions(did: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    d = db.get(Document, did)
    if not d or d.deleted_at:
        raise HTTPException(404, "Document not found")
    names = user_names(db)
    rows = db.scalars(select(Document).where(Document.group_id == d.group_id, Document.deleted_at.is_(None)).order_by(Document.version.desc())).all()
    return {"items": [svc.doc_out(db, x, names) for x in rows]}


@router.post("/documents/{did}/url")
def signed_url(did: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    d = db.get(Document, did)
    if not d or d.deleted_at:
        raise HTTPException(404, "Document not found")
    if not svc.can_open_document(d, user):
        raise HTTPException(403, "This document is confidential")
    return {"url": f"/api/documents/{d.id}/download?token={svc.sign_download(d.id, user.id)}", "expires_in": 300}


@router.get("/documents/{did}/download")
def download(did: int, token: str, db: Session = Depends(get_db)):
    uid = svc.verify_download(did, token)
    d = db.get(Document, did)
    user = db.get(User, uid) if uid else None
    if not uid or not d or d.deleted_at or not user or not user.active or not svc.can_open_document(d, user):
        raise HTTPException(403, "Invalid or expired link")
    if d.visibility == "confidential":
        db.info["actor"], db.info["actor_id"] = user.name, user.id
        log_event(db, "document_download", "documents", d.id, {"file": d.file_name, "version": d.version})
        db.commit()
    from pathlib import Path
    data = Path(d.storage_path).read_bytes()
    return Response(data, media_type=d.content_type or "application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{d.file_name}"'})


@router.delete("/documents/{did}", status_code=204)
def delete_document(did: int, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    d = db.get(Document, did)
    if not d:
        raise HTTPException(404, "Document not found")
    d.deleted_at = utcnow()
    db.commit()


# ---------------- timeline and notifications ----------------
@router.get("/timeline")
def timeline(record_type: str, record_id: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    svc.check_record(db, record_type, record_id)
    names = user_names(db)
    items = []
    for a in db.scalars(select(Activity).where(Activity.id.in_(select(ActivityAssociation.activity_id).where(ActivityAssociation.record_type == record_type, ActivityAssociation.record_id == record_id)), Activity.status != "cancelled")):
        o = svc.activity_out(db, a, names)
        items.append({"kind": "activity", "at": a.completed_at or a.due_at or a.created_at, "data": o})
    for n in db.scalars(select(Note).where(Note.deleted_at.is_(None), or_(Note.visibility == "team", Note.author_user_id == user.id),
                                           Note.id.in_(select(NoteAssociation.note_id).where(NoteAssociation.record_type == record_type, NoteAssociation.record_id == record_id)))):
        items.append({"kind": "note", "at": n.created_at, "data": svc.note_out(db, n, names)})
    latest: dict = {}
    for d in db.scalars(select(Document).where(Document.deleted_at.is_(None), Document.id.in_(select(DocumentAssociation.document_id).where(DocumentAssociation.record_type == record_type, DocumentAssociation.record_id == record_id)))):
        if d.group_id not in latest or d.version > latest[d.group_id].version:
            latest[d.group_id] = d  # the timeline shows the current version; older versions via /documents/{id}/versions
    for d in latest.values():
        items.append({"kind": "document", "at": d.created_at, "data": svc.doc_out(db, d, names)})
    for ext in TIMELINE_PROVIDERS:
        items += ext(db, record_type, record_id, user, names)
    planned = sorted([i for i in items if i["kind"] == "activity" and i["data"]["status"] == "planned"], key=lambda i: i["at"])
    rest = sorted([i for i in items if not (i["kind"] == "activity" and i["data"]["status"] == "planned")], key=lambda i: i["at"], reverse=True)
    return {"upcoming": planned, "history": rest, "pinned": [i for i in rest if i["kind"] == "note" and i["data"]["pinned"]]}


TIMELINE_PROVIDERS: list = []


@router.get("/notifications")
def notifications(unread: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc()).limit(50)).all()
    unread_n = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)))
    return {"unread": unread_n, "items": [{"id": n.id, "kind": n.kind, "message": n.message, "record_type": n.record_type, "record_id": n.record_id, "read": n.read_at is not None, "created_at": n.created_at} for n in rows]}


@router.post("/notifications/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(current_user)):
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))):
        n.read_at = utcnow()
    db.commit()
    return {"ok": True}


@router.post("/notifications/{nid}/read")
def read_one(nid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Not found")
    n.read_at = utcnow()
    db.commit()
    return {"ok": True}
