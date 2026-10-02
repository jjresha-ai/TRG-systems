from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.core_sys import User
from ..models.pipeline import INTEREST_STAGES, LISTING_STATUSES, BuyerInterest, Listing
from ..security import current_user, require
from ..services import listings as svc
from ..services import custom_fields as cfs
from ..services.common import paginate, user_names
from ..services.visibility import Visibility, sql_clause

router = APIRouter(prefix="/api", tags=["listings"])


class BrokerIn(BaseModel):
    user_id: int
    role: str = "lead"
    split_pct: float = Field(default=100.0, gt=0, le=100)


class ListingIn(BaseModel):
    property_id: int
    seller_contact_id: int | None = None
    seller_company_id: int | None = None
    listing_type: str = "sale"
    status: str = "prospect"
    list_price: int | None = Field(default=None, gt=0)
    commission_rate_bps: int | None = Field(default=None, ge=0, le=2000)
    commission_terms: str | None = None
    agreement_date: date | None = None
    expiration_date: date | None = None
    confidential: bool = False
    owner_user_id: int | None = None
    brokers: list[BrokerIn] | None = None
    source: str | None = "manual"
    custom: dict | None = None


class ListingPatch(BaseModel):
    seller_contact_id: int | None = None
    seller_company_id: int | None = None
    list_price: int | None = Field(default=None, gt=0)
    commission_rate_bps: int | None = Field(default=None, ge=0, le=2000)
    commission_terms: str | None = None
    agreement_date: date | None = None
    expiration_date: date | None = None
    confidential: bool | None = None
    brokers: list[BrokerIn] | None = None
    custom: dict | None = None


class StatusIn(BaseModel):
    status: str
    sold_price: int | None = None
    closed_date: date | None = None
    list_price: int | None = None
    agreement_date: date | None = None
    expiration_date: date | None = None


def _get(db, lid, user=None) -> Listing:
    l = db.get(Listing, lid)
    if not l or l.deleted_at or (user is not None and not Visibility(db, user).can_see(l)):
        raise HTTPException(404, "Listing not found")
    return l


@router.get("/listings")
def list_listings(property_id: int | None = None, status: str | None = None, type: str | None = None, owner_id: int | None = None, expiring_within_days: int | None = None, q: str | None = None,
                  sort: str = "recent", page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
                  db: Session = Depends(get_db), user: User = Depends(require("view"))):
    from ..models.core import Property
    stmt = select(Listing).where(Listing.deleted_at.is_(None))
    clause = sql_clause(db, user, Listing)
    if clause is not None:
        stmt = stmt.where(clause)
    if property_id:
        stmt = stmt.where(Listing.property_id == property_id)
    if status:
        stmt = stmt.where(Listing.status == status)
    if owner_id:
        stmt = stmt.where(Listing.owner_user_id == owner_id)
    if type:
        stmt = stmt.where(Listing.property_id.in_(select(Property.id).where(Property.property_type == type)))
    if q:
        stmt = stmt.where(Listing.property_id.in_(select(Property.id).where(Property.address.ilike(f"%{q}%") | Property.city.ilike(f"%{q}%") | Property.name.ilike(f"%{q}%"))))
    if expiring_within_days is not None:
        today = date.today()
        stmt = stmt.where(Listing.status == "active", Listing.expiration_date <= today + timedelta(days=expiring_within_days), Listing.expiration_date >= today)
    order = {"recent": Listing.created_at.desc(), "expiration": Listing.expiration_date.asc(), "price": Listing.list_price.desc()}.get(sort, Listing.created_at.desc())
    items, total = paginate(db, stmt.order_by(order, Listing.id), page, limit)
    names = user_names(db)
    return {"items": [svc.listing_out(db, l, user, names) for l in items], "total": total, "page": page, "limit": limit}


@router.get("/listings/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require("view"))):
    by = {s: {"count": 0, "value": 0} for s in LISTING_STATUSES}
    for s, n, v in db.execute(select(Listing.status, func.count(), func.coalesce(func.sum(Listing.list_price), 0)).where(Listing.deleted_at.is_(None)).group_by(Listing.status)):
        by[s] = {"count": n, "value": int(v)}
    today = date.today()
    exp = db.scalar(select(func.count()).select_from(Listing).where(Listing.status == "active", Listing.expiration_date <= today + timedelta(days=60), Listing.expiration_date >= today))
    return {"by_status": by, "expiring_60_days": exp}


@router.post("/listings", status_code=201)
def create_listing(body: ListingIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    if body.listing_type not in ("sale", "lease"):
        raise HTTPException(422, "listing_type must be sale or lease")
    if body.status not in LISTING_STATUSES:
        raise HTTPException(422, f"status must be one of {LISTING_STATUSES}")
    data = body.model_dump()
    data["brokers"] = [b for b in data["brokers"]] if data.get("brokers") else None
    custom = data.pop("custom", None) or {}
    l = svc.create_listing(db, data, user.id)
    l.custom = cfs.validate_custom(db, "listing", {}, custom, l, user, creating=True)
    db.commit()
    return svc.listing_out(db, l, user, user_names(db))


@router.get("/listings/{lid}")
def get_listing(lid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return svc.listing_out(db, _get(db, lid, user), user, user_names(db))


@router.patch("/listings/{lid}")
def patch_listing(lid: int, body: ListingPatch, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    l = _get(db, lid, user)
    if l.status == "closed":
        raise HTTPException(409, "Closed listings cannot be edited")
    d = body.model_dump(exclude_unset=True)
    brokers = d.pop("brokers", None)
    if "custom" in d:
        l.custom = cfs.validate_custom(db, "listing", l.custom, d.pop("custom"), l, user)
    if ("commission_rate_bps" in d or "commission_terms" in d or brokers is not None) and user.role not in ("admin", "manager", "broker"):
        raise HTTPException(403, "Your role may not change commission or split fields")
    for k, v in d.items():
        setattr(l, k, v)
    if l.expiration_date and l.agreement_date and l.expiration_date <= l.agreement_date:
        raise HTTPException(422, "Expiration must be after the listing agreement date")
    if brokers is not None:
        svc.set_brokers(db, l, brokers)
    db.commit()
    return svc.listing_out(db, l, user, user_names(db))


@router.post("/listings/{lid}/status")
def set_status(lid: int, body: StatusIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    if body.status not in LISTING_STATUSES:
        raise HTTPException(422, f"status must be one of {LISTING_STATUSES}")
    l = _get(db, lid, user)
    svc.transition(db, l, body.status, body.model_dump(exclude_none=True), user.id)
    db.commit()
    return svc.listing_out(db, l, user, user_names(db))


@router.delete("/listings/{lid}", status_code=204)
def delete_listing(lid: int, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    from ..db import utcnow
    _get(db, lid, user).deleted_at = utcnow()
    db.commit()


# ---------------- buyer interest ----------------
class ContactMini(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None


class InterestIn(BaseModel):
    contact_id: int | None = None
    contact: ContactMini | None = None
    company_id: int | None = None
    stage: str = "inquiry"
    channel: str = "manual"  # manual | email | form
    amount: int | None = Field(default=None, gt=0)
    terms: str | None = None
    note: str | None = None
    reason: str | None = None


@router.get("/listings/{lid}/interest")
def interest(lid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    l = _get(db, lid, user)
    names = user_names(db)
    items = db.scalars(select(BuyerInterest).where(BuyerInterest.listing_id == lid)).all()
    funnel = {s: 0 for s in INTEREST_STAGES}
    for i in items:
        funnel[i.stage] += 1
    return {"items": [svc.interest_out(db, i, l, user, names) for i in items], "funnel": funnel, "total": len(items)}


@router.post("/listings/{lid}/interest", status_code=201)
def add_interest(lid: int, body: InterestIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    l = _get(db, lid, user)
    data = body.model_dump()
    data["contact"] = body.contact.model_dump() if body.contact else None
    i = svc.record_interest(db, l, data, user.id)
    db.commit()
    return svc.interest_out(db, i, l, user, user_names(db))


@router.post("/interest/{iid}/events")
def interest_event(iid: int, body: InterestIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    i = db.get(BuyerInterest, iid)
    if not i:
        raise HTTPException(404, "Not found")
    l = _get(db, i.listing_id, user)
    from ..models.core import Contact
    if body.stage in svc.OUTREACH_STAGES and db.get(Contact, i.contact_id).do_not_contact:
        raise HTTPException(409, "Contact is marked do-not-contact; outreach is blocked")
    if body.stage not in INTEREST_STAGES:
        raise HTTPException(422, f"stage must be one of {INTEREST_STAGES}")
    svc.apply_stage(db, i, body.stage, body.model_dump(), user.id)
    db.commit()
    return svc.interest_out(db, i, l, user, user_names(db))
