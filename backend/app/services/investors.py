"""Investors, funds, commitments, matching (ADR 0009)."""
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.core import Company, Contact, Property
from ..models.core_sys import User
from ..models.deals import Deal
from ..models.investors import (ACCREDITATION, CHANNELS, COMMITMENT_STATUSES, Commitment, Fund, FundDeal, FundProperty, InvestorProfile)
from ..models.pipeline import Listing
from ..security import ACCREDITATION_VIEW_ROLES

LTV_DEFAULT = 60  # percent: used to turn a price into the equity an investor must write

ASSUMPTION_ACCREDITED_TO_COMMIT = True  # compliance rule to be confirmed with securities counsel (Reg D)


def can_see_accreditation(user: User) -> bool:
    return user.role in ACCREDITATION_VIEW_ROLES


def name_of(p: InvestorProfile) -> str:
    return p.contact.full_name if p.contact else (p.company.name if p.company else f"Investor #{p.id}")


def investor_out(db: Session, p: InvestorProfile, user: User, names: dict, detail=False) -> dict:
    commits = db.scalars(select(Commitment).where(Commitment.investor_id == p.id, Commitment.deleted_at.is_(None))).all()
    total = {s: sum(c.amount for c in commits if c.status == s) for s in COMMITMENT_STATUSES}
    out = {"id": p.id, "name": name_of(p), "contact_id": p.contact_id, "company_id": p.company_id, "asset_classes": p.asset_classes, "markets": p.markets,
           "min_check": p.min_check, "max_check": p.max_check, "min_cap_rate_bps": p.min_cap_rate_bps, "target_return_notes": p.target_return_notes,
           "exchange_1031": p.exchange_1031, "exchange_deadline": p.exchange_deadline,
           "days_to_1031": (p.exchange_deadline - date.today()).days if p.exchange_deadline else None, "preferred_channel": p.preferred_channel,
           "owner_user_id": p.owner_user_id, "owner_name": names.get(p.owner_user_id), "commitment_totals": total, "commitments": len(commits),
           "do_not_contact": bool(p.contact and p.contact.do_not_contact), "title": p.contact.title if p.contact else None,
           "firm": p.company.name if p.company else None, "created_at": p.created_at}
    if can_see_accreditation(user):
        out["accreditation_status"] = p.accreditation_status
        out["accreditation_verified_on"] = p.accreditation_verified_on
    if detail:
        out["notes"] = p.notes
        out["commitment_list"] = [{"id": c.id, "fund_id": c.fund_id, "fund": c.fund.name, "amount": c.amount, "status": c.status, "interested_on": c.interested_on, "committed_on": c.committed_on, "funded_on": c.funded_on} for c in commits]
    return out


def validate_profile(db: Session, data: dict):
    if not data.get("contact_id") and not data.get("company_id"):
        raise HTTPException(422, "An investor profile needs a contact_id or company_id")
    if data.get("contact_id") and not db.get(Contact, data["contact_id"]):
        raise HTTPException(422, "Unknown contact")
    if data.get("company_id") and not db.get(Company, data["company_id"]):
        raise HTTPException(422, "Unknown company")
    mn, mx = data.get("min_check"), data.get("max_check")
    if mn is not None and mx is not None and mn > mx:
        raise HTTPException(422, "min_check cannot exceed max_check")
    if data.get("accreditation_status") and data["accreditation_status"] not in ACCREDITATION:
        raise HTTPException(422, f"accreditation_status must be one of {ACCREDITATION}")
    if data.get("preferred_channel") and data["preferred_channel"] not in CHANNELS:
        raise HTTPException(422, f"preferred_channel must be one of {CHANNELS}")
    for a in data.get("asset_classes") or []:
        if a not in ("retail", "industrial"):
            raise HTTPException(422, "asset_classes may contain retail and industrial")
    if data.get("exchange_deadline") and not data.get("exchange_1031", True):
        raise HTTPException(422, "exchange_deadline requires exchange_1031")


def create_profile(db: Session, data: dict, user_id: int) -> InvestorProfile:
    validate_profile(db, data)
    key = {"contact_id": data.get("contact_id")} if data.get("contact_id") else {"company_id": data["company_id"]}
    col = getattr(InvestorProfile, next(iter(key)))
    if db.scalar(select(InvestorProfile).where(col == next(iter(key.values())), InvestorProfile.deleted_at.is_(None))):
        raise HTTPException(409, "This contact or company already has an investor profile")
    if data.get("exchange_deadline") and "exchange_1031" not in data:
        data["exchange_1031"] = True
    p = InvestorProfile(**data)
    p.owner_user_id = p.owner_user_id or user_id
    db.add(p)
    db.flush()
    c = db.get(Contact, p.contact_id) if p.contact_id else None
    if c and "investor" not in (c.contact_types or []):
        c.contact_types = [*c.contact_types, "investor"]
    return p


# ---------------- funds ----------------
def fund_totals(db: Session, f: Fund) -> dict:
    rows = db.scalars(select(Commitment).where(Commitment.fund_id == f.id, Commitment.deleted_at.is_(None))).all()
    by = {s: {"amount": 0, "count": 0} for s in COMMITMENT_STATUSES}
    for c in rows:
        by[c.status]["amount"] += c.amount
        by[c.status]["count"] += 1
    firm = by["committed"]["amount"] + by["funded"]["amount"]
    return {"by_status": by, "committed_or_funded": firm, "pct_of_target": round(firm / f.target_raise * 100, 1) if f.target_raise else 0,
            "pipeline_interest": sum(v["amount"] for v in by.values()), "investors": len({c.investor_id for c in rows})}


def fund_out(db: Session, f: Fund, detail=False) -> dict:
    sponsor = db.get(Company, f.sponsor_company_id) if f.sponsor_company_id else None
    out = {"id": f.id, "name": f.name, "sponsor": sponsor.name if sponsor else None, "sponsor_company_id": f.sponsor_company_id, "status": f.status, "target_raise": f.target_raise,
           "minimum_investment": f.minimum_investment, "strategy": f.strategy, "target_return_notes": f.target_return_notes, "opened_on": f.opened_on, "closing_date": f.closing_date,
           **fund_totals(db, f)}
    if detail:
        out["properties"] = [{"id": x.property_id, "address": db.get(Property, x.property_id).address, "city": db.get(Property, x.property_id).city} for x in f.properties]
        out["deals"] = [{"id": x.deal_id, "name": db.get(Deal, x.deal_id).name, "status": db.get(Deal, x.deal_id).status} for x in f.deals]
    return out


def commit_rules(db: Session, c: Commitment, new_status: str, amount: int):
    f = db.get(Fund, c.fund_id)
    inv = db.get(InvestorProfile, c.investor_id)
    if f.status == "closed" or f.status == "deployed":
        if new_status != c.status or amount != c.amount:
            raise HTTPException(409, f"Fund is {f.status}; commitments can no longer change")
    if new_status in ("soft_circled", "committed", "funded") and amount < f.minimum_investment:
        raise HTTPException(422, f"Minimum investment for {f.name} is ${f.minimum_investment:,}")
    if new_status in ("committed", "funded"):
        if ASSUMPTION_ACCREDITED_TO_COMMIT and inv.accreditation_status != "accredited":
            raise HTTPException(409, "Investor must be accredited before committing (accreditation is not verified)")
        others = db.scalar(select(func.coalesce(func.sum(Commitment.amount), 0)).where(Commitment.fund_id == f.id, Commitment.status.in_(["committed", "funded"]), Commitment.deleted_at.is_(None), Commitment.id != (c.id or -1)))
        if others + amount > f.target_raise:
            raise HTTPException(409, f"Commitment would exceed the fund target of ${f.target_raise:,} (already ${others:,})")


def create_commitment(db: Session, data: dict) -> Commitment:
    inv, f = db.get(InvestorProfile, data["investor_id"]), db.get(Fund, data["fund_id"])
    if not inv or inv.deleted_at:
        raise HTTPException(422, "Unknown investor")
    if not f or f.deleted_at:
        raise HTTPException(422, "Unknown fund")
    if data["amount"] <= 0:
        raise HTTPException(422, "amount must be positive")
    if db.scalar(select(Commitment).where(Commitment.investor_id == inv.id, Commitment.fund_id == f.id, Commitment.deleted_at.is_(None))):
        raise HTTPException(409, "This investor already has a commitment in this fund")
    c = Commitment(investor_id=inv.id, fund_id=f.id, amount=data["amount"], status="interested", interested_on=data.get("interested_on") or date.today())
    if f.status in ("closed", "deployed"):
        raise HTTPException(409, f"Fund is {f.status}; no new commitments")
    db.add(c)
    db.flush()
    status = data.get("status", "interested")
    if status != "interested":
        set_status(db, c, status, data["amount"])
    return c


def set_status(db: Session, c: Commitment, new: str, amount: int | None = None) -> Commitment:
    if new not in COMMITMENT_STATUSES:
        raise HTTPException(422, f"status must be one of {COMMITMENT_STATUSES}")
    order = {s: i for i, s in enumerate(COMMITMENT_STATUSES)}
    if order[new] < order[c.status]:
        raise HTTPException(409, f"Cannot move a commitment back from {c.status} to {new}")
    amt = amount if amount is not None else c.amount
    if amt <= 0:
        raise HTTPException(422, "amount must be positive")
    commit_rules(db, c, new, amt)
    c.amount, c.status = amt, new
    today = date.today()
    for st in COMMITMENT_STATUSES[: order[new] + 1]:
        if getattr(c, f"{st}_on") is None:
            setattr(c, f"{st}_on", today)
    db.flush()
    return c


# ---------------- matching ----------------
def listing_equity(price: int, ltv: int) -> int:
    return round(price * (100 - ltv) / 100)


def match_score(p: InvestorProfile, prop: Property, price: int, cap_bps: int | None, ltv: int, today: date | None = None):
    """Returns (score, reasons, excluded_reason). Asset class is a gate; everything else adds transparent points."""
    today = today or date.today()
    reasons: list[str] = []
    if p.asset_classes and prop.property_type not in p.asset_classes:
        return 0, [], f"Asset class mismatch ({prop.property_type})"
    score = 0
    if p.asset_classes:
        score += 30
        reasons.append(f"Asset class: {prop.property_type}")
    if p.markets:
        if prop.market in p.markets:
            score += 25
            reasons.append(f"Market: {prop.market}")
        else:
            return 0, [], f"Market mismatch ({prop.market})"
    if price and (p.min_check or p.max_check):
        eq = listing_equity(price, ltv)
        lo, hi = p.min_check or 0, p.max_check or 10**12
        if lo <= eq <= hi:
            score += 25
            reasons.append(f"Equity ~${eq:,} (at {ltv}% LTV) is within check size ${lo:,}-${hi:,}")
        elif lo * 0.75 <= eq <= hi * 1.25:
            score += 10
            reasons.append(f"Equity ~${eq:,} is near check size ${lo:,}-${hi:,}")
        else:
            return 0, [], f"Check size mismatch (equity ~${eq:,})"
    if p.exchange_1031 and p.exchange_deadline:
        d = (p.exchange_deadline - today).days
        if d < 0:
            return 0, [], "1031 deadline has passed"
        pts = 20 if d <= 120 else 10
        score += pts
        reasons.append(f"1031 buyer: {d} days to deadline")
    elif p.exchange_1031:
        score += 5
        reasons.append("1031 buyer")
    if p.min_cap_rate_bps and cap_bps:
        if cap_bps >= p.min_cap_rate_bps:
            score += 10
            reasons.append(f"Cap rate {cap_bps / 100:.2f}% meets minimum {p.min_cap_rate_bps / 100:.2f}%")
        else:
            score -= 10
            reasons.append(f"Cap rate {cap_bps / 100:.2f}% is below minimum {p.min_cap_rate_bps / 100:.2f}%")
    if p.accreditation_status == "accredited":
        score += 5
    return score, reasons, None


def matches_for_listing(db: Session, l: Listing, user: User, ltv: int = LTV_DEFAULT, limit: int = 25) -> list[dict]:
    price = l.list_price or l.property.estimated_value or 0
    cap = round(l.property.noi / price * 10000) if l.property.noi and price else l.property.cap_rate_bps
    out = []
    for p in db.scalars(select(InvestorProfile).where(InvestorProfile.deleted_at.is_(None))):
        score, reasons, excl = match_score(p, l.property, price, cap, ltv)
        if excl or score <= 0:
            continue
        o = {"investor_id": p.id, "name": name_of(p), "contact_id": p.contact_id, "score": score, "reasons": reasons, "blocked_do_not_contact": bool(p.contact and p.contact.do_not_contact),
             "min_check": p.min_check, "max_check": p.max_check, "preferred_channel": p.preferred_channel}
        if can_see_accreditation(user):
            o["accreditation_status"] = p.accreditation_status
        out.append(o)
    out.sort(key=lambda r: (-r["score"], r["name"]))
    return out[:limit]


def matches_for_investor(db: Session, p: InvestorProfile, ltv: int = LTV_DEFAULT, limit: int = 25) -> list[dict]:
    out = []
    for l in db.scalars(select(Listing).where(Listing.status == "active", Listing.deleted_at.is_(None), Listing.listing_type == "sale")):
        price = l.list_price or 0
        cap = round(l.property.noi / price * 10000) if l.property.noi and price else l.property.cap_rate_bps
        score, reasons, excl = match_score(p, l.property, price, cap, ltv)
        if excl or score <= 0:
            continue
        out.append({"listing_id": l.id, "address": l.property.address, "city": l.property.city, "property_type": l.property.property_type, "list_price": l.list_price, "score": score, "reasons": reasons})
    out.sort(key=lambda r: -r["score"])
    return out[:limit]


from . import merge as _merge  # noqa: E402
_merge.register_relink("contact", InvestorProfile, "contact_id")
_merge.register_relink("company", InvestorProfile, "company_id")
