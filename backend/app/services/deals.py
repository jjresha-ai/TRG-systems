"""Deals and pipelines (ADR 0010): stage rules, history, splits, forecast. Business rules live here (ADR 0004)."""
from collections import defaultdict
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models.core import Company, Contact, Property
from ..models.core_sys import User
from ..models.deals import (CommissionSplit, Deal, DealParty, DealStageHistory, PARTY_ROLES, Pipeline, Stage)
from ..models.pipeline import BuyerInterest, Listing
from ..security import can_see_commission
from . import listings as listings_svc
from . import prospecting

KEY_DATE_HOOKS = []  # stage 4 registers: fn(db, deal) creates tasks from key dates

DEFAULT_PIPELINES = {
    "seller": ("Seller-side (Listings)", "sale", [
        ("prospect", "Prospect", 10, 30), ("pitch", "Pitch", 20, 21), ("listing_agreement", "Listing agreement", 35, 14), ("marketing", "Marketing", 50, 120),
        ("offers", "Offers", 65, 30), ("under_contract", "Under contract", 80, 21), ("due_diligence", "Due diligence", 90, 45)]),
    "buyer": ("Buyer representation", "buyer_rep", [
        ("qualification", "Qualification", 10, 30), ("search", "Search", 25, 90), ("offer", "Offer", 45, 21), ("under_contract", "Under contract", 75, 21), ("due_diligence", "Due diligence", 90, 45)]),
    "capital": ("Capital / syndication", "capital", [
        ("initial_discussion", "Initial discussion", 10, 30), ("materials", "Materials sent", 25, 30), ("soft_circled", "Soft-circled", 50, 45), ("committed", "Committed", 80, 30)]),
    "leasing": ("Leasing", "lease", [
        ("inquiry", "Inquiry", 10, 21), ("tour", "Tour", 25, 21), ("proposal", "Proposal / LOI", 45, 30), ("lease_negotiation", "Lease negotiation", 70, 45)]),
}


def ensure_default_pipelines(db: Session):
    for key, (name, dtype, stages) in DEFAULT_PIPELINES.items():
        if db.scalar(select(Pipeline).where(Pipeline.key == key)):
            continue
        p = Pipeline(key=key, name=name, deal_type=dtype)
        pos = 0
        for skey, sname, prob, rot in stages:
            p.stages.append(Stage(key=skey, name=sname, position=pos, probability=prob, rotting_days=rot))
            pos += 1
        p.stages.append(Stage(key="closed", name="Closed", position=pos, probability=100, is_won=True))
        p.stages.append(Stage(key="lost", name="Lost", position=pos + 1, probability=0, is_lost=True))
        db.add(p)
    db.flush()


def get_pipeline(db: Session, key_or_id) -> Pipeline:
    ensure_default_pipelines(db)
    p = db.get(Pipeline, key_or_id) if isinstance(key_or_id, int) else db.scalar(select(Pipeline).where(Pipeline.key == key_or_id))
    if not p:
        raise HTTPException(404, "Pipeline not found")
    return p


def stage_by_key(p: Pipeline, key: str) -> Stage:
    s = next((s for s in p.stages if s.key == key), None)
    if not s:
        raise HTTPException(422, f"Pipeline {p.key} has no stage {key}")
    return s


def effective_probability(d: Deal) -> int:
    return d.probability if d.probability is not None else d.stage.probability


def gross_of(d: Deal) -> int | None:
    if d.gross_commission is not None:
        return d.gross_commission
    if d.commission_rate_bps and d.price:
        return round(d.price * d.commission_rate_bps / 10000)
    return None


def days_in_stage(d: Deal) -> int:
    return max((utcnow() - d.stage_entered_at).days, 0)


def is_rotting(d: Deal) -> bool:
    return d.status == "open" and bool(d.stage.rotting_days) and days_in_stage(d) > d.stage.rotting_days


def _dedupe_roles(parties):
    for p in parties:
        if p["role"] not in PARTY_ROLES:
            raise HTTPException(422, f"party role must be one of {PARTY_ROLES}")
        if not p.get("contact_id") and not p.get("company_id"):
            raise HTTPException(422, "Each party needs a contact_id or company_id")


def create_deal(db: Session, data: dict, user_id: int | None, at: datetime | None = None) -> Deal:
    pipe = get_pipeline(db, data.pop("pipeline_id", None) or data.pop("pipeline", "seller")) if ("pipeline_id" in data or "pipeline" in data) else get_pipeline(db, "seller")
    data.pop("pipeline", None)
    stage = next((s for s in pipe.stages if s.id == data.pop("stage_id", None)), None) if data.get("stage_id") else None
    stage_key = data.pop("stage", None)
    stage = stage or (stage_by_key(pipe, stage_key) if stage_key else pipe.stages[0])
    if stage.is_won or stage.is_lost:
        raise HTTPException(422, "New deals must start in an open stage")
    parties = data.pop("parties", None) or []
    _dedupe_roles(parties)
    if data.get("property_id") and not db.get(Property, data["property_id"]):
        raise HTTPException(422, "Unknown property")
    if data.get("price") is not None and data["price"] <= 0:
        raise HTTPException(422, "price must be positive")
    now = at or utcnow()
    d = Deal(**data, pipeline_id=pipe.id, stage_id=stage.id, status="open", deal_type=pipe.deal_type, stage_entered_at=now)
    d.owner_user_id = d.owner_user_id or user_id
    for p in parties:
        d.parties.append(DealParty(**p))
    db.add(d)
    db.flush()
    db.add(DealStageHistory(deal_id=d.id, from_stage_id=None, to_stage_id=stage.id, at=now, user_id=user_id, note="Created"))
    db.flush()
    for h in KEY_DATE_HOOKS:
        h(db, d)
    return d


def change_stage(db: Session, d: Deal, stage_id: int | None, stage_key: str | None, user_id: int | None, extra: dict | None = None, at: datetime | None = None, note: str | None = None, from_listing: bool = False) -> Deal:
    extra = extra or {}
    pipe = d.pipeline
    stage = next((s for s in pipe.stages if s.id == stage_id or (stage_key and s.key == stage_key)), None)
    if not stage:
        raise HTTPException(422, "Stage does not belong to this deal's pipeline")
    if d.status == "won":
        raise HTTPException(409, "Closed deals cannot change stage")
    if stage.id == d.stage_id:
        return d
    for f in ("price", "gross_commission", "commission_rate_bps", "dd_expiry_date", "loan_contingency_date", "expected_close_date"):
        if extra.get(f) is not None:
            setattr(d, f, extra[f])
    if stage.is_lost:
        reason = extra.get("lost_reason") or d.lost_reason
        if not reason:
            raise HTTPException(422, "A lost reason is required to mark a deal lost")
        d.lost_reason, d.status = reason, "lost"
    elif stage.is_won:
        if not d.price or d.price <= 0:
            raise HTTPException(422, "A price is required before closing a deal")
        d.status, d.actual_close_date = "won", extra.get("actual_close_date") or date.today()
        d.lost_reason = None
    else:
        if stage.key == "under_contract" and not d.price:
            raise HTTPException(422, "A price is required to go under contract")
        if stage.key == "due_diligence" and not d.dd_expiry_date:
            raise HTTPException(422, "dd_expiry_date is required to enter due diligence")
        d.status, d.lost_reason = "open", None
    prev = d.stage_id
    now = at or utcnow()
    d.stage_id, d.stage_entered_at = stage.id, now
    d.stage = stage
    db.add(DealStageHistory(deal_id=d.id, from_stage_id=prev, to_stage_id=stage.id, at=now, user_id=user_id, note=note))
    db.flush()
    if not from_listing:
        _sync_listing(db, d, stage)
    for h in KEY_DATE_HOOKS:
        h(db, d)
    return d


def _sync_listing(db: Session, d: Deal, stage: Stage):
    if not d.listing_id:
        return
    l = db.get(Listing, d.listing_id)
    if not l:
        return
    if stage.is_won and l.status == "under_contract":
        l.status, l.sold_price, l.closed_date = "closed", d.price, d.actual_close_date
    elif stage.key in ("under_contract", "due_diligence") and l.status == "active":
        l.status = "under_contract"
    elif stage.is_lost and l.status == "under_contract":
        l.status = "active"
    db.flush()


def set_splits(db: Session, d: Deal, splits: list[dict]):
    pct = sum(s.get("pct") or 0 for s in splits if s.get("split_type", "percent") == "percent")
    if round(pct, 4) > 100:
        raise HTTPException(422, "Commission splits exceed 100 percent")
    gross = gross_of(d)
    amt = sum(s.get("amount") or 0 for s in splits if s.get("split_type") == "amount")
    if gross is not None and amt + gross * pct / 100 > gross + 0.5:
        raise HTTPException(422, "Commission splits exceed the gross commission")
    for s in splits:
        st = s.get("split_type", "percent")
        if st not in ("percent", "amount"):
            raise HTTPException(422, "split_type must be percent or amount")
        if st == "percent" and not s.get("pct"):
            raise HTTPException(422, "pct is required for percent splits")
        if st == "amount" and not s.get("amount"):
            raise HTTPException(422, "amount is required for amount splits")
        if not s.get("recipient_user_id") and not s.get("external_name"):
            raise HTTPException(422, "A recipient (user or external name) is required")
        if s.get("recipient_user_id") and not db.get(User, s["recipient_user_id"]):
            raise HTTPException(422, "Unknown recipient user")
    d.splits.clear()
    for s in splits:
        kind = s.get("kind") or ("internal" if s.get("recipient_user_id") else "co_broker")
        d.splits.append(CommissionSplit(recipient_user_id=s.get("recipient_user_id"), external_name=s.get("external_name"), kind=kind,
                                        split_type=s.get("split_type", "percent"), pct=s.get("pct"), amount=s.get("amount")))
    db.flush()


def add_party(db: Session, d: Deal, p: dict):
    _dedupe_roles([p])
    if p.get("contact_id") and not db.get(Contact, p["contact_id"]):
        raise HTTPException(422, "Unknown contact")
    if p.get("company_id") and not db.get(Company, p["company_id"]):
        raise HTTPException(422, "Unknown company")
    d.parties.append(DealParty(**p))
    db.flush()


def _split_amounts(d: Deal) -> list[dict]:
    gross = gross_of(d)
    out = []
    for s in d.splits:
        amt = s.amount if s.split_type == "amount" else (round(gross * s.pct / 100) if gross is not None else None)
        out.append({"id": s.id, "recipient_user_id": s.recipient_user_id, "external_name": s.external_name, "kind": s.kind,
                    "split_type": s.split_type, "pct": s.pct, "amount": amt})
    return out


def deal_out(db: Session, d: Deal, user: User, names: dict, detail: bool = False) -> dict:
    p = d.property
    prob = effective_probability(d)
    out = {"id": d.id, "name": d.name, "pipeline": {"id": d.pipeline.id, "key": d.pipeline.key, "name": d.pipeline.name},
           "stage": {"id": d.stage.id, "key": d.stage.key, "name": d.stage.name, "probability": d.stage.probability, "rotting_days": d.stage.rotting_days, "is_won": d.stage.is_won, "is_lost": d.stage.is_lost},
           "status": d.status, "deal_type": d.deal_type, "property_id": d.property_id,
           "property": {"address": p.address, "city": p.city, "property_type": p.property_type, "subtype": p.subtype, "building_sf": p.building_sf} if p else None,
           "listing_id": d.listing_id, "price": d.price, "probability": prob, "probability_override": d.probability,
           "expected_close_date": d.expected_close_date, "actual_close_date": d.actual_close_date, "listing_expiration_date": d.listing_expiration_date,
           "dd_expiry_date": d.dd_expiry_date, "loan_contingency_date": d.loan_contingency_date, "lost_reason": d.lost_reason,
           "days_in_stage": days_in_stage(d), "rotting": is_rotting(d), "owner_user_id": d.owner_user_id, "owner_name": names.get(d.owner_user_id),
           "source": d.source, "created_at": d.created_at, "tags": d.tags,
           "parties": [{"id": x.id, "role": x.role, "contact_id": x.contact_id, "company_id": x.company_id,
                        "contact": db.get(Contact, x.contact_id).full_name if x.contact_id else None,
                        "company": db.get(Company, x.company_id).name if x.company_id else None} for x in d.parties]}
    if can_see_commission(user):
        g = gross_of(d)
        out.update(gross_commission=g, commission_rate_bps=d.commission_rate_bps, weighted_commission=round(g * prob / 100) if g is not None and d.status == "open" else None)
        if detail:
            out["splits"] = _split_amounts(d)
    if detail:
        hist = db.scalars(select(DealStageHistory).where(DealStageHistory.deal_id == d.id).order_by(DealStageHistory.at, DealStageHistory.id)).all()
        stages = {s.id: s for s in d.pipeline.stages}
        rows = []
        for i, h in enumerate(hist):
            end = hist[i + 1].at if i + 1 < len(hist) else utcnow()
            rows.append({"id": h.id, "stage": stages[h.to_stage_id].name, "stage_key": stages[h.to_stage_id].key, "from": stages[h.from_stage_id].name if h.from_stage_id else None,
                         "at": h.at, "user": names.get(h.user_id), "note": h.note, "days": max((end - h.at).days, 0)})
        out["history"] = rows
    return out


def forecast(db: Session, user: User, pipeline_key: str | None = None) -> dict:
    stmt = select(Deal).where(Deal.status == "open", Deal.deleted_at.is_(None))
    if pipeline_key:
        stmt = stmt.where(Deal.pipeline_id == get_pipeline(db, pipeline_key).id)
    show = can_see_commission(user)
    months: dict[str, dict] = defaultdict(lambda: {"count": 0, "volume": 0, "weighted_volume": 0, "commission": 0, "weighted_commission": 0})
    stages: dict[str, dict] = defaultdict(lambda: {"count": 0, "volume": 0, "weighted_volume": 0, "weighted_commission": 0, "position": 0})
    totals = {"count": 0, "volume": 0, "weighted_volume": 0, "commission": 0, "weighted_commission": 0}
    for d in db.scalars(stmt):
        prob = effective_probability(d) / 100
        price, g = d.price or 0, gross_of(d) or 0
        key = d.expected_close_date.strftime("%Y-%m") if d.expected_close_date else "unscheduled"
        for bucket in (months[key], stages[d.stage.name], totals):
            bucket["count"] += 1
            bucket["volume"] = bucket.get("volume", 0) + price
            bucket["weighted_volume"] = bucket.get("weighted_volume", 0) + round(price * prob)
            if "commission" in bucket:
                bucket["commission"] += g
            bucket["weighted_commission"] = bucket.get("weighted_commission", 0) + round(g * prob)
        stages[d.stage.name]["position"] = d.stage.position
    if not show:  # field-level restriction applies to reports too (ADR 0017)
        for b in [*months.values(), *stages.values(), totals]:
            b.pop("commission", None)
            b.pop("weighted_commission", None)
    return {"totals": totals, "by_month": [{"month": k, **v} for k, v in sorted(months.items())],
            "by_stage": [{"stage": k, **v} for k, v in sorted(stages.items(), key=lambda kv: kv[1]["position"])], "commission_visible": show}


# ---------- integrations with leads and listings ----------
def deal_for_lead(db: Session, lead, contact, company, user_id) -> int:
    prop = lead.property
    name = f"{prop.address if prop else (company.name if company else lead.name)} — Sale"
    parties = []
    if contact:
        parties.append({"role": "seller", "contact_id": contact.id})
    elif company:
        parties.append({"role": "seller", "company_id": company.id})
    d = create_deal(db, {"name": name, "pipeline": "seller", "property_id": prop.id if prop else None, "source": "lead conversion", "parties": parties,
                         "owner_user_id": lead.owner_user_id, "price": prop.estimated_value if prop else None}, user_id)
    return d.id


def listing_hook(db: Session, l: Listing, old: str, new: str, extra: dict, user_id: int | None):
    """Keep the deal and listing consistent in both directions (ADR 0008, 0010)."""
    d = db.get(Deal, l.deal_id) if l.deal_id else None
    if new == "under_contract":
        top = db.scalar(select(BuyerInterest).where(BuyerInterest.listing_id == l.id, BuyerInterest.offer_amount.is_not(None)).order_by(BuyerInterest.offer_amount.desc()))
        price = (top.offer_amount if top else None) or l.list_price
        pipe = get_pipeline(db, "seller")
        if d is None:
            parties = []
            if l.seller_contact_id:
                parties.append({"role": "seller", "contact_id": l.seller_contact_id})
            if l.seller_company_id:
                parties.append({"role": "seller", "company_id": l.seller_company_id})
            if top:
                parties.append({"role": "buyer", "contact_id": top.contact_id})
            d = create_deal(db, {"name": f"{l.property.address} — Sale", "pipeline": "seller", "stage": "marketing", "property_id": l.property_id, "listing_id": l.id,
                                 "price": price, "commission_rate_bps": l.commission_rate_bps, "listing_expiration_date": l.expiration_date, "owner_user_id": l.owner_user_id,
                                 "source": "listing", "parties": parties}, user_id)
            l.deal_id = d.id
        if d.stage.key not in ("under_contract", "due_diligence"):
            change_stage(db, d, None, "under_contract", user_id, {"price": price}, from_listing=True, note="Listing went under contract")
    elif new == "closed" and d and d.status == "open":
        if d.stage.key not in ("under_contract", "due_diligence"):
            change_stage(db, d, None, "under_contract", user_id, {"price": l.sold_price}, from_listing=True)
        change_stage(db, d, None, "closed", user_id, {"price": l.sold_price, "actual_close_date": l.closed_date}, from_listing=True, note="Listing closed")
    elif old == "under_contract" and new in ("active", "withdrawn") and d and d.status == "open":
        change_stage(db, d, None, "lost", user_id, {"lost_reason": "Contract terminated"}, from_listing=True, note="Listing returned to market")


def install_hooks():
    from . import prospecting as pr
    pr.DEAL_CREATOR = deal_for_lead
    if listing_hook not in listings_svc.ON_TRANSITION:
        listings_svc.ON_TRANSITION.append(listing_hook)


install_hooks()
