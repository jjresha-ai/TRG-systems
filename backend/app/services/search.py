"""Global search (ADR 0015): ranked, fuzzy, graph-aware. Providers register per entity."""
import re
from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models.core import (Company, Contact, ContactCompanyRole, ContactEmail, ContactPhone, Property, PropertyOwnership)
from .normalize import norm_address, norm_apn, norm_email, norm_phone


def _tokens(q: str) -> list[str]:
    return [t for t in re.split(r"\s+", q.strip().lower()) if t]


def _score(text: str, q: str, toks: list[str]) -> float:
    t = text.lower()
    if not t:
        return 0
    if t == q:
        return 100
    s = 0.0
    if t.startswith(q):
        s = 80
    elif q in t:
        s = 60
    elif all(tok in t for tok in toks):
        s = 50
    else:
        words = re.split(r"[\s,.]+", t)
        best = [max((SequenceMatcher(None, tok, w).ratio() for w in words), default=0) for tok in toks]
        avg = sum(best) / len(best)
        s = avg * 48 if avg >= 0.8 else 0
    return s


def current_owners(db: Session, property_id: int):
    rows = db.scalars(select(PropertyOwnership).where(PropertyOwnership.property_id == property_id, PropertyOwnership.disposed_date.is_(None))).all()
    out = []
    for r in rows:
        if r.company:
            principals = db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.company_id == r.company_id, ContactCompanyRole.end_date.is_(None))).all()
            out.append({"company_id": r.company_id, "company": r.company.name, "contact_id": None, "pct": r.ownership_pct,
                        "principals": [{"id": p.contact_id, "name": p.contact.full_name, "role": p.role} for p in principals]})
        elif r.contact:
            out.append({"company_id": None, "company": None, "contact_id": r.contact_id, "name": r.contact.full_name, "pct": r.ownership_pct, "principals": []})
    return out


def holdings_of_contact(db: Session, contact_id: int):
    """Properties connected to a person directly or through entities they are a principal of."""
    props = {}
    for o in db.scalars(select(PropertyOwnership).where(PropertyOwnership.contact_id == contact_id, PropertyOwnership.disposed_date.is_(None))):
        props[o.property_id] = {"property_id": o.property_id, "address": o.property.address, "city": o.property.city, "via": "direct"}
    for role in db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == contact_id, ContactCompanyRole.end_date.is_(None))):
        for o in db.scalars(select(PropertyOwnership).where(PropertyOwnership.company_id == role.company_id, PropertyOwnership.disposed_date.is_(None))):
            props.setdefault(o.property_id, {"property_id": o.property_id, "address": o.property.address, "city": o.property.city, "via": role.company.name})
    return list(props.values())


def search(db: Session, q: str, limit: int = 20, types: set[str] | None = None, extra_providers=None):
    q = q.strip()
    if len(q) < 2:
        return []
    ql, toks = q.lower(), _tokens(q)
    ne, npn, napn, naddr = norm_email(q), norm_phone(q) if re.search(r"\d{7,}", re.sub(r"\D", "", q)) else None, norm_apn(q), norm_address(q)
    results = []

    def want(t):
        return not types or t in types

    if want("contact"):
        like = [Contact.full_name.ilike(f"%{t[:3]}%") for t in toks]
        cond = or_(*[c for c in like]) if like else None
        ids = set()
        if "@" in q:
            ids |= set(db.scalars(select(ContactEmail.contact_id).where(ContactEmail.normalized.like(f"%{ne}%"))))
        if npn:
            ids |= set(db.scalars(select(ContactPhone.contact_id).where(ContactPhone.normalized == npn)))
        stmt = select(Contact).where(Contact.deleted_at.is_(None), or_(cond, Contact.id.in_(ids)) if ids else cond)
        for c in db.scalars(stmt.limit(300)):
            s = max(_score(c.full_name, ql, toks), 95 if c.id in ids else 0, _score(c.title or "", ql, toks) * 0.3)
            if s > 0:
                co = db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == c.id)).first()
                results.append({"type": "contact", "id": c.id, "title": c.full_name, "subtitle": " · ".join(x for x in [c.title, co.company.name if co else None] if x),
                                "score": s, "url": f"/contacts/{c.id}",
                                "connections": [h["address"] for h in holdings_of_contact(db, c.id)[:3]]})
    if want("company"):
        like = [Company.name.ilike(f"%{t[:3]}%") for t in toks]
        for co in db.scalars(select(Company).where(Company.deleted_at.is_(None), or_(*like)).limit(300)):
            s = _score(co.name, ql, toks)
            if s > 0:
                results.append({"type": "company", "id": co.id, "title": co.name, "subtitle": f"{co.kind.replace('_', ' ').title()} · {co.city or ''}".strip(" ·"),
                                "score": s, "url": f"/companies/{co.id}", "connections": []})
    if want("property"):
        like = [Property.address.ilike(f"%{t[:3]}%") for t in toks] + [Property.name.ilike(f"%{t[:3]}%") for t in toks] + [Property.city.ilike(f"%{t[:3]}%") for t in toks]
        if napn:
            like.append(Property.apn_norm == napn)
        for p in db.scalars(select(Property).where(Property.deleted_at.is_(None), or_(*like)).limit(300)):
            s = max(_score(p.address, ql, toks), _score(p.name or "", ql, toks), 98 if napn and p.apn_norm == napn else 0)
            s = max(s, _score(f"{p.address} {p.city}", ql, toks))
            if s > 0:
                owners = current_owners(db, p.id)
                conn = []
                for o in owners:
                    conn.append(o["company"] or o.get("name"))
                    conn += [pr["name"] for pr in o["principals"][:2]]
                results.append({"type": "property", "id": p.id, "title": p.address, "subtitle": f"{p.city} · {p.property_type.title()}{' · ' + p.subtype if p.subtype else ''}",
                                "score": s, "url": f"/properties/{p.id}", "connections": [c for c in conn if c]})
    for provider in extra_providers or SEARCH_PROVIDERS:
        results += provider(db, q, ql, toks, want)
    results.sort(key=lambda r: (-r["score"], r["title"]))
    return results[:limit]


SEARCH_PROVIDERS: list = []
