"""Create/update logic and serializers for Contact, Company, Property (business rules live here, ADR 0004)."""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.core import (COMPANY_KINDS, CONTACT_TYPES, HOLD_INTENTS, LIFECYCLE, PROPERTY_TYPES, Company, Contact,
                           ContactCompanyRole, ContactEmail, ContactPhone, DuplicateCandidate, Property, PropertyOwnership)
from . import dedupe
from .common import years_between
from .normalize import norm_address, norm_apn, norm_company_name, norm_domain, norm_email, norm_phone
from .search import current_owners, holdings_of_contact


def _check(value, allowed, label):
    if value is not None and value not in allowed:
        raise HTTPException(422, f"{label} must be one of {allowed}")


def _dup_error(entity, definite):
    raise HTTPException(409, {"message": f"Duplicate {entity}", "matches": dedupe.describe(definite)})


# ---------------- contacts ----------------
def set_contact_channels(c: Contact, emails, phones):
    if emails is not None:
        c.emails.clear()
        seen = set()
        for i, e in enumerate(emails):
            n = norm_email(e["email"])
            if not n or n in seen:
                continue
            seen.add(n)
            c.emails.append(ContactEmail(email=e["email"].strip(), normalized=n, label=e.get("label", "work"), is_primary=e.get("is_primary", i == 0)))
    if phones is not None:
        c.phones.clear()
        seen = set()
        for i, p in enumerate(phones):
            n = norm_phone(p["phone"])
            if not n or n in seen:
                raise HTTPException(422, f"Invalid or repeated phone: {p['phone']}")
            seen.add(n)
            c.phones.append(ContactPhone(phone=p["phone"].strip(), normalized=n, label=p.get("label", "mobile"), is_primary=p.get("is_primary", i == 0)))


def create_contact(db: Session, data: dict, user_id: int) -> Contact:
    _check(data.get("lifecycle_stage"), LIFECYCLE, "lifecycle_stage")
    for t in data.get("contact_types") or []:
        _check(t, CONTACT_TYPES, "contact_types")
    company_links = data.pop("company_links", None) or []
    emails, phones = data.pop("emails", None) or [], data.pop("phones", None) or []
    cnames = [db.get(Company, l["company_id"]).name for l in company_links if db.get(Company, l["company_id"])]
    definite, possible = dedupe.contact_matches(db, [e["email"] for e in emails], [p["phone"] for p in phones],
                                                data["first_name"], data["last_name"], cnames)
    if definite:
        _dup_error("contact", definite)
    data["owner_user_id"] = data.get("owner_user_id") or user_id
    c = Contact(**data, full_name=f"{data['first_name']} {data['last_name']}".strip())
    set_contact_channels(c, emails, phones)
    db.add(c)
    db.flush()
    for l in company_links:
        if not db.get(Company, l["company_id"]):
            raise HTTPException(422, "Unknown company")
        db.add(ContactCompanyRole(contact_id=c.id, company_id=l["company_id"], role=l.get("role", "principal"), is_primary=l.get("is_primary", False)))
    dedupe.queue_possible(db, "contact", c.id, possible)
    return c


def update_contact(db: Session, c: Contact, data: dict) -> Contact:
    _check(data.get("lifecycle_stage"), LIFECYCLE, "lifecycle_stage")
    for t in data.get("contact_types") or []:
        _check(t, CONTACT_TYPES, "contact_types")
    emails, phones = data.pop("emails", None), data.pop("phones", None)
    if emails is not None or phones is not None:
        definite, _ = dedupe.contact_matches(db, [e["email"] for e in emails or []], [p["phone"] for p in phones or []], "", "", exclude_id=c.id)
        if definite:
            _dup_error("contact", definite)
    for k, v in data.items():
        setattr(c, k, v)
    if "first_name" in data or "last_name" in data:
        c.full_name = f"{c.first_name} {c.last_name}".strip()
    set_contact_channels(c, emails, phones)
    return c


def contact_summary(db: Session, c: Contact, names: dict, with_holdings=True) -> dict:
    role = db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == c.id).order_by(ContactCompanyRole.is_primary.desc(), ContactCompanyRole.id)).first()
    pe = next((e for e in c.emails if e.is_primary), c.emails[0] if c.emails else None)
    pp = next((p for p in c.phones if p.is_primary), c.phones[0] if c.phones else None)
    return {"id": c.id, "full_name": c.full_name, "first_name": c.first_name, "last_name": c.last_name, "title": c.title,
            "primary_email": pe.email if pe else None, "primary_phone": pp.phone if pp else None,
            "company": role.company.name if role else None, "company_id": role.company_id if role else None,
            "contact_types": c.contact_types, "lifecycle_stage": c.lifecycle_stage, "status": c.status,
            "owner_user_id": c.owner_user_id, "owner_name": names.get(c.owner_user_id), "last_contact_at": c.last_contact_at,
            "tags": c.tags, "do_not_contact": c.do_not_contact, "city": c.city,
            "holdings_count": len(holdings_of_contact(db, c.id)) if with_holdings else None}


def contact_detail(db: Session, c: Contact, names: dict) -> dict:
    d = contact_summary(db, c, names)
    roles = db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == c.id)).all()
    pend = db.scalars(select(DuplicateCandidate).where(DuplicateCandidate.entity == "contact", DuplicateCandidate.status == "pending",
                                                       (DuplicateCandidate.a_id == c.id) | (DuplicateCandidate.b_id == c.id))).all()
    d.update(address=c.address, state=c.state, zip=c.zip, source=c.source, created_at=c.created_at, custom=c.custom,
             do_not_contact_reason=c.do_not_contact_reason, confidential=c.confidential,
             emails=[{"id": e.id, "email": e.email, "label": e.label, "is_primary": e.is_primary} for e in c.emails],
             phones=[{"id": p.id, "phone": p.phone, "label": p.label, "is_primary": p.is_primary} for p in c.phones],
             companies=[{"role_id": r.id, "company_id": r.company_id, "company": r.company.name, "kind": r.company.kind, "role": r.role,
                         "is_primary": r.is_primary, "end_date": r.end_date} for r in roles],
             holdings=holdings_of_contact(db, c.id),
             possible_duplicates=[{"id": p.id, "other_id": p.b_id if p.a_id == c.id else p.a_id, "reason": p.reason} for p in pend])
    return d


# ---------------- companies ----------------
def create_company(db: Session, data: dict, user_id: int) -> Company:
    _check(data.get("kind"), COMPANY_KINDS, "kind")
    definite, possible = dedupe.company_matches(db, data["name"], data.get("website"), data.get("address"), data.get("city"))
    if definite:
        _dup_error("company", definite)
    data["owner_user_id"] = data.get("owner_user_id") or user_id
    co = Company(**data, normalized_name=norm_company_name(data["name"]), domain=norm_domain(data.get("website")),
                 normalized_address=norm_address(data.get("address"), data.get("city")) if data.get("address") else None)
    db.add(co)
    db.flush()
    dedupe.queue_possible(db, "company", co.id, possible)
    return co


def update_company(db: Session, co: Company, data: dict) -> Company:
    _check(data.get("kind"), COMPANY_KINDS, "kind")
    for k, v in data.items():
        setattr(co, k, v)
    co.normalized_name = norm_company_name(co.name)
    co.domain = norm_domain(co.website)
    co.normalized_address = norm_address(co.address, co.city) if co.address else None
    return co


def company_summary(db: Session, co: Company, names: dict) -> dict:
    owned = db.scalars(select(PropertyOwnership).where(PropertyOwnership.company_id == co.id, PropertyOwnership.disposed_date.is_(None))).all()
    n_principals = len(db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.company_id == co.id, ContactCompanyRole.end_date.is_(None))).all())
    return {"id": co.id, "name": co.name, "kind": co.kind, "website": co.website, "city": co.city, "state": co.state,
            "owner_user_id": co.owner_user_id, "owner_name": names.get(co.owner_user_id), "tags": co.tags,
            "last_contact_at": co.last_contact_at, "properties_count": len(owned), "principals_count": n_principals,
            "portfolio_value": sum(o.property.estimated_value or 0 for o in owned)}


def company_detail(db: Session, co: Company, names: dict) -> dict:
    d = company_summary(db, co, names)
    roles = db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.company_id == co.id)).all()
    own = db.scalars(select(PropertyOwnership).where(PropertyOwnership.company_id == co.id).order_by(PropertyOwnership.acquired_date.desc())).all()
    parent = db.get(Company, co.parent_company_id) if co.parent_company_id else None
    kids = db.scalars(select(Company).where(Company.parent_company_id == co.id, Company.deleted_at.is_(None))).all()
    d.update(address=co.address, zip=co.zip, source=co.source, custom=co.custom, created_at=co.created_at,
             parent={"id": parent.id, "name": parent.name} if parent else None,
             children=[{"id": k.id, "name": k.name} for k in kids],
             principals=[{"role_id": r.id, "contact_id": r.contact_id, "name": r.contact.full_name, "role": r.role, "is_primary": r.is_primary,
                          "end_date": r.end_date, "title": r.contact.title} for r in roles],
             holdings=[{"ownership_id": o.id, "property_id": o.property_id, "address": o.property.address, "city": o.property.city,
                        "property_type": o.property.property_type, "acquired_date": o.acquired_date, "disposed_date": o.disposed_date,
                        "ownership_pct": o.ownership_pct, "estimated_value": o.property.estimated_value} for o in own])
    return d


# ---------------- properties ----------------
def create_property(db: Session, data: dict, user_id: int) -> Property:
    _check(data.get("property_type"), PROPERTY_TYPES, "property_type")
    _check(data.get("hold_intent"), HOLD_INTENTS, "hold_intent")
    definite, possible = dedupe.property_matches(db, data["address"], data.get("city"), data.get("apn"), data.get("county"))
    if definite:
        _dup_error("property", definite)
    data["owner_user_id"] = data.get("owner_user_id") or user_id
    p = Property(**data, normalized_address=norm_address(data["address"], data.get("city")), apn_norm=norm_apn(data.get("apn")))
    db.add(p)
    db.flush()
    dedupe.queue_possible(db, "property", p.id, possible)
    return p


def update_property(db: Session, p: Property, data: dict) -> Property:
    _check(data.get("property_type"), PROPERTY_TYPES, "property_type")
    _check(data.get("hold_intent"), HOLD_INTENTS, "hold_intent")
    for k, v in data.items():
        setattr(p, k, v)
    p.normalized_address = norm_address(p.address, p.city)
    p.apn_norm = norm_apn(p.apn)
    return p


def hold_years(db: Session, p: Property) -> float | None:
    dates = [o.acquired_date for o in db.scalars(select(PropertyOwnership).where(PropertyOwnership.property_id == p.id, PropertyOwnership.disposed_date.is_(None))) if o.acquired_date]
    return years_between(min(dates)) if dates else None


def property_summary(db: Session, p: Property, names: dict) -> dict:
    owners = current_owners(db, p.id)
    return {"id": p.id, "name": p.name, "address": p.address, "city": p.city, "zip": p.zip, "apn": p.apn, "county": p.county,
            "property_type": p.property_type, "subtype": p.subtype, "market": p.market, "submarket": p.submarket,
            "building_sf": p.building_sf, "land_acres": p.land_acres, "units": p.units, "year_built": p.year_built,
            "noi": p.noi, "cap_rate_bps": p.cap_rate_bps, "estimated_value": p.estimated_value, "lat": p.lat, "lng": p.lng,
            "lender": p.lender, "loan_maturity_date": p.loan_maturity_date, "hold_intent": p.hold_intent,
            "owner_user_id": p.owner_user_id, "owner_name": names.get(p.owner_user_id), "last_contact_at": p.last_contact_at,
            "hold_years": hold_years(db, p), "tags": p.tags,
            "current_owner": owners[0]["company"] or owners[0].get("name") if owners else None,
            "principal": owners[0]["principals"][0]["name"] if owners and owners[0]["principals"] else None}


def property_detail(db: Session, p: Property, names: dict) -> dict:
    d = property_summary(db, p, names)
    hist = db.scalars(select(PropertyOwnership).where(PropertyOwnership.property_id == p.id).order_by(PropertyOwnership.acquired_date.desc())).all()
    d.update(zoning=p.zoning, loan_original_amount=p.loan_original_amount, loan_rate_type=p.loan_rate_type,
             pricing_expectation=p.pricing_expectation, source=p.source, custom=p.custom, created_at=p.created_at,
             owners=current_owners(db, p.id),
             ownership_history=[{"id": o.id, "company_id": o.company_id, "company": o.company.name if o.company else None,
                                 "contact_id": o.contact_id, "contact": o.contact.full_name if o.contact else None,
                                 "ownership_pct": o.ownership_pct, "acquired_date": o.acquired_date, "disposed_date": o.disposed_date,
                                 "acquisition_price": o.acquisition_price} for o in hist])
    return d


def transfer_ownership(db: Session, p: Property, data: dict) -> PropertyOwnership:
    if not data.get("company_id") and not data.get("contact_id"):
        raise HTTPException(422, "company_id or contact_id is required")
    if data.get("company_id") and not db.get(Company, data["company_id"]):
        raise HTTPException(422, "Unknown company")
    if data.get("contact_id") and not db.get(Contact, data["contact_id"]):
        raise HTTPException(422, "Unknown contact")
    when = data.get("acquired_date") or date.today()
    if data.get("dispose_current", True):
        for o in db.scalars(select(PropertyOwnership).where(PropertyOwnership.property_id == p.id, PropertyOwnership.disposed_date.is_(None))):
            o.disposed_date = when
    o = PropertyOwnership(property_id=p.id, company_id=data.get("company_id"), contact_id=data.get("contact_id"),
                          ownership_pct=data.get("ownership_pct", 100.0), acquired_date=when, acquisition_price=data.get("acquisition_price"))
    db.add(o)
    db.flush()
    return o
