"""Stage 2 seed: lead sources, campaigns, rules, leads, listings, buyer interest."""
import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from ..models.core import Company, Contact, Property, PropertyOwnership
from ..models.pipeline import (AssignmentRule, BuyerInterest, BuyerInterestEvent, Campaign, Lead, LeadSource, Listing, ListingBroker, TriggerRule)
from ..services import prospecting
from .gen import dt_last_year, pick, rnd


def seed(db, ctx):
    today = date.today()
    users = ctx["users"]
    brokers = ctx["brokers"]
    src_names = ["Cold call list", "Referral", "CoStar export", "Past client", "Industry event", "Web form", "Sperry network", "LinkedIn outreach", "Direct mail"]
    sources = {n: LeadSource(name=n) for n in src_names}
    sources["Hold/Sell Trigger"] = LeadSource(name="Hold/Sell Trigger")
    db.add_all(sources.values())
    db.flush()
    camps = []
    for name, src, desc in [("2026 Q1 Industrial Owners: Loan Maturity", "Direct mail", "Letter + call to IE/LA industrial owners with 2026-27 maturities"),
                            ("OC Retail Long-Hold Owners", "Cold call list", "Owners of OC retail held 15+ years"),
                            ("Trust & Estate Owners", "Referral", "Estate attorneys and CPAs referral campaign"),
                            ("1031 Buyer Roundup", "Industry event", "Buyer-side database build"),
                            ("Website: What's My Property Worth", "Web form", "Inbound valuation landing page")]:
        c = Campaign(name=name, source_id=sources[src].id, description=desc, started_on=today - timedelta(days=rnd(60, 330)))
        db.add(c)
        camps.append(c)
    jim, maria, kevin, dana, tyler = users[0], users[1], users[2], users[3], users[4]
    db.add_all([TriggerRule(name="Long hold: 15+ years", kind="hold_years", threshold=15), TriggerRule(name="Loan matures within 12 months", kind="loan_maturity", threshold=12),
                TriggerRule(name="Ownership change in last 18 months", kind="ownership_change", threshold=18),
                TriggerRule(name="Retail held 12+ years", kind="hold_years", threshold=12, property_type="retail", enabled=False)])
    db.add_all([AssignmentRule(name="Industrial: Kevin", priority=10, property_type="industrial", strategy="fixed", user_ids=[kevin.id]),
                AssignmentRule(name="Retail: Dana & Jim round-robin", priority=20, property_type="retail", strategy="round_robin", user_ids=[dana.id, jim.id])])
    db.flush()
    # trigger-generated seller leads (real evaluation over seeded property/ownership/debt data)
    prospecting.evaluate_triggers(db, today)
    trig = db.scalars(select(Lead)).all()
    # spread statuses and dates like a year of working them
    for l in trig:
        l.created_at = l.updated_at = dt_last_year()
        r = random.random()
        l.status = "new" if r < 0.5 else "contacted" if r < 0.78 else "qualified" if r < 0.9 else "disqualified"
        if l.status == "disqualified":
            l.disqualify_reason = pick(["Not selling: long-term hold", "Owner passed away: estate not ready", "Already listed with another broker", "Wrong decision-maker"])
        if l.status in ("contacted", "qualified"):
            l.last_contact_at = datetime.combine(today - timedelta(days=rnd(2, 120)), datetime.min.time())
    # manually sourced seller leads
    contacts = ctx["owner_contacts"]
    props = ctx["properties"]
    n_manual = 80
    for i in range(n_manual):
        c = pick(contacts)
        src = pick(src_names)
        p = pick(props) if random.random() < 0.8 else None
        camp = pick(camps) if random.random() < 0.55 else None
        st = random.choices(["new", "contacted", "qualified", "converted", "disqualified"], weights=[22, 30, 18, 14, 16])[0]
        score, comp = prospecting.score_lead(db, p, [], None, today)
        l = Lead(name=c.full_name, company_name=None, email=c.emails[0].email if c.emails else None, phone=c.phones[0].phone if c.phones else None,
                 stream="seller", status=st, source_id=sources[src].id, campaign_id=camp.id if camp else None, score=score, score_components=comp,
                 owner_user_id=pick(brokers).id, property_id=p.id if p else None, contact_id=c.id if st == "converted" else None, created_at=dt_last_year(),
                 notes=pick(["Called, will revisit after refi", "Interested in valuation", "Referred by estate attorney", "Met at CREW event", "Asked for broker opinion of value", None]))
        l.updated_at = l.created_at
        if st == "converted":
            l.converted_at = l.created_at + timedelta(days=rnd(5, 60))
            l.conversion_outcome = "deal" if random.random() < 0.6 else "contact"
        if st == "disqualified":
            l.disqualify_reason = pick(["Not selling", "Listed elsewhere", "Unresponsive after 6 touches", "Wrong market"])
        db.add(l)
    db.flush()
    # ---------- listings ----------
    all_props = list(props)
    random.shuffle(all_props)
    plan = [("prospect", 14), ("active", 24), ("under_contract", 8), ("closed", 20), ("expired", 5), ("withdrawn", 3)]
    listings = []
    ctx["listings_by_status"] = {}
    idx = 0
    for status, n in plan:
        for _ in range(n):
            p = all_props[idx]
            idx += 1
            contact, company = prospecting.primary_principal(db, p)
            price = int((p.estimated_value or 4_000_000) * random.uniform(0.95, 1.1)) // 25000 * 25000
            bps = pick([200, 250, 250, 300, 300, 350])
            lead_b = pick(brokers)
            if status == "prospect":
                agreement = exp = active = closed = None
                created = dt_last_year()
            elif status == "closed":
                closed = today - timedelta(days=rnd(7, 340))
                active = closed - timedelta(days=rnd(75, 240))
                agreement = active - timedelta(days=rnd(3, 21))
                exp = agreement + timedelta(days=pick([180, 270, 365]))
                created = datetime.combine(agreement, datetime.min.time())
            else:
                active = today - timedelta(days=rnd(10, 230))
                agreement = active - timedelta(days=rnd(3, 21))
                exp = agreement + timedelta(days=pick([180, 270, 365]))
                if status == "active" and exp < today:
                    exp = today + timedelta(days=rnd(10, 120))
                if status == "active" and random.random() < 0.3:
                    exp = today + timedelta(days=rnd(5, 55))  # expiring soon: listing-renewal calls
                if status == "expired":
                    exp = today - timedelta(days=rnd(3, 120))
                    active = exp - timedelta(days=rnd(180, 330))
                    agreement = active - timedelta(days=5)
                closed = None
                created = datetime.combine(agreement, datetime.min.time())
            l = Listing(property_id=p.id, seller_contact_id=contact.id if contact else None, seller_company_id=company.id if company else None,
                        listing_type="sale", status=status, list_price=price if status != "prospect" or random.random() < 0.5 else None,
                        sold_price=int(price * random.uniform(0.9, 1.0)) // 5000 * 5000 if status == "closed" else None,
                        commission_rate_bps=bps, commission_terms=pick(["Full commission; co-op 50% to buyer's broker", "3% first $5M, 2% thereafter", "Flat fee + success bonus", None]),
                        agreement_date=agreement, expiration_date=exp, active_date=active, closed_date=closed, owner_user_id=lead_b.id,
                        confidential=random.random() < 0.1, source=pick(["Trigger lead", "Referral", "Past client", "Cold call"]), created_at=created, updated_at=created, tags=[], custom={})
            l.brokers.append(ListingBroker(user_id=lead_b.id, role="lead", split_pct=100 if random.random() < 0.6 else 60))
            if l.brokers[0].split_pct == 60:
                l.brokers.append(ListingBroker(user_id=pick([b for b in brokers if b.id != lead_b.id]).id, role="co-list", split_pct=40))
            db.add(l)
            listings.append(l)
            ctx["listings_by_status"].setdefault(status, []).append(l)
            if status in ("prospect", "active", "under_contract"):
                p.hold_intent = "selling_soon"
                p.pricing_expectation = price
    db.flush()
    # ---------- buyer interest ----------
    buyers = ctx["buyer_contacts"] + ctx["inv_contacts"]
    stages = ["inquiry", "ca_sent", "ca_signed", "om_sent", "tour", "offer"]
    n_interest = 0
    for l in listings:
        if l.status in ("prospect", "expired", "withdrawn") and random.random() < 0.7:
            continue
        k = rnd(4, 11) if l.status in ("active", "under_contract", "closed") else rnd(1, 3)
        for b in random.sample(buyers, min(k, len(buyers))):
            if b.do_not_contact:
                continue
            depth = random.choices(range(7), weights=[22, 14, 18, 14, 14, 10, 8])[0]  # 6 = declined after some depth
            end = l.closed_date or today
            start = l.active_date or (end - timedelta(days=30))
            span = max((end - start).days, 1)
            t = datetime.combine(start, datetime.min.time()) + timedelta(days=rnd(0, max(span - 1, 0)), hours=rnd(8, 17))
            i = BuyerInterest(listing_id=l.id, contact_id=b.id, channel=pick(["email", "form", "manual", "email"]), stage="inquiry")
            final = "declined" if depth == 6 else stages[min(depth, 5)]
            reach = stages[: (rnd(1, 5) if depth == 6 else depth + 1)]
            for s in reach:
                i.events.append(BuyerInterestEvent(stage=s, at=t, user_id=l.owner_user_id, note=None, amount=None))
                t += timedelta(days=rnd(1, 9), hours=rnd(0, 6))
            i.stage = reach[-1]
            if depth == 6:
                i.events.append(BuyerInterestEvent(stage="declined", at=t, user_id=l.owner_user_id, note="Pricing / cap rate"))
                i.stage, i.declined_reason = "declined", pick(["Pricing too high", "Cap rate below target", "Found another deal", "Timing / 1031 deadline", "Lender financing fell through"])
            if i.stage == "offer":
                amt = int((l.list_price or 4e6) * random.uniform(0.88, 1.0)) // 5000 * 5000
                i.offer_amount, i.offer_terms = amt, pick(["30 day DD, 30 day close", "21 day DD, 1031 buyer", "All cash, 45 day close", "Seller carry 20%"])
                i.events[-1].amount = amt
            db.add(i)
            n_interest += 1
    db.flush()
    ctx["listings"] = listings
