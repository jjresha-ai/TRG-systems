"""Listings and buyer interest (ADR 0008). One service path for all buyer responses (email, form, manual)."""
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models.core import Company, Contact, Property
from ..models.core_sys import User
from ..models.pipeline import INTEREST_STAGES, BuyerInterest, BuyerInterestEvent, Listing, ListingBroker
from ..security import can_see_commission
from . import dedupe

TRANSITIONS = {
    "prospect": {"active", "withdrawn", "expired"},
    "active": {"under_contract", "expired", "withdrawn"},
    "under_contract": {"closed", "active", "withdrawn"},
    "closed": set(), "expired": {"active"}, "withdrawn": {"prospect", "active"},
}
ON_UNDER_CONTRACT = []  # hooks registered by the deals stage: fn(db, listing, user_id)
ON_TRANSITION = []  # fn(db, listing, old_status, new_status, extra, user_id)


def assert_single_active_sale(db: Session, listing: Listing):
    if listing.listing_type != "sale":
        return
    other = db.scalar(select(Listing).where(Listing.property_id == listing.property_id, Listing.listing_type == "sale", Listing.status.in_(["active", "under_contract"]), Listing.id != (listing.id or -1)))
    if other:
        raise HTTPException(409, f"Property already has an active sale listing (#{other.id})")


def validate_brokers(brokers: list[dict]):
    if brokers and round(sum(b.get("split_pct", 0) for b in brokers), 4) > 100:
        raise HTTPException(422, "Broker split shares exceed 100 percent")


def set_brokers(db: Session, listing: Listing, brokers: list[dict]):
    validate_brokers(brokers)
    for b in brokers:
        if not db.get(User, b["user_id"]):
            raise HTTPException(422, f"Unknown user {b['user_id']}")
    listing.brokers.clear()
    for b in brokers:
        listing.brokers.append(ListingBroker(user_id=b["user_id"], role=b.get("role", "lead"), split_pct=b.get("split_pct", 100.0)))


def create_listing(db: Session, data: dict, user_id: int) -> Listing:
    prop = db.get(Property, data["property_id"])
    if not prop or prop.deleted_at:
        raise HTTPException(422, "Unknown property")
    brokers = data.pop("brokers", None) or [{"user_id": data.get("owner_user_id") or user_id, "role": "lead", "split_pct": 100.0}]
    status = data.pop("status", "prospect")
    data["owner_user_id"] = data.get("owner_user_id") or user_id
    l = Listing(**data, status="prospect")
    set_brokers(db, l, brokers)
    db.add(l)
    db.flush()
    if status != "prospect":
        transition(db, l, status, {}, user_id)
    return l


def transition(db: Session, l: Listing, new: str, extra: dict, user_id: int | None) -> Listing:
    if new == l.status:
        return l
    old = l.status
    if new not in TRANSITIONS.get(l.status, set()):
        raise HTTPException(409, f"Cannot move a {l.status} listing to {new}")
    if new == "active":
        for f in ("list_price", "agreement_date", "expiration_date"):
            if not getattr(l, f) and not extra.get(f):
                raise HTTPException(422, f"{f} is required to activate a listing")
        for f in ("list_price", "agreement_date", "expiration_date"):
            if extra.get(f):
                setattr(l, f, extra[f])
        if l.expiration_date <= l.agreement_date:
            raise HTTPException(422, "Expiration must be after the listing agreement date")
        l.status = "active"
        assert_single_active_sale(db, l)
        l.active_date = l.active_date or date.today()
    elif new == "closed":
        if not extra.get("sold_price"):
            raise HTTPException(422, "sold_price is required to close a listing")
        l.sold_price, l.closed_date = extra["sold_price"], extra.get("closed_date") or date.today()
        l.status = "closed"
    elif new == "under_contract":
        l.status = "under_contract"
        for hook in ON_UNDER_CONTRACT:
            hook(db, l, user_id)
    else:
        l.status = new
    db.flush()
    for hook in ON_TRANSITION:
        hook(db, l, old, new, extra, user_id)
    return l


def days_on_market(l: Listing, today: date | None = None) -> int | None:
    if not l.active_date:
        return None
    end = l.closed_date if l.status == "closed" and l.closed_date else (today or date.today())
    return max((end - l.active_date).days, 0)


def listing_out(db: Session, l: Listing, user: User, names: dict) -> dict:
    p = l.property
    interests = db.scalars(select(BuyerInterest).where(BuyerInterest.listing_id == l.id)).all()
    funnel = {s: 0 for s in INTEREST_STAGES}
    for i in interests:
        funnel[i.stage] += 1
    seller = db.get(Company, l.seller_company_id) if l.seller_company_id else None
    sc = db.get(Contact, l.seller_contact_id) if l.seller_contact_id else None
    out = {"id": l.id, "property_id": l.property_id, "address": p.address, "city": p.city, "property_name": p.name, "property_type": p.property_type,
           "subtype": p.subtype, "market": p.market, "building_sf": p.building_sf, "listing_type": l.listing_type, "status": l.status,
           "list_price": l.list_price, "sold_price": l.sold_price, "price_per_sf": round(l.list_price / p.building_sf) if l.list_price and p.building_sf else None,
           "cap_rate_bps": round(p.noi / l.list_price * 10000) if l.list_price and p.noi else p.cap_rate_bps,
           "agreement_date": l.agreement_date, "expiration_date": l.expiration_date, "active_date": l.active_date, "closed_date": l.closed_date,
           "days_on_market": days_on_market(l), "days_to_expiration": (l.expiration_date - date.today()).days if l.expiration_date else None,
           "seller_company": seller.name if seller else None, "seller_company_id": l.seller_company_id,
           "seller_contact": sc.full_name if sc else None, "seller_contact_id": l.seller_contact_id,
           "confidential": l.confidential, "owner_user_id": l.owner_user_id, "owner_name": names.get(l.owner_user_id),
           "brokers": [{"user_id": b.user_id, "name": names.get(b.user_id), "role": b.role, "split_pct": b.split_pct} for b in l.brokers],
           "interest_total": len(interests), "funnel": funnel, "deal_id": l.deal_id, "created_at": l.created_at}
    if can_see_commission(user):
        out["commission_rate_bps"] = l.commission_rate_bps
        out["commission_terms"] = l.commission_terms
        out["expected_commission"] = round((l.sold_price or l.list_price or 0) * (l.commission_rate_bps or 0) / 10000) if l.commission_rate_bps else None
    return out


# ---------------- buyer interest ----------------
def can_view_buyer_identity(l: Listing, user: User) -> bool:
    return not l.confidential or user.role in ("admin", "manager", "broker")


def interest_out(db: Session, i: BuyerInterest, l: Listing, user: User, names: dict) -> dict:
    c = db.get(Contact, i.contact_id)
    co = db.get(Company, i.company_id) if i.company_id else None
    show = can_view_buyer_identity(l, user)
    return {"id": i.id, "listing_id": i.listing_id, "contact_id": i.contact_id if show else None,
            "contact": c.full_name if show else f"Confidential buyer #{i.id}", "company": (co.name if co else None) if show else None,
            "stage": i.stage, "offer_amount": i.offer_amount, "offer_terms": i.offer_terms, "declined_reason": i.declined_reason, "channel": i.channel,
            "events": [{"stage": e.stage, "at": e.at, "user": names.get(e.user_id), "amount": e.amount, "note": e.note} for e in i.events],
            "first_at": i.events[0].at if i.events else None, "last_at": i.events[-1].at if i.events else None}


OUTREACH_STAGES = {"ca_sent", "om_sent"}


def record_interest(db: Session, listing: Listing, data: dict, user_id: int | None) -> BuyerInterest:
    stage = data.get("stage", "inquiry")
    if stage not in INTEREST_STAGES:
        raise HTTPException(422, f"stage must be one of {INTEREST_STAGES}")
    if listing.status not in ("active", "under_contract", "prospect"):
        raise HTTPException(409, f"Listing is {listing.status}")
    contact = db.get(Contact, data["contact_id"]) if data.get("contact_id") else None
    if data.get("contact_id") and (not contact or contact.deleted_at):
        raise HTTPException(422, "Unknown contact")
    if not contact:
        c = data.get("contact") or {}
        if not (c.get("last_name") and (c.get("email") or c.get("phone"))):
            raise HTTPException(422, "Provide contact_id or contact {first_name,last_name,email|phone}")
        from . import entities
        d, _ = dedupe.contact_matches(db, [c["email"]] if c.get("email") else [], [c["phone"]] if c.get("phone") else [], c.get("first_name", ""), c["last_name"])
        if d:
            contact = list(d.values())[0][0]
        else:
            contact = entities.create_contact(db, {"first_name": c.get("first_name") or "Unknown", "last_name": c["last_name"], "contact_types": ["buyer"], "source": f"listing inquiry ({data.get('channel', 'manual')})",
                                                   "emails": [{"email": c["email"]}] if c.get("email") else [], "phones": [{"phone": c["phone"]}] if c.get("phone") else []}, user_id or 0)
    if stage in OUTREACH_STAGES and contact.do_not_contact:
        raise HTTPException(409, f"{contact.full_name} is marked do-not-contact; outreach is blocked")
    i = db.scalar(select(BuyerInterest).where(BuyerInterest.listing_id == listing.id, BuyerInterest.contact_id == contact.id))
    if not i:
        i = BuyerInterest(listing_id=listing.id, contact_id=contact.id, company_id=data.get("company_id"), channel=data.get("channel", "manual"), stage="inquiry")
        db.add(i)
        db.flush()
        if stage != "inquiry":
            i.events.append(BuyerInterestEvent(stage="inquiry", at=data.get("at") or utcnow(), user_id=user_id))
    apply_stage(db, i, stage, data, user_id)
    return i


def apply_stage(db: Session, i: BuyerInterest, stage: str, data: dict, user_id: int | None):
    order = {s: n for n, s in enumerate(INTEREST_STAGES)}
    if i.stage == "declined" and stage != "declined":
        raise HTTPException(409, "Buyer already declined")
    if stage != "declined" and order[stage] < order[i.stage]:
        raise HTTPException(409, f"Cannot move a buyer from {i.stage} back to {stage}")
    if stage == "offer":
        if not data.get("amount"):
            raise HTTPException(422, "Offers require an amount")
        i.offer_amount, i.offer_terms = data["amount"], data.get("terms")
    if stage == "declined":
        i.declined_reason = data.get("reason") or data.get("note")
    if stage == i.stage and stage not in ("offer",) and not i.events:
        pass
    i.stage = stage
    i.events.append(BuyerInterestEvent(stage=stage, at=data.get("at") or utcnow(), user_id=user_id, amount=data.get("amount"), note=data.get("note")))
    db.flush()


def _search_listings(db, q, ql, toks, want):
    if not want("listing"):
        return []
    from .search import _score
    out = []
    for l in db.scalars(select(Listing).where(Listing.deleted_at.is_(None))):
        p = l.property
        s = max(_score(p.address, ql, toks), _score(p.name or "", ql, toks))
        if s > 0:
            out.append({"type": "listing", "id": l.id, "title": f"Listing: {p.address}", "subtitle": f"{l.status.replace('_', ' ').title()} · {p.city}",
                        "score": s - 1, "url": f"/listings/{l.id}", "connections": []})
    return out


from .search import SEARCH_PROVIDERS  # noqa: E402
SEARCH_PROVIDERS.append(_search_listings)
