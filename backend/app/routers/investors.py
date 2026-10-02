from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..db import get_db, utcnow
from ..models.core import Company, Contact
from ..models.core_sys import User
from ..models.deals import Deal
from ..models.investors import Commitment, Fund, FundDeal, FundProperty, InvestorProfile, FUND_STATUSES
from ..models.core import Property
from ..models.pipeline import Listing
from ..security import require
from ..services import investors as svc
from ..services.common import paginate, user_names

router = APIRouter(prefix="/api", tags=["investors"])


class ProfileBase(BaseModel):
    asset_classes: list[str] | None = None
    markets: list[str] | None = None
    min_check: int | None = Field(default=None, ge=0)
    max_check: int | None = Field(default=None, ge=0)
    min_cap_rate_bps: int | None = Field(default=None, ge=0)
    target_return_notes: str | None = None
    exchange_1031: bool | None = None
    exchange_deadline: date | None = None
    accreditation_status: str | None = None
    accreditation_verified_on: date | None = None
    preferred_channel: str | None = None
    owner_user_id: int | None = None
    notes: str | None = None


class ProfileIn(ProfileBase):
    contact_id: int | None = None
    company_id: int | None = None


def _profile(db, pid) -> InvestorProfile:
    p = db.get(InvestorProfile, pid)
    if not p or p.deleted_at:
        raise HTTPException(404, "Investor profile not found")
    return p


@router.get("/investors")
def list_investors(q: str | None = None, asset_class: str | None = None, market: str | None = None, only_1031: bool | None = None, accreditation: str | None = None,
                   min_check_at_least: int | None = None, page: int = Query(1, ge=1), limit: int = Query(50, le=200), db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(InvestorProfile).where(InvestorProfile.deleted_at.is_(None))
    if q:
        stmt = stmt.where(or_(InvestorProfile.contact_id.in_(select(Contact.id).where(Contact.full_name.ilike(f"%{q}%"))),
                              InvestorProfile.company_id.in_(select(Company.id).where(Company.name.ilike(f"%{q}%")))))
    if asset_class:
        stmt = stmt.where(func.json_extract(InvestorProfile.asset_classes, "$").like(f'%"{asset_class}"%'))
    if market:
        stmt = stmt.where(func.json_extract(InvestorProfile.markets, "$").like(f'%"{market}"%'))
    if only_1031:
        stmt = stmt.where(InvestorProfile.exchange_1031.is_(True))
    if accreditation:
        if not svc.can_see_accreditation(user):
            raise HTTPException(403, "Your role may not filter by accreditation")
        stmt = stmt.where(InvestorProfile.accreditation_status == accreditation)
    if min_check_at_least:
        stmt = stmt.where(InvestorProfile.max_check >= min_check_at_least)
    items, total = paginate(db, stmt.order_by(InvestorProfile.id), page, limit)
    names = user_names(db)
    return {"items": [svc.investor_out(db, p, user, names) for p in items], "total": total, "page": page, "limit": limit}


@router.post("/investors", status_code=201)
def create_investor(body: ProfileIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    d = body.model_dump(exclude_none=True)
    if ("accreditation_status" in d or "accreditation_verified_on" in d) and not svc.can_see_accreditation(user):
        raise HTTPException(403, "Your role may not set accreditation data")
    p = svc.create_profile(db, d, user.id)
    db.commit()
    return svc.investor_out(db, p, user, user_names(db), detail=True)


@router.get("/investors/{pid}")
def get_investor(pid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    p = _profile(db, pid)
    if svc.can_see_accreditation(user):
        db.info["actor"], db.info["actor_id"] = user.name, user.id
        log_event(db, "view_investor_profile", "investor_profiles", p.id)  # sensitive data access is audited (ADR 0009, 0018)
        db.commit()
    return svc.investor_out(db, p, user, user_names(db), detail=True)


@router.patch("/investors/{pid}")
def patch_investor(pid: int, body: ProfileBase, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    p = _profile(db, pid)
    d = body.model_dump(exclude_unset=True)
    if ("accreditation_status" in d or "accreditation_verified_on" in d) and not svc.can_see_accreditation(user):
        raise HTTPException(403, "Your role may not change accreditation data")
    merged = {**{k: getattr(p, k) for k in ("min_check", "max_check", "exchange_1031", "exchange_deadline", "asset_classes", "accreditation_status", "preferred_channel", "contact_id", "company_id")}, **d}
    svc.validate_profile(db, merged)
    for k, v in d.items():
        setattr(p, k, v)
    db.commit()
    return svc.investor_out(db, p, user, user_names(db), detail=True)


@router.delete("/investors/{pid}", status_code=204)
def delete_investor(pid: int, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    _profile(db, pid).deleted_at = utcnow()
    db.commit()


@router.get("/investors/{pid}/matches")
def investor_matches(pid: int, ltv_pct: int = Query(svc.LTV_DEFAULT, ge=0, le=95), db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return {"items": svc.matches_for_investor(db, _profile(db, pid), ltv_pct)}


@router.get("/listings/{lid}/matches")
def listing_matches(lid: int, ltv_pct: int = Query(svc.LTV_DEFAULT, ge=0, le=95), db: Session = Depends(get_db), user: User = Depends(require("view"))):
    l = db.get(Listing, lid)
    if not l or l.deleted_at:
        raise HTTPException(404, "Listing not found")
    return {"listing_id": lid, "ltv_pct": ltv_pct, "suggestion_only": True, "items": svc.matches_for_listing(db, l, user, ltv_pct)}


# ---------------- funds ----------------
class FundIn(BaseModel):
    name: str = Field(min_length=1)
    sponsor_company_id: int | None = None
    status: str = "planning"
    target_raise: int = Field(gt=0)
    minimum_investment: int = Field(default=50000, gt=0)
    strategy: str | None = None
    target_return_notes: str | None = None
    opened_on: date | None = None
    closing_date: date | None = None


class FundPatch(BaseModel):
    status: str | None = None
    target_raise: int | None = Field(default=None, gt=0)
    minimum_investment: int | None = Field(default=None, gt=0)
    strategy: str | None = None
    closing_date: date | None = None


class CommitIn(BaseModel):
    investor_id: int
    fund_id: int
    amount: int = Field(gt=0)
    status: str = "interested"


class CommitStatusIn(BaseModel):
    status: str
    amount: int | None = Field(default=None, gt=0)


def _fund(db, fid) -> Fund:
    f = db.get(Fund, fid)
    if not f or f.deleted_at:
        raise HTTPException(404, "Fund not found")
    return f


@router.get("/funds")
def funds(status: str | None = None, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    stmt = select(Fund).where(Fund.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Fund.status == status)
    return {"items": [svc.fund_out(db, f) for f in db.scalars(stmt.order_by(Fund.id))]}


@router.post("/funds", status_code=201)
def create_fund(body: FundIn, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    if body.status not in FUND_STATUSES:
        raise HTTPException(422, f"status must be one of {FUND_STATUSES}")
    if db.scalar(select(Fund).where(Fund.name == body.name)):
        raise HTTPException(409, "A fund with that name exists")
    f = Fund(**body.model_dump())
    db.add(f)
    db.commit()
    return svc.fund_out(db, f, detail=True)


@router.get("/funds/{fid}")
def get_fund(fid: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return svc.fund_out(db, _fund(db, fid), detail=True)


@router.patch("/funds/{fid}")
def patch_fund(fid: int, body: FundPatch, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    f = _fund(db, fid)
    d = body.model_dump(exclude_unset=True)
    if d.get("status") and d["status"] not in FUND_STATUSES:
        raise HTTPException(422, f"status must be one of {FUND_STATUSES}")
    if d.get("target_raise") and d["target_raise"] < svc.fund_totals(db, f)["committed_or_funded"]:
        raise HTTPException(409, "target_raise cannot be below the amount already committed or funded")
    for k, v in d.items():
        setattr(f, k, v)
    db.commit()
    return svc.fund_out(db, f, detail=True)


@router.get("/funds/{fid}/commitments")
def fund_commitments(fid: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    f = _fund(db, fid)
    rows = db.scalars(select(Commitment).where(Commitment.fund_id == fid, Commitment.deleted_at.is_(None)).order_by(Commitment.amount.desc())).all()
    return {"items": [{"id": c.id, "investor_id": c.investor_id, "investor": svc.name_of(c.investor), "amount": c.amount, "status": c.status, "interested_on": c.interested_on,
                       "soft_circled_on": c.soft_circled_on, "committed_on": c.committed_on, "funded_on": c.funded_on,
                       **({"accreditation_status": c.investor.accreditation_status} if svc.can_see_accreditation(user) else {})} for c in rows]}


@router.post("/funds/{fid}/properties/{pid}", status_code=201)
def link_property(fid: int, pid: int, db: Session = Depends(get_db), _: User = Depends(require("edit"))):
    _fund(db, fid)
    if not db.get(Property, pid):
        raise HTTPException(422, "Unknown property")
    if not db.scalar(select(FundProperty).where(FundProperty.fund_id == fid, FundProperty.property_id == pid)):
        db.add(FundProperty(fund_id=fid, property_id=pid))
        db.commit()
    return svc.fund_out(db, db.get(Fund, fid), detail=True)


@router.post("/funds/{fid}/deals/{did}", status_code=201)
def link_deal(fid: int, did: int, db: Session = Depends(get_db), _: User = Depends(require("edit"))):
    _fund(db, fid)
    if not db.get(Deal, did):
        raise HTTPException(422, "Unknown deal")
    if not db.scalar(select(FundDeal).where(FundDeal.fund_id == fid, FundDeal.deal_id == did)):
        db.add(FundDeal(fund_id=fid, deal_id=did))
        db.commit()
    return svc.fund_out(db, db.get(Fund, fid), detail=True)


@router.post("/commitments", status_code=201)
def create_commitment(body: CommitIn, db: Session = Depends(get_db), _: User = Depends(require("create"))):
    c = svc.create_commitment(db, body.model_dump())
    db.commit()
    return {"id": c.id, "status": c.status, "amount": c.amount}


@router.post("/commitments/{cid}/status")
def commitment_status(cid: int, body: CommitStatusIn, db: Session = Depends(get_db), _: User = Depends(require("edit"))):
    c = db.get(Commitment, cid)
    if not c or c.deleted_at:
        raise HTTPException(404, "Commitment not found")
    svc.set_status(db, c, body.status, body.amount)
    db.commit()
    return {"id": c.id, "status": c.status, "amount": c.amount}


@router.delete("/commitments/{cid}", status_code=204)
def delete_commitment(cid: int, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    c = db.get(Commitment, cid)
    if not c:
        raise HTTPException(404, "Commitment not found")
    if c.status in ("committed", "funded"):
        raise HTTPException(409, "Committed or funded commitments cannot be deleted")
    c.deleted_at = utcnow()
    db.commit()
