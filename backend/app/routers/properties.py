from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models.core import Property, PropertyOwnership
from ..models.core_sys import User
from ..security import require
from ..services import entities as svc
from ..services.visibility import Visibility, assert_can_set_confidential, sql_clause
from ..services.common import add_months, paginate, user_names
from ..services.normalize import norm_address

router = APIRouter(prefix="/api/properties", tags=["properties"])


class PropertyBase(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    apn: str | None = None
    county: str | None = None
    property_type: str | None = None
    subtype: str | None = None
    market: str | None = None
    submarket: str | None = None
    building_sf: int | None = None
    land_acres: float | None = None
    units: int | None = None
    year_built: int | None = None
    zoning: str | None = None
    noi: int | None = None
    cap_rate_bps: int | None = None
    estimated_value: int | None = None
    lat: float | None = None
    lng: float | None = None
    lender: str | None = None
    loan_original_amount: int | None = None
    loan_rate_type: str | None = None
    loan_maturity_date: date | None = None
    hold_intent: str | None = None
    pricing_expectation: int | None = None
    owner_user_id: int | None = None
    tags: list[str] | None = None
    custom: dict | None = None
    confidential: bool | None = None


class PropertyIn(PropertyBase):
    address: str = Field(min_length=1)
    city: str = Field(min_length=1)
    property_type: str
    state: str = "CA"
    county: str = "Orange"
    hold_intent: str = "unknown"
    source: str | None = "manual"
    tags: list[str] = []


class OwnershipIn(BaseModel):
    company_id: int | None = None
    contact_id: int | None = None
    ownership_pct: float = 100.0
    acquired_date: date | None = None
    acquisition_price: int | None = None
    dispose_current: bool = True


def _get(db, pid, user=None) -> Property:
    p = db.get(Property, pid)
    if not p or p.deleted_at or (user is not None and not Visibility(db, user).can_see(p)):
        raise HTTPException(404, "Property not found")
    return p


@router.get("")
def list_properties(q: str | None = None, type: str | None = None, subtype: str | None = None, market: str | None = None, city: str | None = None,
                    hold_intent: str | None = None, min_sf: int | None = None, max_sf: int | None = None,
                    maturity_within_months: int | None = None, held_at_least_years: float | None = None, owner_id: int | None = None,
                    tag: str | None = None, sort: str = "address", order: str = "asc", page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
                    db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(Property).where(Property.deleted_at.is_(None))
    clause = sql_clause(db, user, Property)
    if clause is not None:
        stmt = stmt.where(clause)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Property.address.ilike(like), Property.name.ilike(like), Property.city.ilike(like), Property.apn.ilike(like),
                              Property.normalized_address.ilike(f"%{norm_address(q)}%")))
    if type:
        stmt = stmt.where(Property.property_type == type)
    if subtype:
        stmt = stmt.where(Property.subtype == subtype)
    if market:
        stmt = stmt.where(Property.market == market)
    if city:
        stmt = stmt.where(Property.city == city)
    if hold_intent:
        stmt = stmt.where(Property.hold_intent == hold_intent)
    if min_sf:
        stmt = stmt.where(Property.building_sf >= min_sf)
    if max_sf:
        stmt = stmt.where(Property.building_sf <= max_sf)
    if owner_id:
        stmt = stmt.where(Property.owner_user_id == owner_id)
    if tag:
        stmt = stmt.where(func.json_extract(Property.tags, "$").like(f'%"{tag}"%'))
    if maturity_within_months:
        stmt = stmt.where(Property.loan_maturity_date.is_not(None), Property.loan_maturity_date <= add_months(date.today(), maturity_within_months),
                          Property.loan_maturity_date >= date.today())
    if held_at_least_years:
        cutoff = date.today().replace(year=date.today().year - int(held_at_least_years))
        stmt = stmt.where(Property.id.in_(select(PropertyOwnership.property_id).where(PropertyOwnership.disposed_date.is_(None), PropertyOwnership.acquired_date <= cutoff)))
    cols = {"address": Property.address, "value": Property.estimated_value, "sf": Property.building_sf, "maturity": Property.loan_maturity_date,
            "last_contact": Property.last_contact_at, "city": Property.city}
    col = cols.get(sort, Property.address)
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), Property.id)
    items, total = paginate(db, stmt, page, limit)
    names = user_names(db)
    return {"items": [svc.property_summary(db, p, names) for p in items], "total": total, "page": page, "limit": limit}


@router.post("", status_code=201)
def create_property(body: PropertyIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    d = body.model_dump(exclude_none=True)
    d.setdefault("custom", {})
    p = svc.create_property(db, d, user.id)
    db.commit()
    return svc.property_detail(db, p, user_names(db), user)


@router.get("/{pid}")
def get_property(pid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return svc.property_detail(db, _get(db, pid, user), user_names(db), user)


@router.patch("/{pid}")
def patch_property(pid: int, body: PropertyBase, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    obj = _get(db, pid, user)
    fields = body.model_dump(exclude_unset=True)
    if "confidential" in fields:
        assert_can_set_confidential(obj, user)
    p = svc.update_property(db, obj, fields, user)
    db.commit()
    return svc.property_detail(db, p, user_names(db), user)


@router.delete("/{pid}", status_code=204)
def delete_property(pid: int, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    _get(db, pid, user).deleted_at = utcnow()
    db.commit()


@router.post("/{pid}/ownerships", status_code=201)
def transfer_ownership(pid: int, body: OwnershipIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    p = _get(db, pid, user)
    svc.transfer_ownership(db, p, body.model_dump())
    db.commit()
    return svc.property_detail(db, p, user_names(db), user)
