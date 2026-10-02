"""Stage 9 seed: workflow rules (run for real over the seeded data), an API token, and a year of audit history derived from the seeded records."""
import hashlib
import random
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import select

from ..models.core import Company, Contact, Property
from ..models.core_sys import AuditEvent
from ..models.deals import Deal, DealStageHistory, Stage
from ..models.investors import Commitment, Fund, InvestorProfile
from ..models.pipeline import Lead, Listing
from ..models.security import ApiToken, Rule
from ..models.work import CadenceTemplate, Document
from ..services import rules as rules_svc
from .gen import pick, rnd

F = lambda *a: {"field": a[0], "operator": a[1], **({"value": a[2]} if len(a) > 2 else {})}  # noqa: E731
G = lambda op, *c: {"op": op, "conditions": list(c)}  # noqa: E731


def seed(db, ctx):
    users = ctx["users"]
    jim, maria, kevin, dana, tyler = users[:5]
    cad = {c.name: c for c in db.scalars(select(CadenceTemplate))}
    rules = [
        Rule(name="Loan maturity: 6-month alert", description="Six months before a loan matures, open the refinance-or-sell conversation", entity="property", trigger_type="date_reached",
             trigger_config={"date_field": "loan_maturity_date", "offset_days": -180, "grace_days": 180}, owner_user_id=jim.id,
             actions=[{"type": "create_task", "params": {"subject": "Loan matures in ~6 months: raise refinance-or-sell at {name}", "days_due": 3, "type": "call", "priority": "high"}},
                      {"type": "notify", "params": {"message": "Loan maturity approaching: {name}"}}]),
        Rule(name="Hot seller: owner says selling soon", description="When a property's hold intent becomes 'selling soon', create a seller lead and a same-day call", entity="property", trigger_type="field_changed",
             trigger_config={"field": "hold_intent", "to": "selling_soon"}, owner_user_id=jim.id,
             actions=[{"type": "create_lead", "params": {}}, {"type": "create_task", "params": {"subject": "Call the owner of {name} today", "days_due": 0, "type": "call", "priority": "high"}}, {"type": "notify", "params": {"message": "{name} is now selling soon"}}]),
        Rule(name="Under contract: closing checklist", description="Title, escrow and lender follow-ups when a deal goes under contract", entity="deal", trigger_type="stage_changed", trigger_config={"to_stage": "under_contract"}, owner_user_id=maria.id,
             actions=[{"type": "create_task", "params": {"subject": "Open escrow and order title: {name}", "days_due": 1, "type": "other"}}, {"type": "create_task", "params": {"subject": "Confirm lender and appraisal timeline: {name}", "days_due": 3, "type": "call"}}]),
        Rule(name="New investor: tour follow-up cadence", description="Every new investor contact gets the buyer follow-up cadence", entity="contact", trigger_type="record_created", conditions=G("and", F("contact_types", "contains", "investor")),
             trigger_config={}, owner_user_id=tyler.id, actions=[{"type": "apply_cadence", "params": {"cadence_id": cad["Buyer follow-up after tour"].id}}]),
        Rule(name="Owner untouched 120 days: re-engage", description="Owners nobody has spoken to in 120+ days get a re-engagement call (respects do-not-contact)", entity="contact", trigger_type="scheduled", trigger_config={"cooldown_days": 90}, owner_user_id=jim.id,
             conditions=G("and", F("contact_types", "contains", "owner"), G("or", F("last_contact_at", "older_than_days", 120), F("last_contact_at", "is_null"))),
             actions=[{"type": "create_task", "params": {"subject": "Re-engage {name}: no contact in 120+ days", "days_due": 2, "type": "call"}}]),
        Rule(name="Listing expires in 45 days: renewal conversation", description="Start the renewal or reprice conversation early", entity="listing", trigger_type="date_reached", trigger_config={"date_field": "expiration_date", "offset_days": -45, "grace_days": 45},
             conditions=G("and", F("status", "eq", "active")), owner_user_id=kevin.id,
             actions=[{"type": "create_task", "params": {"subject": "Listing expiring: renewal or reprice conversation for {name}", "days_due": 1, "type": "meeting", "priority": "high"}}, {"type": "notify", "params": {"message": "Listing expiring soon: {name}"}}]),
    ]
    db.add_all(rules)
    db.flush()
    # run the scan rules for real (events-based rules react to future changes)
    for r in rules:
        if r.trigger_type in ("date_reached", "scheduled"):
            rules_svc.evaluate_scan_rule(db, r)
    rules_svc.set_cursor(db, 10**9)  # historical seed events are not replayed through event rules
    db.flush()
    # an API token for an integration (shown once at creation; only the hash is stored)
    secret = f"trg_seed0001_{secrets.token_urlsafe(24)}"
    db.add(ApiToken(user_id=tyler.id, name="Zapier: web form to lead", prefix="seed0001", token_hash=hashlib.sha256(secret.encode()).hexdigest(), scopes=["view", "create"],
                    expires_at=datetime.utcnow() + timedelta(days=200), last_used_at=datetime.utcnow() - timedelta(hours=5), created_at=datetime.utcnow() - timedelta(days=60)))
    # ---------------- audit history (derived from the seeded records) ----------------
    names = {u.id: u.name for u in users}
    ev: list[AuditEvent] = []

    def add(ts, actor_id, action, etype, eid, changes=None):
        ev.append(AuditEvent(timestamp=ts, actor=names.get(actor_id, "system"), actor_user_id=actor_id, action=action, entity_type=etype, entity_id=eid, changes=changes or {}))

    def key(o, *fields):
        return {f: [None, getattr(o, f)] for f in fields if getattr(o, f, None) is not None}

    for c in ctx["all_contacts"]:
        add(c.created_at, c.owner_user_id, "create", "contacts", c.id, key(c, "full_name", "title", "lifecycle_stage"))
    for co in db.scalars(select(Company)):
        add(co.created_at, co.owner_user_id, "create", "companies", co.id, key(co, "name", "kind"))
    for p in ctx["properties"]:
        add(p.created_at, p.owner_user_id, "create", "properties", p.id, key(p, "address", "city", "property_type", "estimated_value"))
        if p.hold_intent in ("open_to_sell", "selling_soon") and random.random() < 0.5:
            add(p.created_at + timedelta(days=rnd(5, 150)), p.owner_user_id, "update", "properties", p.id, {"hold_intent": ["unknown", p.hold_intent]})
    for l in ctx["listings"]:
        add(l.created_at, l.owner_user_id, "create", "listings", l.id, key(l, "property_id", "status", "list_price"))
        if l.status != "prospect":
            add(l.created_at + timedelta(days=rnd(1, 14)), l.owner_user_id, "update", "listings", l.id, {"status": ["prospect", "active"], "list_price": [None, l.list_price]})
        if random.random() < 0.3 and l.list_price:
            add(l.created_at + timedelta(days=rnd(30, 120)), l.owner_user_id, "update", "listings", l.id, {"list_price": [int(l.list_price * 1.04), l.list_price]})
    stages = {s.id: s for s in db.scalars(select(Stage))}
    for d in db.scalars(select(Deal)):
        add(d.created_at, d.owner_user_id, "create", "deals", d.id, key(d, "name", "price", "status"))
        hist = db.scalars(select(DealStageHistory).where(DealStageHistory.deal_id == d.id).order_by(DealStageHistory.at, DealStageHistory.id)).all()
        for h in hist[1:]:
            add(h.at, h.user_id or d.owner_user_id, "update", "deals", d.id, {"stage_id": [h.from_stage_id, h.to_stage_id]})
        if d.price and random.random() < 0.28:
            add(d.created_at + timedelta(days=rnd(7, 90)), d.owner_user_id, "update", "deals", d.id, {"price": [int(d.price * random.uniform(1.03, 1.12)), d.price]})
        if random.random() < 0.06:
            add(d.created_at + timedelta(days=rnd(7, 60)), maria.id, "ownership_transfer", "deals", d.id, {"from": kevin.id, "to": d.owner_user_id})
        if d.gross_commission is not None or d.commission_rate_bps:
            add(d.created_at + timedelta(days=1), d.owner_user_id, "update", "deals", d.id, {"commission_rate_bps": ["changed", "changed"]})
    for lead in db.scalars(select(Lead)):
        add(lead.created_at, lead.owner_user_id, "create", "leads", lead.id, key(lead, "name", "status", "score"))
    for ip in db.scalars(select(InvestorProfile)):
        add(ip.created_at, ip.owner_user_id, "create", "investor_profiles", ip.id, {})
        add(ip.created_at + timedelta(days=rnd(1, 20)), ip.owner_user_id, "view_investor_profile", "investor_profiles", ip.id)
        add(ip.created_at + timedelta(days=rnd(1, 10)), ip.owner_user_id, "update", "investor_profiles", ip.id, {"accreditation_status": ["changed", "changed"]})
    for cm in db.scalars(select(Commitment)):
        add(datetime.combine(cm.interested_on or date.today(), datetime.min.time()) + timedelta(hours=11), tyler.id, "create", "commitments", cm.id, {"amount": [None, cm.amount], "status": [None, "interested"]})
        if cm.status != "interested":
            add(datetime.combine(cm.committed_on or cm.soft_circled_on or cm.interested_on, datetime.min.time()) + timedelta(hours=15), tyler.id, "update", "commitments", cm.id, {"status": ["interested", cm.status]})
    for f in db.scalars(select(Fund)):
        add(datetime.combine(f.opened_on or date.today(), datetime.min.time()) + timedelta(hours=9), jim.id, "create", "funds", f.id, {"name": [None, f.name]})
    # sign-ins: each user on most weekdays across the year
    today = date.today()
    for u in users:
        for back in range(0, 365):
            d = today - timedelta(days=back)
            if d.weekday() < 5 and random.random() < 0.72:
                add(datetime.combine(d, datetime.min.time()) + timedelta(hours=rnd(6, 9), minutes=rnd(0, 59)), u.id, "login", "users", u.id, {"email": u.email})
    for _ in range(14):
        add(datetime.utcnow() - timedelta(days=rnd(1, 300), hours=rnd(0, 9)), None, "login_failed", "users", None, {"email": pick(["jim@resha.group", "kevin@resha.group", "admin@resha.group", "dana@resha.group"])})
    # exports, document downloads, role changes, API token use
    for _ in range(16):
        u = pick([jim, maria, kevin, dana])
        add(datetime.utcnow() - timedelta(days=rnd(1, 330), hours=rnd(0, 8)), u.id, "export", pick(["contact", "property", "listing", "deal", "reports"]), None, {"rows": rnd(20, 400), "format": pick(["csv", "xlsx"])})
    for d in db.scalars(select(Document).where(Document.visibility == "confidential").limit(24)):
        u = pick([jim, maria, kevin, dana])
        add(d.created_at + timedelta(days=rnd(0, 40)), u.id, "document_download", "documents", d.id, {"file": d.file_name, "version": d.version})
    add(datetime.utcnow() - timedelta(days=210), jim.id, "role_change", "users", dana.id, {"from": "assistant", "to": "broker", "by": jim.name})
    add(datetime.utcnow() - timedelta(days=95), jim.id, "role_change", "users", maria.id, {"from": "broker", "to": "manager", "by": jim.name})
    for _ in range(40):
        add(datetime.utcnow() - timedelta(hours=rnd(1, 24 * 40)), tyler.id, "api_token_use", "api_tokens", 1, {"method": "POST", "path": "/api/public/leads"})
    ev.sort(key=lambda e: e.timestamp)
    db.add_all(ev)
    db.flush()
