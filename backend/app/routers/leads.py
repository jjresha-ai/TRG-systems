import os
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..audit import current_actor
from ..db import get_db, utcnow
from ..models.core import Property
from ..models.core_sys import User
from ..models.pipeline import AssignmentRule, Campaign, Lead, LeadSource, TriggerRule, TRIGGER_KINDS, LEAD_STATUSES
from ..security import require
from ..services import prospecting as svc
from ..services.common import paginate, user_names

router = APIRouter(prefix="/api", tags=["prospecting"])


def lead_out(db: Session, l: Lead, names: dict) -> dict:
    p = l.property
    return {"id": l.id, "name": l.name, "company_name": l.company_name, "email": l.email, "phone": l.phone, "stream": l.stream, "status": l.status,
            "source": l.source.name if l.source else None, "source_id": l.source_id, "campaign_id": l.campaign_id,
            "score": l.score, "score_components": l.score_components, "owner_user_id": l.owner_user_id, "owner_name": names.get(l.owner_user_id),
            "property_id": l.property_id, "property": {"address": p.address, "city": p.city, "property_type": p.property_type, "estimated_value": p.estimated_value,
                                                       "loan_maturity_date": p.loan_maturity_date, "hold_intent": p.hold_intent} if p else None,
            "contact_id": l.contact_id, "company_id": l.company_id, "deal_id": l.deal_id, "trigger_reason": l.trigger_reason,
            "converted_at": l.converted_at, "conversion_outcome": l.conversion_outcome, "disqualify_reason": l.disqualify_reason,
            "created_at": l.created_at, "notes": l.notes}


class LeadIn(BaseModel):
    name: str = Field(min_length=1)
    company_name: str | None = None
    email: str | None = None
    phone: str | None = None
    stream: str = "seller"
    source_id: int | None = None
    campaign_id: int | None = None
    property_id: int | None = None
    owner_user_id: int | None = None
    notes: str | None = None


class LeadPatch(BaseModel):
    status: str | None = None
    owner_user_id: int | None = None
    notes: str | None = None
    disqualify_reason: str | None = None


class ConvertIn(BaseModel):
    contact_id: int | None = None
    company_id: int | None = None
    create_deal: bool = False


def _lead(db, lid) -> Lead:
    l = db.get(Lead, lid)
    if not l:
        raise HTTPException(404, "Lead not found")
    return l


@router.get("/leads")
def list_leads(property_id: int | None = None, status: str | None = None, source_id: int | None = None, owner_id: int | None = None, min_score: int | None = None, q: str | None = None,
               sort: str = "score", page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
               db: Session = Depends(get_db), _: User = Depends(require("view"))):
    stmt = select(Lead)
    if property_id:
        stmt = stmt.where(Lead.property_id == property_id)
    if status:
        stmt = stmt.where(Lead.status == status)
    if source_id:
        stmt = stmt.where(Lead.source_id == source_id)
    if owner_id:
        stmt = stmt.where(Lead.owner_user_id == owner_id)
    if min_score:
        stmt = stmt.where(Lead.score >= min_score)
    if q:
        stmt = stmt.where(Lead.name.ilike(f"%{q}%") | Lead.company_name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Lead.score.desc() if sort == "score" else Lead.created_at.desc(), Lead.id)
    items, total = paginate(db, stmt, page, limit)
    names = user_names(db)
    return {"items": [lead_out(db, l, names) for l in items], "total": total, "page": page, "limit": limit}


@router.post("/leads", status_code=201)
def create_lead(body: LeadIn, db: Session = Depends(get_db), user: User = Depends(require("create"))):
    if body.stream != "seller":
        raise HTTPException(422, "Buyer-side inquiries are recorded as buyer interest on a listing, not as leads")
    p = db.get(Property, body.property_id) if body.property_id else None
    if body.property_id and not p:
        raise HTTPException(422, "Unknown property")
    score, comp = svc.score_lead(db, p, [], None)
    l = Lead(**body.model_dump(), score=score, score_components=comp)
    l.owner_user_id = l.owner_user_id or svc.pick_assignee(db, p)
    db.add(l)
    db.commit()
    return lead_out(db, l, user_names(db))


@router.get("/leads/stats")
def lead_stats(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    by_status = {s: 0 for s in LEAD_STATUSES}
    for s, n in db.execute(select(Lead.status, func.count()).group_by(Lead.status)):
        by_status[s] = n
    rows = db.execute(select(LeadSource.id, LeadSource.name, func.count(Lead.id), func.sum(case((Lead.status == "converted", 1), else_=0)))
                      .join(Lead, Lead.source_id == LeadSource.id, isouter=True).group_by(LeadSource.id)).all()
    return {"by_status": by_status, "total": sum(by_status.values()),
            "by_source": [{"source_id": i, "source": n, "leads": c, "converted": int(v or 0), "conversion_rate": round((v or 0) / c * 100, 1) if c else 0} for i, n, c, v in rows]}


@router.get("/leads/{lid}")
def get_lead(lid: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return lead_out(db, _lead(db, lid), user_names(db))


@router.patch("/leads/{lid}")
def patch_lead(lid: int, body: LeadPatch, db: Session = Depends(get_db), _: User = Depends(require("edit"))):
    l = _lead(db, lid)
    d = body.model_dump(exclude_unset=True)
    if "status" in d:
        if d["status"] not in LEAD_STATUSES or d["status"] == "converted":
            raise HTTPException(422, "Use the convert endpoint to convert; status must be new, contacted, qualified or disqualified")
        if l.status == "converted":
            raise HTTPException(409, "Converted leads cannot change status")
        if d["status"] == "disqualified" and not (d.get("disqualify_reason") or l.disqualify_reason):
            raise HTTPException(422, "A disqualify reason is required")
    for k, v in d.items():
        setattr(l, k, v)
    db.commit()
    return lead_out(db, l, user_names(db))


@router.post("/leads/{lid}/convert")
def convert(lid: int, body: ConvertIn, db: Session = Depends(get_db), user: User = Depends(require("edit"))):
    l = _lead(db, lid)
    r = svc.convert_lead(db, l, body.model_dump(), user.id)
    db.commit()
    return r


# ---- public web form capture (API key, no user session) ----
class WebFormIn(BaseModel):
    name: str = Field(min_length=1)
    email: str | None = None
    phone: str | None = None
    company_name: str | None = None
    property_address: str | None = None
    message: str | None = None
    campaign: str | None = None


@router.post("/public/leads", status_code=201, tags=["public"])
def web_form(body: WebFormIn, x_form_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    if x_form_key != os.environ.get("TRG_FORM_KEY", "dev-form-key"):
        raise HTTPException(401, "Invalid form key")
    if not (body.email or body.phone):
        raise HTTPException(422, "Email or phone is required")
    src = db.scalar(select(LeadSource).where(LeadSource.name == "Web form"))
    if not src:
        src = LeadSource(name="Web form")
        db.add(src)
        db.flush()
    camp = db.scalar(select(Campaign).where(Campaign.name == body.campaign)) if body.campaign else None
    current_actor.set("web form")
    l = Lead(name=body.name, email=body.email, phone=body.phone, company_name=body.company_name, source_id=src.id, campaign_id=camp.id if camp else None,
             notes=" | ".join(x for x in [body.property_address, body.message] if x) or None, score=10, score_components={"inbound web inquiry": 10})
    l.owner_user_id = svc.pick_assignee(db, None)
    db.add(l)
    db.commit()
    return {"id": l.id, "status": "received"}


# ---- sources, campaigns, rules ----
class SourceIn(BaseModel):
    name: str = Field(min_length=1)


@router.get("/lead-sources")
def sources(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return [{"id": s.id, "name": s.name, "active": s.active} for s in db.scalars(select(LeadSource).order_by(LeadSource.name))]


@router.post("/lead-sources", status_code=201)
def add_source(body: SourceIn, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    if db.scalar(select(LeadSource).where(LeadSource.name == body.name)):
        raise HTTPException(409, "Source exists")
    s = LeadSource(name=body.name)
    db.add(s)
    db.commit()
    return {"id": s.id, "name": s.name}


@router.get("/campaigns")
def campaigns(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    out = []
    for c in db.scalars(select(Campaign).order_by(Campaign.id)):
        leads = db.scalars(select(Lead).where(Lead.campaign_id == c.id)).all()
        out.append({"id": c.id, "name": c.name, "description": c.description, "started_on": c.started_on, "leads": len(leads), "converted": sum(1 for l in leads if l.status == "converted")})
    return out


class TriggerIn(BaseModel):
    name: str
    kind: str
    threshold: int = Field(gt=0)
    property_type: str | None = None
    enabled: bool = True


@router.get("/trigger-rules")
def trigger_rules(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return [{"id": r.id, "name": r.name, "kind": r.kind, "threshold": r.threshold, "property_type": r.property_type, "enabled": r.enabled}
            for r in db.scalars(select(TriggerRule).order_by(TriggerRule.id))]


@router.post("/trigger-rules", status_code=201)
def add_trigger_rule(body: TriggerIn, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    if body.kind not in TRIGGER_KINDS:
        raise HTTPException(422, f"kind must be one of {TRIGGER_KINDS}")
    r = TriggerRule(**body.model_dump())
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.patch("/trigger-rules/{rid}")
def patch_trigger_rule(rid: int, body: dict, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    r = db.get(TriggerRule, rid)
    if not r:
        raise HTTPException(404, "Not found")
    for k in ("enabled", "threshold", "name"):
        if k in body:
            setattr(r, k, body[k])
    db.commit()
    return {"id": r.id, "enabled": r.enabled, "threshold": r.threshold}


class AssignIn(BaseModel):
    name: str
    priority: int = 100
    property_type: str | None = None
    market: str | None = None
    strategy: str = "fixed"
    user_ids: list[int]


@router.get("/assignment-rules")
def assignment_rules(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    names = user_names(db)
    return [{"id": r.id, "name": r.name, "priority": r.priority, "property_type": r.property_type, "market": r.market, "strategy": r.strategy,
             "users": [names.get(u) for u in r.user_ids], "enabled": r.enabled} for r in db.scalars(select(AssignmentRule).order_by(AssignmentRule.priority))]


@router.post("/assignment-rules", status_code=201)
def add_assignment_rule(body: AssignIn, db: Session = Depends(get_db), _: User = Depends(require("delete"))):
    if body.strategy not in ("fixed", "round_robin"):
        raise HTTPException(422, "strategy must be fixed or round_robin")
    for u in body.user_ids:
        if not db.get(User, u):
            raise HTTPException(422, f"Unknown user {u}")
    r = AssignmentRule(**body.model_dump())
    db.add(r)
    db.commit()
    return {"id": r.id}
