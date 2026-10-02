from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.core import Contact, DuplicateCandidate, MergeLog
from ..models.core_sys import User
from ..security import require
from ..services import dedupe, entities as svc, merge as merge_svc
from ..services.common import user_names
from ..services.search import search

from fastapi import HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def global_search(q: str, types: str | None = None, limit: int = Query(20, le=50), db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return {"query": q, "results": search(db, q, limit, set(types.split(",")) if types else None)}


class MergeIn(BaseModel):
    entity: str
    survivor_id: int
    absorbed_id: int
    choices: dict[str, str] = {}


def _brief(db, entity, id_):
    names = user_names(db)
    M = merge_svc.MODELS[entity]
    o = db.get(M, id_)
    if not o:
        return None
    if entity == "contact":
        return svc.contact_summary(db, o, names, with_holdings=False)
    if entity == "company":
        return svc.company_summary(db, o, names)
    return svc.property_summary(db, o, names)


@router.get("/duplicates")
def duplicates(entity: str | None = None, status: str = "pending", db: Session = Depends(get_db), _: User = Depends(require("view"))):
    stmt = select(DuplicateCandidate).where(DuplicateCandidate.status == status)
    if entity:
        stmt = stmt.where(DuplicateCandidate.entity == entity)
    out = []
    for d in db.scalars(stmt.order_by(DuplicateCandidate.id)):
        a, b = _brief(db, d.entity, d.a_id), _brief(db, d.entity, d.b_id)
        if a and b:
            out.append({"id": d.id, "entity": d.entity, "reason": d.reason, "score": d.score, "a": a, "b": b})
    return {"items": out, "total": len(out)}


@router.post("/duplicates/scan")
def scan(db: Session = Depends(get_db), _: User = Depends(require("edit"))):
    r = dedupe.scan_all(db)
    db.commit()
    return r


@router.post("/duplicates/{did}/dismiss")
def dismiss(did: int, db: Session = Depends(get_db), _: User = Depends(require("edit"))):
    d = db.get(DuplicateCandidate, did)
    if not d:
        raise HTTPException(404, "Not found")
    d.status = "dismissed"
    db.commit()
    return {"status": "dismissed"}


@router.post("/merge")
def do_merge(body: MergeIn, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    if body.entity not in merge_svc.MODELS:
        raise HTTPException(422, "entity must be contact, company or property")
    log = merge_svc.merge(db, body.entity, body.survivor_id, body.absorbed_id, body.choices, user.id)
    db.commit()
    return {"merge_id": log.id, "moved": len(log.moved), "survivor_id": log.survivor_id}


@router.get("/merges")
def merges(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return {"items": [{"id": m.id, "entity": m.entity, "survivor_id": m.survivor_id, "absorbed_id": m.absorbed_id, "created_at": m.created_at,
                       "undone_at": m.undone_at, "moved": len(m.moved)} for m in db.scalars(select(MergeLog).order_by(MergeLog.id.desc()).limit(100))]}


@router.post("/merges/{mid}/undo")
def undo(mid: int, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    merge_svc.undo(db, mid)
    db.commit()
    return {"status": "undone"}
