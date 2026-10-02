"""Duplicate detection (ADR 0006): definite (exact key) vs possible (fuzzy, queued for review)."""
from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models.core import (Company, Contact, ContactEmail, ContactPhone, DuplicateCandidate, Property)
from .normalize import norm_address, norm_apn, norm_company_name, norm_domain, norm_email, norm_phone


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ---------- contacts ----------
def contact_matches(db: Session, emails=(), phones=(), first="", last="", company_names=(), exclude_id=None):
    definite, possible = {}, {}
    ne = [e for e in (norm_email(x) for x in emails) if e]
    npn = [p for p in (norm_phone(x) for x in phones) if p]
    if ne:
        for c in db.scalars(select(Contact).join(ContactEmail).where(ContactEmail.normalized.in_(ne), Contact.deleted_at.is_(None))):
            definite[c.id] = (c, "same email")
    if npn:
        for c in db.scalars(select(Contact).join(ContactPhone).where(ContactPhone.normalized.in_(npn), Contact.deleted_at.is_(None))):
            definite.setdefault(c.id, (c, "same phone"))
    full = f"{first} {last}".strip()
    if last:
        cos = {norm_company_name(n) for n in company_names if n}
        for c in db.scalars(select(Contact).where(Contact.last_name.ilike(last), Contact.deleted_at.is_(None))):
            if c.id in definite:
                continue
            r = _ratio(c.full_name, full)
            same_co = bool(cos) and any(norm_company_name(role.company.name) in cos for role in _roles(db, c.id))
            if (r >= 0.8 and same_co) or r >= 0.93:
                possible[c.id] = (c, f"similar name ({r:.0%})" + (", same company" if same_co else ""))
    for d in (definite, possible):
        d.pop(exclude_id, None)
    return definite, possible


def _roles(db, contact_id):
    from ..models.core import ContactCompanyRole
    return db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == contact_id)).all()


# ---------- companies ----------
def company_matches(db: Session, name: str, website=None, address=None, city=None, exclude_id=None):
    definite, possible = {}, {}
    nn, dom = norm_company_name(name), norm_domain(website)
    na = norm_address(address, city) if address else None
    q = select(Company).where(Company.deleted_at.is_(None))
    for c in db.scalars(q):
        if c.id == exclude_id:
            continue
        if nn and c.normalized_name == nn:
            definite[c.id] = (c, "same name")
        elif dom and c.domain == dom:
            definite[c.id] = (c, "same website domain")
        elif na and c.normalized_address == na:
            definite[c.id] = (c, "same address")
        elif nn and c.normalized_name:
            r = _ratio(c.normalized_name, nn)
            if r >= 0.92:
                possible[c.id] = (c, f"similar name ({r:.0%})")
    return definite, possible


# ---------- properties ----------
def property_matches(db: Session, address: str, city=None, apn=None, county=None, exclude_id=None):
    definite, possible = {}, {}
    na, napn = norm_address(address, city), norm_apn(apn)
    for p in db.scalars(select(Property).where(Property.deleted_at.is_(None))):
        if p.id == exclude_id:
            continue
        if napn and p.apn_norm == napn and (not county or p.county.lower() == county.lower()):
            definite[p.id] = (p, "same APN and county")
        elif p.normalized_address == na:
            definite[p.id] = (p, "same address")
        elif city and p.city.lower() == city.lower():
            r = _ratio(p.normalized_address, na)
            if r >= 0.92:
                possible[p.id] = (p, f"similar address ({r:.0%})")
    return definite, possible


def describe(matches: dict) -> list[dict]:
    return [{"id": i, "name": getattr(o, "full_name", None) or getattr(o, "name", None) or getattr(o, "address", ""), "reason": r}
            for i, (o, r) in matches.items()]


def queue_possible(db: Session, entity: str, new_id: int, possible: dict):
    for other_id, (_, reason) in possible.items():
        a, b = sorted((new_id, other_id))
        exists = db.scalar(select(DuplicateCandidate).where(DuplicateCandidate.entity == entity, DuplicateCandidate.a_id == a, DuplicateCandidate.b_id == b))
        if not exists:
            db.add(DuplicateCandidate(entity=entity, a_id=a, b_id=b, score=0.9, reason=reason))
            db.flush()


def scan_all(db: Session) -> dict:
    """Backfill job: find possible duplicates across the whole database."""
    for c in db.scalars(select(Contact).where(Contact.deleted_at.is_(None))):
        co = [r.company.name for r in _roles(db, c.id)]
        d, p = contact_matches(db, [e.email for e in c.emails], [x.phone for x in c.phones], c.first_name, c.last_name, co, exclude_id=c.id)
        queue_possible(db, "contact", c.id, {**p, **d})
    for c in db.scalars(select(Company).where(Company.deleted_at.is_(None))):
        d, p = company_matches(db, c.name, c.website, c.address, c.city, exclude_id=c.id)
        queue_possible(db, "company", c.id, {**p, **d})
    for pr in db.scalars(select(Property).where(Property.deleted_at.is_(None))):
        d, p = property_matches(db, pr.address, pr.city, pr.apn, pr.county, exclude_id=pr.id)
        queue_possible(db, "property", pr.id, {**p, **d})
    db.flush()
    return {"pending": db.query(DuplicateCandidate).filter_by(status="pending").count()}
