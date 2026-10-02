"""Owner prospecting (ADR 0007): trigger evaluation, additive scoring, assignment, conversion."""
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models.core import Company, Contact, ContactCompanyRole, Property, PropertyOwnership
from ..models.core_sys import User
from ..models.pipeline import AssignmentRule, Lead, LeadSource, Listing, TriggerRule
from . import dedupe
from .common import add_months, years_between
from .jobs import job
from .normalize import norm_company_name

DEAL_CREATOR = None  # set by the deals stage: fn(db, lead, contact, company, user_id) -> deal id


def current_ownerships(db: Session, property_id: int):
    return db.scalars(select(PropertyOwnership).where(PropertyOwnership.property_id == property_id, PropertyOwnership.disposed_date.is_(None))).all()


def hold_years_of(db: Session, p: Property, today: date) -> float | None:
    ds = [o.acquired_date for o in current_ownerships(db, p.id) if o.acquired_date]
    return years_between(min(ds), today) if ds else None


def property_triggers(db: Session, p: Property, rules: list[TriggerRule], today: date | None = None) -> list[dict]:
    """Which enabled rules match this property now, with the facts that matched."""
    today = today or date.today()
    out = []
    for r in rules:
        if not r.enabled or (r.property_type and r.property_type != p.property_type):
            continue
        if r.kind == "hold_years":
            y = hold_years_of(db, p, today)
            if y is not None and y >= r.threshold:
                out.append({"rule_id": r.id, "rule": r.name, "kind": r.kind, "detail": f"Held {y} years (threshold {r.threshold})"})
        elif r.kind == "loan_maturity":
            m = p.loan_maturity_date
            if m and add_months(today, -6) <= m <= add_months(today, r.threshold):
                out.append({"rule_id": r.id, "rule": r.name, "kind": r.kind, "detail": f"Loan ({p.lender or 'lender n/a'}) matures {m.isoformat()}"})
        elif r.kind == "ownership_change":
            cutoff = add_months(today, -r.threshold)
            for o in current_ownerships(db, p.id):
                prior = db.scalar(select(PropertyOwnership).where(PropertyOwnership.property_id == p.id, PropertyOwnership.disposed_date.is_not(None)))
                if o.acquired_date and o.acquired_date >= cutoff and prior:
                    out.append({"rule_id": r.id, "rule": r.name, "kind": r.kind, "detail": f"Ownership changed {o.acquired_date.isoformat()}"})
                    break
    return out


def score_lead(db: Session, p: Property | None, matches: list[dict], last_contact: datetime | None, today: date | None = None) -> tuple[int, dict]:
    """Transparent additive score; components are stored with the lead (no black box)."""
    today = today or date.today()
    comp: dict[str, int] = {}
    if matches:
        comp["trigger matches"] = min(20 * len(matches), 40)
    if p:
        y = hold_years_of(db, p, today)
        if y is not None:
            comp["hold period"] = 15 if y >= 10 else 10 if y >= 7 else 0
        if p.loan_maturity_date:
            mo = (p.loan_maturity_date - today).days / 30.44
            comp["loan maturity"] = 25 if mo <= 12 else 15 if mo <= 24 else 0
        comp["stated intent"] = {"selling_soon": 30, "open_to_sell": 20}.get(p.hold_intent, 0)
        fit = (10 if (p.estimated_value or 0) >= 3_000_000 else 5) + (5 if p.market == "Orange County" else 0)
        comp["property fit"] = fit
    if last_contact:
        d = (utcnow() - last_contact).days
        comp["contact recency"] = 10 if d <= 30 else 5 if d <= 90 else 0
    else:
        comp["contact recency"] = 0
    comp = {k: v for k, v in comp.items() if v}
    return min(sum(comp.values()), 100), comp


def pick_assignee(db: Session, p: Property | None) -> int | None:
    rules = db.scalars(select(AssignmentRule).where(AssignmentRule.enabled.is_(True)).order_by(AssignmentRule.priority, AssignmentRule.id)).all()
    for r in rules:
        if r.property_type and (not p or r.property_type != p.property_type):
            continue
        if r.market and (not p or r.market != p.market):
            continue
        if not r.user_ids:
            continue
        if r.strategy == "round_robin":
            uid = r.user_ids[r.counter % len(r.user_ids)]
            r.counter += 1
            return uid
        return r.user_ids[0]
    brokers = db.scalars(select(User).where(User.role.in_(["broker", "admin"]), User.active.is_(True)).order_by(User.id)).all()
    if not brokers:
        return None
    total = db.scalar(select(func.count()).select_from(Lead)) or 0
    return brokers[total % len(brokers)].id


def primary_principal(db: Session, p: Property):
    for o in current_ownerships(db, p.id):
        if o.company_id:
            role = db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.company_id == o.company_id, ContactCompanyRole.end_date.is_(None))
                              .order_by(ContactCompanyRole.is_primary.desc(), ContactCompanyRole.id)).first()
            if role:
                return role.contact, o.company
            return None, o.company
        if o.contact:
            return o.contact, None
    return None, None


def evaluate_triggers(db: Session, today: date | None = None) -> dict:
    """Idempotent: one lead per property; extra matching rules add reasons to it. Never for properties already being listed."""
    today = today or date.today()
    rules = db.scalars(select(TriggerRule).where(TriggerRule.enabled.is_(True))).all()
    src = db.scalar(select(LeadSource).where(LeadSource.name == "Hold/Sell Trigger"))
    if not src:
        src = LeadSource(name="Hold/Sell Trigger")
        db.add(src)
        db.flush()
    created = reasons_added = skipped = 0
    busy = {l.property_id for l in db.scalars(select(Listing).where(Listing.status.in_(["prospect", "active", "under_contract"])))}
    for p in db.scalars(select(Property).where(Property.deleted_at.is_(None))):
        matches = property_triggers(db, p, rules, today)
        if not matches or p.id in busy:
            continue
        leads = db.scalars(select(Lead).where(Lead.property_id == p.id, Lead.trigger_key.is_not(None))).all()
        handled = {l.trigger_key for l in leads} | {k for l in leads for k in (l.trigger_reason or {}).get("keys", [])}
        open_lead = next((l for l in leads if l.status in ("new", "contacted", "qualified")), None)
        for m in matches:
            key = f"{m['rule_id']}:{p.id}"
            if key in handled:
                skipped += 1
                continue
            handled.add(key)
            if open_lead:
                tr = dict(open_lead.trigger_reason or {"matches": [], "keys": []})
                tr["matches"] = tr.get("matches", []) + [m]
                tr["keys"] = tr.get("keys", []) + [key]
                open_lead.trigger_reason = tr
                open_lead.score, open_lead.score_components = score_lead(db, p, tr["matches"], open_lead.last_contact_at, today)
                reasons_added += 1
                continue
            contact, company = primary_principal(db, p)
            score, comp = score_lead(db, p, [m], p.last_contact_at, today)
            lead = Lead(name=contact.full_name if contact else (company.name if company else "Unknown owner"),
                        company_name=company.name if company else None, stream="seller", status="new", source_id=src.id,
                        score=score, score_components=comp, owner_user_id=pick_assignee(db, p), property_id=p.id,
                        contact_id=contact.id if contact else None, company_id=company.id if company else None,
                        trigger_key=key, trigger_reason={"matches": [m], "keys": [key]}, last_contact_at=p.last_contact_at)
            if contact and contact.emails:
                lead.email = contact.emails[0].email
            if contact and contact.phones:
                lead.phone = contact.phones[0].phone
            db.add(lead)
            db.flush()
            open_lead = lead
            created += 1
    db.flush()
    return {"leads_created": created, "reasons_added": reasons_added, "already_handled": skipped}


@job("hold_sell_triggers", "Evaluate hold-period, loan-maturity and ownership-change rules and create seller leads")
def _job_triggers(db):
    r = evaluate_triggers(db)
    return r


@job("duplicate_scan", "Scan contacts, companies and properties for possible duplicates")
def _job_dupes(db):
    return dedupe.scan_all(db)


def convert_lead(db: Session, lead: Lead, body: dict, user_id: int) -> dict:
    if lead.status == "converted":
        raise HTTPException(409, "Lead already converted")
    if lead.status == "disqualified":
        raise HTTPException(409, "Lead is disqualified")
    from . import entities
    contact = company = None
    linked = {"contact": False, "company": False}
    if body.get("contact_id"):
        contact = db.get(Contact, body["contact_id"])
        if not contact or contact.deleted_at:
            raise HTTPException(422, "Unknown contact")
        linked["contact"] = True
    elif lead.contact_id:
        contact, linked["contact"] = db.get(Contact, lead.contact_id), True
    else:
        first, _, last = lead.name.partition(" ")
        data = {"first_name": first, "last_name": last or "(unknown)", "contact_types": ["owner"], "source": "lead conversion",
                "emails": [{"email": lead.email}] if lead.email else [], "phones": [{"phone": lead.phone}] if lead.phone else [], "lifecycle_stage": "prospect"}
        d, _ = dedupe.contact_matches(db, [e["email"] for e in data["emails"]], [p["phone"] for p in data["phones"]], first, last)
        if d:
            contact, linked["contact"] = list(d.values())[0][0], True
        else:
            contact = entities.create_contact(db, data, user_id)
    if body.get("company_id"):
        company = db.get(Company, body["company_id"])
        if not company:
            raise HTTPException(422, "Unknown company")
        linked["company"] = True
    elif lead.company_id:
        company, linked["company"] = db.get(Company, lead.company_id), True
    elif lead.company_name:
        d, _ = dedupe.company_matches(db, lead.company_name)
        if d:
            company, linked["company"] = list(d.values())[0][0], True
        else:
            company = entities.create_company(db, {"name": lead.company_name, "kind": "llc", "source": "lead conversion"}, user_id)
    db.flush()
    if contact and company and not db.scalar(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == contact.id, ContactCompanyRole.company_id == company.id)):
        db.add(ContactCompanyRole(contact_id=contact.id, company_id=company.id, role="principal", is_primary=True))
    deal_id = None
    if body.get("create_deal"):
        if DEAL_CREATOR is None:
            raise HTTPException(501, "Deals are not available yet")
        deal_id = DEAL_CREATOR(db, lead, contact, company, user_id)
    lead.contact_id, lead.company_id = contact.id if contact else None, company.id if company else None
    lead.status, lead.converted_at, lead.conversion_outcome, lead.deal_id = "converted", utcnow(), "deal" if deal_id else "contact", deal_id
    db.flush()
    return {"lead_id": lead.id, "contact_id": lead.contact_id, "company_id": lead.company_id, "deal_id": deal_id, "linked_existing": linked}
