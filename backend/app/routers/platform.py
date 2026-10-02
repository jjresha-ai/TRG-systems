import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models.core_sys import User
from ..models.platform import FIELD_TYPES, FILTER_ENTITIES, FieldDefinition, ListDef, SavedView
from ..security import can_see_commission, require
from ..services import custom_fields as cf
from ..services import filters as flt
from ..services.visibility import Visibility

router = APIRouter(prefix="/api", tags=["lists-views-fields"])


class QueryIn(BaseModel):
    entity: str
    filter: dict | None = None
    columns: list[str] | None = None
    sort_field: str | None = None
    sort_dir: str = "asc"
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=200)


def _entity(e: str) -> str:
    if e not in FILTER_ENTITIES:
        raise HTTPException(422, f"entity must be one of {FILTER_ENTITIES}")
    return e


@router.get("/filter-fields")
def filter_fields(entity: str, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return {"entity": _entity(entity), "fields": flt.field_meta(db, entity, user)}


@router.post("/query")
def query(body: QueryIn, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    r = flt.run(db, _entity(body.entity), body.filter, user, body.columns, body.sort_field, body.sort_dir, body.page, body.limit)
    r.pop("ids", None)
    return r


# ---------------- saved views ----------------
class ViewIn(BaseModel):
    name: str = Field(min_length=1)
    entity: str
    filter: dict = {}
    columns: list[str] = []
    sort_field: str | None = None
    sort_dir: str = "asc"
    visibility: str = "private"


def _view_out(v: SavedView, names: dict) -> dict:
    return {"id": v.id, "name": v.name, "entity": v.entity, "filter": v.filter, "columns": v.columns, "sort_field": v.sort_field, "sort_dir": v.sort_dir, "visibility": v.visibility,
            "owner_user_id": v.owner_user_id, "owner": names.get(v.owner_user_id)}


def _names(db):
    return {u.id: u.name for u in db.scalars(select(User))}


def _view(db, vid, user, write=False) -> SavedView:
    v = db.get(SavedView, vid)
    if not v or (v.visibility == "private" and v.owner_user_id != user.id):
        raise HTTPException(404, "View not found")
    if write and v.owner_user_id != user.id and user.role not in ("admin", "manager"):
        raise HTTPException(403, "Only the owner can change this view")
    return v


@router.get("/views")
def views(entity: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(SavedView).where(or_(SavedView.visibility == "shared", SavedView.owner_user_id == user.id))
    if entity:
        stmt = stmt.where(SavedView.entity == entity)
    names = _names(db)
    return {"items": [_view_out(v, names) for v in db.scalars(stmt.order_by(SavedView.name))]}


@router.post("/views", status_code=201)
def add_view(body: ViewIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    _entity(body.entity)
    if body.visibility not in ("private", "shared"):
        raise HTTPException(422, "visibility must be private or shared")
    flt.run(db, body.entity, body.filter, user, body.columns or None, body.sort_field, body.sort_dir, 1, 1)  # validates filter, columns and sort
    v = SavedView(**body.model_dump(), owner_user_id=user.id)
    db.add(v)
    db.commit()
    return _view_out(v, _names(db))


@router.patch("/views/{vid}")
def patch_view(vid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    v = _view(db, vid, user, write=True)
    for k in ("name", "filter", "columns", "sort_field", "sort_dir", "visibility"):
        if k in body:
            setattr(v, k, body[k])
    flt.run(db, v.entity, v.filter, user, v.columns or None, v.sort_field, v.sort_dir, 1, 1)
    db.commit()
    return _view_out(v, _names(db))


@router.delete("/views/{vid}", status_code=204)
def del_view(vid: int, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    db.delete(_view(db, vid, user, write=True))
    db.commit()


@router.get("/views/{vid}/run")
def run_view(vid: int, page: int = Query(1, ge=1), limit: int = Query(50, le=200), db: Session = Depends(get_db), user: User = Depends(require("view"))):
    v = _view(db, vid, user)
    r = flt.run(db, v.entity, v.filter, user, v.columns or None, v.sort_field, v.sort_dir, page, limit)
    r.pop("ids", None)
    return r


# ---------------- lists ----------------
class ListIn(BaseModel):
    name: str = Field(min_length=1)
    entity: str
    kind: str
    filter: dict | None = None
    member_ids: list[int] | None = None
    description: str | None = None
    visibility: str = "shared"


def _list_out(db, l: ListDef, user: User, names: dict) -> dict:
    count = len(l.members or []) if l.kind == "static" else flt.run(db, l.entity, l.filter, user, limit=1)["total"]
    return {"id": l.id, "name": l.name, "entity": l.entity, "kind": l.kind, "filter": l.filter, "description": l.description, "visibility": l.visibility, "owner": names.get(l.owner_user_id),
            "owner_user_id": l.owner_user_id, "member_count": count, "snapshot_at": l.snapshot_at}


def _list(db, lid, user, write=False) -> ListDef:
    l = db.get(ListDef, lid)
    if not l or (l.visibility == "private" and l.owner_user_id != user.id):
        raise HTTPException(404, "List not found")
    if write and l.owner_user_id != user.id and user.role not in ("admin", "manager"):
        raise HTTPException(403, "Only the owner can change this list")
    return l


@router.get("/lists")
def lists(entity: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(ListDef).where(or_(ListDef.visibility == "shared", ListDef.owner_user_id == user.id))
    if entity:
        stmt = stmt.where(ListDef.entity == entity)
    names = _names(db)
    return {"items": [_list_out(db, l, user, names) for l in db.scalars(stmt.order_by(ListDef.name))]}


@router.post("/lists", status_code=201)
def add_list(body: ListIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    _entity(body.entity)
    if body.kind not in ("dynamic", "static"):
        raise HTTPException(422, "kind must be dynamic or static")
    if body.visibility not in ("private", "shared"):
        raise HTTPException(422, "visibility must be private or shared")
    l = ListDef(name=body.name, entity=body.entity, kind=body.kind, description=body.description, visibility=body.visibility, owner_user_id=user.id)
    if body.kind == "dynamic":
        if body.filter is None:
            raise HTTPException(422, "A dynamic list needs a filter")
        flt.run(db, body.entity, body.filter, user, limit=1)
        l.filter = body.filter
    else:
        ids = body.member_ids if body.member_ids is not None else (flt.matching_ids(db, body.entity, body.filter, user) if body.filter is not None else None)
        if ids is None:
            raise HTTPException(422, "A static list needs member_ids or a filter to snapshot")
        l.members, l.snapshot_at = sorted(set(ids)), utcnow()
    db.add(l)
    db.commit()
    return _list_out(db, l, user, _names(db))


@router.get("/lists/{lid}")
def get_list(lid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return _list_out(db, _list(db, lid, user), user, _names(db))


@router.get("/lists/{lid}/members")
def list_members(lid: int, page: int = Query(1, ge=1), limit: int = Query(50, le=200), db: Session = Depends(get_db), user: User = Depends(require("view"))):
    l = _list(db, lid, user)
    r = flt.run(db, l.entity, l.filter if l.kind == "dynamic" else None, user, page=page, limit=limit, restrict_ids=l.members if l.kind == "static" else None)  # dynamic lists are recomputed on every read
    r.pop("ids", None)
    return r


@router.post("/lists/{lid}/snapshot", status_code=201)
def snapshot(lid: int, name: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    l = _list(db, lid, user)
    if l.kind != "dynamic":
        raise HTTPException(409, "Only dynamic lists can be snapshotted")
    s = ListDef(name=name or f"{l.name} (snapshot {utcnow():%Y-%m-%d})", entity=l.entity, kind="static", members=sorted(flt.matching_ids(db, l.entity, l.filter, user)), snapshot_at=utcnow(),
                visibility=l.visibility, owner_user_id=user.id, description=f"Snapshot of {l.name}")
    db.add(s)
    db.commit()
    return _list_out(db, s, user, _names(db))


@router.patch("/lists/{lid}/members")
def edit_members(lid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    l = _list(db, lid, user, write=True)
    if l.kind != "static":
        raise HTTPException(409, "Dynamic lists are defined by their filter")
    cur = set(l.members or [])
    add, rem = body.get("add", []), body.get("remove", [])
    M = flt.ENTITY_MODELS[l.entity]
    vis = Visibility(db, user)
    for i in add:
        o = db.get(M, i)
        if not o or not vis.can_see(o):
            raise HTTPException(422, f"Unknown {l.entity} #{i}")
    l.members = sorted((cur | set(add)) - set(rem))
    db.commit()
    return _list_out(db, l, user, _names(db))


@router.delete("/lists/{lid}", status_code=204)
def del_list(lid: int, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    db.delete(_list(db, lid, user, write=True))
    db.commit()


# ---------------- tags ----------------
TAG_MODELS = {"contact", "company", "property", "listing", "deal"}


def norm_tag(t: str) -> str:
    t = re.sub(r"\s+", " ", t.strip().lower())
    if not t or len(t) > 40:
        raise HTTPException(422, "Tags must be 1-40 characters")
    return t


@router.get("/tags")
def tags(entity: str, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    if entity not in TAG_MODELS:
        raise HTTPException(422, f"entity must be one of {sorted(TAG_MODELS)}")
    M = flt.ENTITY_MODELS[entity]
    counts: dict = {}
    vis = Visibility(db, user)
    for o in db.scalars(select(M)):
        if vis.can_see(o):
            for t in o.tags or []:
                counts[t] = counts.get(t, 0) + 1
    return {"items": [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]}


class BulkTagIn(BaseModel):
    entity: str
    ids: list[int] = Field(min_length=1)
    add: list[str] = []
    remove: list[str] = []


@router.post("/tags/bulk")
def bulk_tags(body: BulkTagIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    if body.entity not in TAG_MODELS:
        raise HTTPException(422, f"entity must be one of {sorted(TAG_MODELS)}")
    add, rem = [norm_tag(t) for t in body.add], {norm_tag(t) for t in body.remove}
    M = flt.ENTITY_MODELS[body.entity]
    vis = Visibility(db, user)
    n = 0
    for i in body.ids:
        o = db.get(M, i)
        if not o or not vis.can_see(o):
            raise HTTPException(422, f"Unknown {body.entity} #{i}")
        new = sorted((set(o.tags or []) | set(add)) - rem)
        if new != sorted(o.tags or []):
            o.tags = new
            n += 1
    db.commit()
    return {"updated": n}


# ---------------- custom field definitions ----------------
class FieldIn(BaseModel):
    entity: str
    key: str
    label: str = Field(min_length=1)
    type: str
    options: list = []
    required: bool = False
    required_when: dict | None = None
    show_when: dict | None = None
    restricted: bool = False


def _def_out(d: FieldDefinition) -> dict:
    return {"id": d.id, "entity": d.entity, "key": d.key, "label": d.label, "type": d.type, "options": d.options, "required": d.required, "required_when": d.required_when,
            "show_when": d.show_when, "restricted": d.restricted, "active": d.active, "position": d.position}


@router.get("/custom-fields")
def custom_fields(entity: str | None = None, include_retired: bool = False, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(FieldDefinition)
    if entity:
        stmt = stmt.where(FieldDefinition.entity == entity)
    if not (include_retired and user.role == "admin"):
        stmt = stmt.where(FieldDefinition.active.is_(True))
    out = [d for d in db.scalars(stmt.order_by(FieldDefinition.entity, FieldDefinition.position)) if not (d.restricted and not can_see_commission(user))]
    return {"items": [_def_out(d) for d in out], "types": FIELD_TYPES}


@router.post("/custom-fields", status_code=201)
def add_field(body: FieldIn, db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    d = cf.create_definition(db, body.model_dump())
    db.commit()
    return _def_out(d)


@router.patch("/custom-fields/{fid}")
def patch_field(fid: int, body: dict, db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    d = db.get(FieldDefinition, fid)
    if not d:
        raise HTTPException(404, "Field not found")
    if "type" in body and body["type"] != d.type:
        raise HTTPException(409, "A field's type cannot change; retire it and add a new one")
    if "options" in body and d.type in ("single_select", "multi_select"):
        removed = set(d.options) - set(body["options"])
        if removed:
            raise HTTPException(409, f"Options cannot be removed while data may use them: {sorted(removed)}")
    for k in ("label", "options", "required", "required_when", "show_when", "restricted", "active", "position"):
        if k in body:
            setattr(d, k, body[k])
    db.commit()
    return _def_out(d)
