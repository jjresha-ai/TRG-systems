from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models.core import Property
from ..models.core_sys import User
from ..models.deals import Deal, DealParty, Pipeline, Stage
from ..security import can_see_commission, require
from ..services import deals as svc
from ..services.common import paginate, user_names

router = APIRouter(prefix="/api", tags=["deals"])


class PartyIn(BaseModel):
    role: str
    contact_id: int | None = None
    company_id: int | None = None


class DealIn(BaseModel):
    name: str = Field(min_length=1)
    pipeline: str = "seller"
    stage: str | None = None
    property_id: int | None = None
    price: int | None = Field(default=None, gt=0)
    gross_commission: int | None = Field(default=None, ge=0)
    commission_rate_bps: int | None = Field(default=None, ge=0, le=2000)
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    listing_expiration_date: date | None = None
    dd_expiry_date: date | None = None
    loan_contingency_date: date | None = None
    owner_user_id: int | None = None
    source: str | None = "manual"
    parties: list[PartyIn] = []
    tags: list[str] = []


class DealPatch(BaseModel):
    name: str | None = None
    price: int | None = Field(default=None, gt=0)
    gross_commission: int | None = Field(default=None, ge=0)
    commission_rate_bps: int | None = Field(default=None, ge=0, le=2000)
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    listing_expiration_date: date | None = None
    dd_expiry_date: date | None = None
    loan_contingency_date: date | None = None
    owner_user_id: int | None = None
    tags: list[str] | None = None


class StageIn(BaseModel):
    stage_id: int | None = None
    stage: str | None = None
    price: int | None = None
    lost_reason: str | None = None
    dd_expiry_date: date | None = None
    expected_close_date: date | None = None
    actual_close_date: date | None = None
    note: str | None = None


class SplitIn(BaseModel):
    recipient_user_id: int | None = None
    external_name: str | None = None
    kind: str | None = None
    split_type: str = "percent"
    pct: float | None = Field(default=None, gt=0, le=100)
    amount: int | None = Field(default=None, gt=0)


class SplitsIn(BaseModel):
    splits: list[SplitIn]


COMMISSION_FIELDS = {"gross_commission", "commission_rate_bps"}


def _get(db, did) -> Deal:
    d = db.get(Deal, did)
    if not d or d.deleted_at:
        raise HTTPException(404, "Deal not found")
    return d


def _guard_commission(user: User, fields: set[str]):
    if fields & COMMISSION_FIELDS and not can_see_commission(user):
        raise HTTPException(403, "Your role may not change commission fields")


@router.get("/pipelines")
def pipelines(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    svc.ensure_default_pipelines(db)
    db.commit()
    return [{"id": p.id, "key": p.key, "name": p.name, "deal_type": p.deal_type,
             "stages": [{"id": s.id, "key": s.key, "name": s.name, "position": s.position, "probability": s.probability, "rotting_days": s.rotting_days, "is_won": s.is_won, "is_lost": s.is_lost} for s in p.stages]}
            for p in db.scalars(select(Pipeline).order_by(Pipeline.id))]


class StagePatch(BaseModel):
    probability: int | None = Field(default=None, ge=0, le=100)
    rotting_days: int | None = Field(default=None, ge=1)


@router.patch("/stages/{sid}")
def patch_stage(sid: int, body: StagePatch, db: Session = Depends(get_db), _: User = Depends(require("admin"))):
    s = db.get(Stage, sid)
    if not s:
        raise HTTPException(404, "Stage not found")
    if s.is_won or s.is_lost:
        raise HTTPException(409, "Terminal stages are fixed")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    return {"id": s.id, "probability": s.probability, "rotting_days": s.rotting_days}


@router.get("/deals")
def list_deals(pipeline: str | None = None, stage_id: int | None = None, status: str | None = None, owner_id: int | None = None, property_type: str | None = None,
               q: str | None = None, closing_before: date | None = None, rotting: bool | None = None, property_id: int | None = None, sort: str = "recent",
               page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(require("view"))):
    stmt = select(Deal).where(Deal.deleted_at.is_(None))
    if pipeline:
        stmt = stmt.where(Deal.pipeline_id == svc.get_pipeline(db, pipeline).id)
    if stage_id:
        stmt = stmt.where(Deal.stage_id == stage_id)
    if status:
        stmt = stmt.where(Deal.status == status)
    if owner_id:
        stmt = stmt.where(Deal.owner_user_id == owner_id)
    if property_id:
        stmt = stmt.where(Deal.property_id == property_id)
    if property_type:
        stmt = stmt.where(Deal.property_id.in_(select(Property.id).where(Property.property_type == property_type)))
    if q:
        stmt = stmt.where(Deal.name.ilike(f"%{q}%"))
    if closing_before:
        stmt = stmt.where(Deal.expected_close_date <= closing_before)
    order = {"recent": Deal.created_at.desc(), "close": Deal.expected_close_date.asc(), "price": Deal.price.desc()}.get(sort, Deal.created_at.desc())
    items, total = paginate(db, stmt.order_by(order, Deal.id), page, limit)
    names = user_names(db)
    rows = [svc.deal_out(db, d, user, names) for d in items]
    if rotting is not None:
        rows = [r for r in rows if r["rotting"] == rotting]
    return {"items": rows, "total": total if rotting is None else len(rows), "page": page, "limit": limit}


@router.get("/deals/board")
def board(pipeline: str = "seller", owner_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    pipe = svc.get_pipeline(db, pipeline)
    names = user_names(db)
    cols = []
    for s in pipe.stages:
        if s.is_lost:
            continue
        stmt = select(Deal).where(Deal.stage_id == s.id, Deal.deleted_at.is_(None))
        if owner_id:
            stmt = stmt.where(Deal.owner_user_id == owner_id)
        if s.is_won:
            from datetime import timedelta
            stmt = stmt.where(Deal.actual_close_date >= date.today() - timedelta(days=365))
        deals = db.scalars(stmt.order_by(Deal.expected_close_date.asc().nulls_last(), Deal.id)).all()
        outs = [svc.deal_out(db, d, user, names) for d in deals]
        col = {"stage": {"id": s.id, "key": s.key, "name": s.name, "probability": s.probability, "rotting_days": s.rotting_days, "is_won": s.is_won},
               "count": len(outs), "volume": sum(o["price"] or 0 for o in outs), "deals": outs[:40]}
        if can_see_commission(user):
            col["weighted_commission"] = sum(o.get("weighted_commission") or 0 for o in outs)
            col["commission"] = sum(o.get("gross_commission") or 0 for o in outs)
        cols.append(col)
    return {"pipeline": {"id": pipe.id, "key": pipe.key, "name": pipe.name}, "columns": cols}


@router.get("/deals/forecast")
def forecast(pipeline: str | None = None, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return svc.forecast(db, user, pipeline)


@router.get("/deals/stalled")
def stalled(db: Session = Depends(get_db), user: User = Depends(require("view"))):
    names = user_names(db)
    rows = [svc.deal_out(db, d, user, names) for d in db.scalars(select(Deal).where(Deal.status == "open", Deal.deleted_at.is_(None)))]
    rows = sorted([r for r in rows if r["rotting"]], key=lambda r: -(r["days_in_stage"] - (r["stage"]["rotting_days"] or 0)))
    return {"items": rows, "total": len(rows)}


@router.post("/deals", status_code=201)
def create_deal(body: DealIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    d = body.model_dump(exclude_none=True)
    _guard_commission(user, set(d))
    d["parties"] = [p for p in d.get("parties", [])]
    deal = svc.create_deal(db, d, user.id)
    db.commit()
    return svc.deal_out(db, deal, user, user_names(db), detail=True)


@router.get("/deals/{did}")
def get_deal(did: int, db: Session = Depends(get_db), user: User = Depends(require("view"))):
    return svc.deal_out(db, _get(db, did), user, user_names(db), detail=True)


@router.patch("/deals/{did}")
def patch_deal(did: int, body: DealPatch, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    d = _get(db, did)
    fields = body.model_dump(exclude_unset=True)
    _guard_commission(user, set(fields))
    if d.status == "won" and set(fields) - {"tags", "name"}:
        raise HTTPException(409, "Closed deals are locked")
    for k, v in fields.items():
        setattr(d, k, v)
    db.flush()
    for h in svc.KEY_DATE_HOOKS:
        h(db, d)
    db.commit()
    return svc.deal_out(db, d, user, user_names(db), detail=True)


@router.post("/deals/{did}/stage")
def move_stage(did: int, body: StageIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    d = _get(db, did)
    if not body.stage_id and not body.stage:
        raise HTTPException(422, "stage_id or stage is required")
    svc.change_stage(db, d, body.stage_id, body.stage, user.id, body.model_dump(exclude_none=True), note=body.note)
    db.commit()
    return svc.deal_out(db, d, user, user_names(db), detail=True)


@router.post("/deals/{did}/parties", status_code=201)
def add_party(did: int, body: PartyIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    d = _get(db, did)
    svc.add_party(db, d, body.model_dump())
    db.commit()
    return svc.deal_out(db, d, user, user_names(db), detail=True)


@router.delete("/deals/{did}/parties/{pid}", status_code=204)
def remove_party(did: int, pid: int, db: Session = Depends(get_db), _: User = Depends(require("edit"))):
    p = db.get(DealParty, pid)
    if not p or p.deal_id != did:
        raise HTTPException(404, "Party not found")
    db.delete(p)
    db.commit()


@router.put("/deals/{did}/splits")
def put_splits(did: int, body: SplitsIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    if not can_see_commission(user):
        raise HTTPException(403, "Your role may not change commission fields")
    d = _get(db, did)
    svc.set_splits(db, d, [s.model_dump() for s in body.splits])
    db.commit()
    return svc.deal_out(db, d, user, user_names(db), detail=True)


@router.delete("/deals/{did}", status_code=204)
def delete_deal(did: int, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    _get(db, did).deleted_at = utcnow()
    db.commit()
