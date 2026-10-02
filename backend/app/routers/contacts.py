from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models.core import Contact, ContactCompanyRole, ContactEmail, ContactPhone
from ..models.core_sys import User
from ..security import require
from ..services import entities as svc
from ..services.visibility import Visibility, assert_can_set_confidential, sql_clause
from ..services.common import paginate, user_names

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


class EmailIn(BaseModel):
    email: str
    label: str = "work"
    is_primary: bool | None = None


class PhoneIn(BaseModel):
    phone: str
    label: str = "mobile"
    is_primary: bool | None = None


class CompanyLinkIn(BaseModel):
    company_id: int
    role: str = "principal"
    is_primary: bool = False
    start_date: date | None = None


class ContactIn(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    title: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    contact_types: list[str] = []
    status: str = "active"
    lifecycle_stage: str = "prospect"
    do_not_contact: bool = False
    do_not_contact_reason: str | None = None
    source: str | None = "manual"
    tags: list[str] = []
    owner_user_id: int | None = None
    emails: list[EmailIn] = []
    phones: list[PhoneIn] = []
    company_links: list[CompanyLinkIn] = []
    custom: dict | None = None


class ContactPatch(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    contact_types: list[str] | None = None
    status: str | None = None
    lifecycle_stage: str | None = None
    do_not_contact: bool | None = None
    do_not_contact_reason: str | None = None
    tags: list[str] | None = None
    owner_user_id: int | None = None
    emails: list[EmailIn] | None = None
    phones: list[PhoneIn] | None = None
    custom: dict | None = None
    confidential: bool | None = None


@router.get("")
def list_contacts(q: str | None = None, type: str | None = None, status: str | None = None, lifecycle: str | None = None,
                  owner_id: int | None = None, tag: str | None = None, dnc: bool | None = None, stale_days: int | None = None,
                  sort: str = "name", order: str = "asc", page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
                  db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(Contact).where(Contact.deleted_at.is_(None))
    clause = sql_clause(db, user, Contact)
    if clause is not None:
        stmt = stmt.where(clause)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Contact.full_name.ilike(like), Contact.title.ilike(like),
                              Contact.id.in_(select(ContactEmail.contact_id).where(ContactEmail.normalized.ilike(like))),
                              Contact.id.in_(select(ContactPhone.contact_id).where(ContactPhone.phone.ilike(like)))))
    if type:
        stmt = stmt.where(func.json_extract(Contact.contact_types, "$").like(f'%"{type}"%'))
    if tag:
        stmt = stmt.where(func.json_extract(Contact.tags, "$").like(f'%"{tag}"%'))
    if status:
        stmt = stmt.where(Contact.status == status)
    if lifecycle:
        stmt = stmt.where(Contact.lifecycle_stage == lifecycle)
    if owner_id:
        stmt = stmt.where(Contact.owner_user_id == owner_id)
    if dnc is not None:
        stmt = stmt.where(Contact.do_not_contact == dnc)
    if stale_days:
        cutoff = utcnow() - timedelta(days=stale_days)
        stmt = stmt.where(or_(Contact.last_contact_at.is_(None), Contact.last_contact_at < cutoff))
    col = {"name": Contact.last_name, "last_contact": Contact.last_contact_at, "created": Contact.created_at}.get(sort, Contact.last_name)
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), Contact.id)
    items, total = paginate(db, stmt, page, limit)
    names = user_names(db)
    return {"items": [svc.contact_summary(db, c, names) for c in items], "total": total, "page": page, "limit": limit}


@router.post("", status_code=201)
def create_contact(body: ContactIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    d = body.model_dump()
    d["custom"] = d.get("custom") or {}
    c = svc.create_contact(db, d, user.id)
    db.commit()
    return svc.contact_detail(db, c, user_names(db), user)


def _get(db, cid, user=None) -> Contact:
    c = db.get(Contact, cid)
    if not c or c.deleted_at or (user is not None and not Visibility(db, user).can_see(c)):
        raise HTTPException(404, "Contact not found")
    return c


@router.get("/{cid}")
def get_contact(cid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return svc.contact_detail(db, _get(db, cid, user), user_names(db), user)


@router.patch("/{cid}")
def patch_contact(cid: int, body: ContactPatch, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    obj = _get(db, cid, user)
    fields = body.model_dump(exclude_unset=True)
    if "confidential" in fields:
        assert_can_set_confidential(obj, user)
    c = svc.update_contact(db, obj, fields, user)
    db.commit()
    return svc.contact_detail(db, c, user_names(db), user)


@router.delete("/{cid}", status_code=204)
def delete_contact(cid: int, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    _get(db, cid, user).deleted_at = utcnow()
    db.commit()


@router.post("/{cid}/companies", status_code=201)
def link_company(cid: int, body: CompanyLinkIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    from ..models.core import Company
    _get(db, cid, user)
    if not db.get(Company, body.company_id):
        raise HTTPException(422, "Unknown company")
    r = ContactCompanyRole(contact_id=cid, **body.model_dump())
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.delete("/{cid}/companies/{role_id}", status_code=204)
def unlink_company(cid: int, role_id: int, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    r = db.get(ContactCompanyRole, role_id)
    if not r or r.contact_id != cid:
        raise HTTPException(404, "Link not found")
    db.delete(r)
    db.commit()
