from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models.core import Company
from ..models.core_sys import User
from ..security import require
from ..services import entities as svc
from ..services.visibility import Visibility, assert_can_set_confidential, sql_clause
from ..services.common import paginate, user_names

router = APIRouter(prefix="/api/companies", tags=["companies"])


class CompanyIn(BaseModel):
    name: str = Field(min_length=1)
    kind: str = "llc"
    website: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    parent_company_id: int | None = None
    owner_user_id: int | None = None
    source: str | None = "manual"
    tags: list[str] = []
    custom: dict | None = None


class CompanyPatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    parent_company_id: int | None = None
    owner_user_id: int | None = None
    tags: list[str] | None = None
    custom: dict | None = None
    confidential: bool | None = None


def _get(db, cid, user=None) -> Company:
    c = db.get(Company, cid)
    if not c or c.deleted_at or (user is not None and not Visibility(db, user).can_see(c)):
        raise HTTPException(404, "Company not found")
    return c


@router.get("")
def list_companies(q: str | None = None, kind: str | None = None, owner_id: int | None = None, tag: str | None = None,
                   sort: str = "name", order: str = "asc", page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
                   db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(Company).where(Company.deleted_at.is_(None))
    clause = sql_clause(db, user, Company)
    if clause is not None:
        stmt = stmt.where(clause)
    if q:
        stmt = stmt.where(or_(Company.name.ilike(f"%{q}%"), Company.normalized_name.ilike(f"%{q.lower()}%")))
    if kind:
        stmt = stmt.where(Company.kind == kind)
    if owner_id:
        stmt = stmt.where(Company.owner_user_id == owner_id)
    if tag:
        stmt = stmt.where(func.json_extract(Company.tags, "$").like(f'%"{tag}"%'))
    col = {"name": Company.name, "created": Company.created_at, "last_contact": Company.last_contact_at}.get(sort, Company.name)
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), Company.id)
    items, total = paginate(db, stmt, page, limit)
    names = user_names(db)
    return {"items": [svc.company_summary(db, c, names) for c in items], "total": total, "page": page, "limit": limit}


@router.post("", status_code=201)
def create_company(body: CompanyIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    d = body.model_dump()
    d["custom"] = d.get("custom") or {}
    co = svc.create_company(db, d, user.id)
    db.commit()
    return svc.company_detail(db, co, user_names(db), user)


@router.get("/{cid}")
def get_company(cid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return svc.company_detail(db, _get(db, cid, user), user_names(db), user)


@router.patch("/{cid}")
def patch_company(cid: int, body: CompanyPatch, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    obj = _get(db, cid, user)
    fields = body.model_dump(exclude_unset=True)
    if "confidential" in fields:
        assert_can_set_confidential(obj, user)
    co = svc.update_company(db, obj, fields, user)
    db.commit()
    return svc.company_detail(db, co, user_names(db), user)


@router.delete("/{cid}", status_code=204)
def delete_company(cid: int, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    _get(db, cid, user).deleted_at = utcnow()
    db.commit()
