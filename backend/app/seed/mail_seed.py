"""Stage 10 seed: a year of captured email and calendar events, templates, exclusions, a prepared bulk send, unsubscribes, stars.

Messages go through the same capture service the API uses, so associations and last-contact updates are real."""
import random
from datetime import datetime, timedelta

from sqlalchemy import select

from ..models.core import Contact, Property
from ..models.mail import ExclusionRule, EmailTemplate, Star, Unsubscribe
from ..services import mail as svc
from .gen import pick, rnd

INBOUND = [("Re: {a}", "Thanks for reaching out. I'd be open to hearing what the property might trade for."), ("Question about {a}", "Can you send me recent comps for the area? We're deciding whether to hold through the loan maturity."),
           ("Re: Valuation request", "Please send over the BOV when it's ready. My partner wants to review before year end."), ("Rent roll for {a}", "Attached is the current rent roll. Two tenants are on month-to-month."),
           ("Re: Tour on Thursday", "Thursday works. I'll meet you at the property at 10."), ("Not ready to sell yet", "Appreciate the call. We're staying put until after the refinance.")]
OUTBOUND = [("Quick thought on {a}", "Jim here. Three similar buildings traded nearby in the last 90 days. Happy to walk you through them if useful."), ("Following up", "Wanted to circle back on our conversation. No pressure, just a short call when you have a minute."),
            ("Comps for {a}", "Sending over the comps we discussed. The two industrial deals in Anaheim set the high end."), ("New listing that fits your criteria", "We just launched a NNN retail asset I think fits what you're buying. Want the OM?")]


def seed(db, ctx):
    users = ctx["users"]
    brokers = [u for u in users if u.role in ("admin", "manager", "broker")]
    for u in brokers:
        svc.get_connection(db, u)
    contacts = [c for c in db.scalars(select(Contact).where(Contact.deleted_at.is_(None))) if c.emails and not c.do_not_contact]
    props = {p.id: p for p in db.scalars(select(Property))}
    now = datetime.utcnow()
    rules = [("domain", "gmail-family.example"), ("address", "spouse@homemail.example"), ("keyword", "divorce"), ("keyword", "medical")]
    for u in brokers[:3]:
        for kind, value in rules[: 2 + (u.id % 3)]:
            db.add(ExclusionRule(user_id=u.id, kind=kind, value=value))
    templates = [
        ("New listing announcement", "New on the market: {{property_address}}, {{property_city}}", "Hi {{first_name}},\n\nWe just listed {{property_address}} at {{list_price}}. Given your interest in the area, I wanted you to see it first.\n\n{{broker_name}}"),
        ("Hold or sell check-in", "{{first_name}}, a quick thought on your property", "Hi {{first_name}},\n\nWith rates where they are, a few owners of similar assets are re-running the hold-versus-sell math. Happy to share what we're seeing. No pitch.\n\n{{broker_name}}"),
        ("Post-tour follow-up", "Great seeing you at {{property_address}}", "{{first_name}}, thanks for the time today. I'll send the comps and the rent roll summary tomorrow.\n\n{{broker_name}}"),
        ("Investor update", "1880 Capital: where we are", "Hi {{first_name}},\n\nA short update on deal flow and what's in the pipeline for {{company}}.\n\n{{broker_name}}"),
    ]
    tpls = []
    for name, s, b in templates:
        t = EmailTemplate(name=name, subject=s, body=b, owner_user_id=brokers[0].id)
        svc.validate_template(s, b)
        db.add(t)
        tpls.append(t)
    db.flush()
    stored = 0
    for i in range(150):
        c = random.choice(contacts)
        u = random.choice(brokers)
        addr = c.emails[0].email
        when = now - timedelta(days=rnd(1, 360), hours=rnd(0, 9))
        sub, body = random.choice(INBOUND if random.random() < 0.5 else OUTBOUND)
        out = (sub, body) in OUTBOUND
        a = random.choice(list(props.values())).address if props else "your property"
        conn = svc.get_connection(db, u)
        payload = {"from_addr": conn.email_address if out else addr, "to_addrs": [addr if out else conn.email_address], "subject": sub.format(a=a), "body": body, "sent_at": when,
                   "message_id": f"<seed-{i}@trg.local>", "thread_id": f"seed-thread-{c.id}"}
        if random.random() < 0.3:
            payload["visibility"] = pick(["team_metadata", "team_subject", "team_full"])
        if svc.capture_message(db, u, payload, channel=pick(["sync", "sync", "bcc"])).get("stored"):
            stored += 1
    for i in range(6):  # a few that match nobody, for the unlinked-triage queue
        u = random.choice(brokers)
        conn = svc.get_connection(db, u)
        svc.capture_message(db, u, {"from_addr": f"stranger{i}@newprospect.example", "to_addrs": [conn.email_address], "subject": "Saw your listing on LoopNet", "body": "Do you have details on the Brea industrial building?",
                                   "sent_at": now - timedelta(days=rnd(1, 20)), "message_id": f"<seed-unlinked-{i}@trg.local>"})
    titles = ["Property tour", "Owner coffee", "Listing presentation", "Buyer call", "Broker open house", "Lender lunch", "Investor update call", "Site walk with engineer", "Closing review"]
    for i in range(36):
        u = random.choice(brokers)
        conn = svc.get_connection(db, u)
        c = random.choice(contacts)
        start = now + timedelta(days=rnd(-300, 14), hours=rnd(8, 16))
        svc.capture_event(db, u, {"external_id": f"seed-evt-{i}", "title": pick(titles), "start": start, "end": start + timedelta(minutes=pick([30, 60, 90])), "location": pick(["On site", "Newport Beach office", "Coffee Bean, Irvine", "Zoom", "Costa Mesa"]),
                                  "attendees": [{"email": c.emails[0].email, "name": c.full_name}, {"email": conn.email_address}], "visibility": pick(["private", "team_metadata", "team_subject"])})
    # unsubscribes and a prepared (never sent) bulk send
    for c in random.sample(contacts, 4):
        db.add(Unsubscribe(email=svc.norm_email(c.emails[0].email), source="bulk email link", at=now - timedelta(days=rnd(2, 120))))
    db.flush()
    listing = next((l for l in ctx["listings"] if l.status == "active"), None)
    pool = random.sample(ctx["owner_contacts"], min(40, len(ctx["owner_contacts"])))
    svc.prepare_bulk(db, brokers[0], "Q4 owner outreach (prepared)", tpls[1], pool, None, None)
    if listing:
        svc.prepare_bulk(db, brokers[1], "Just listed: active retail", tpls[0], random.sample(contacts, 30), listing, None)
    for u in brokers[:3]:
        for c in random.sample(ctx["owner_contacts"], 3):
            db.add(Star(user_id=u.id, record_type="contact", record_id=c.id))
        for p in random.sample(list(props.values()), 3):
            db.add(Star(user_id=u.id, record_type="property", record_id=p.id))
    db.flush()
    ctx["emails_count"] = stored
