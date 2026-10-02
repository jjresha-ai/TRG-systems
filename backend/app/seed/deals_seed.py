"""Stage 3 seed: deals across all four pipelines with real stage history, parties and splits; weekly snapshots derived from history."""
import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from ..models.core import Company, Contact, Property
from ..models.deals import CommissionSplit, Deal, DealParty, DealStageHistory, Pipeline, PipelineSnapshot
from ..models.pipeline import BuyerInterest, Lead, Listing
from ..services import deals as svc
from .gen import pick, rnd

NOW = datetime.utcnow()


def _dt(d: date, hours=10) -> datetime:
    return datetime.combine(d, datetime.min.time()) + timedelta(hours=hours, minutes=random.randint(0, 59))


def _history(db, deal, pipe, path, times, user_id, terminal=None, terminal_at=None):
    prev = None
    rows = list(zip(path, times))
    if terminal:
        rows.append((terminal, terminal_at))
    for s, t in rows:
        db.add(DealStageHistory(deal_id=deal.id, from_stage_id=prev.id if prev else None, to_stage_id=s.id, at=t, user_id=user_id, note="Created" if prev is None else None))
        prev = s
    deal.stage_id, deal.stage_entered_at = prev.id, rows[-1][1]


def make_deal(db, pipe, target_key, name, created, owner, price, bps, prop=None, listing=None, parties=(), expected_close=None, lost_reason=None, closed_on=None, source="listing", dd=None):
    stages = {s.key: s for s in pipe.stages}
    opens = [s for s in pipe.stages if not s.is_won and not s.is_lost]
    tgt = stages[target_key]
    deal = Deal(name=name, pipeline_id=pipe.id, stage_id=tgt.id, status="open", property_id=prop.id if prop else None, listing_id=listing.id if listing else None,
                deal_type=pipe.deal_type, price=price, commission_rate_bps=bps, expected_close_date=expected_close, owner_user_id=owner.id, source=source,
                stage_entered_at=created, created_at=created, updated_at=created, tags=[], custom={}, dd_expiry_date=dd,
                listing_expiration_date=listing.expiration_date if listing else None)
    db.add(deal)
    db.flush()
    end = (_dt(closed_on) if closed_on else NOW)
    if tgt.is_won:
        path = [s for s in opens if s.position <= opens[-1].position]
        times = sorted(created + (end - created) * random.random() for _ in path[1:])
        times = [created] + times
        _history(db, deal, pipe, path, times, owner.id, terminal=tgt, terminal_at=end)
        deal.status, deal.actual_close_date = "won", closed_on
    elif tgt.is_lost:
        depth = rnd(1, len(opens))
        path = opens[:depth]
        last = created + (end - created) * 0.7
        times = [created] + sorted(created + (last - created) * random.random() for _ in path[1:])
        _history(db, deal, pipe, path, times, owner.id, terminal=tgt, terminal_at=min(max(last + timedelta(days=rnd(3, 25)), times[-1] + timedelta(days=1)), NOW))
        deal.status, deal.lost_reason = "lost", lost_reason or pick(["Owner decided to hold", "Pricing gap", "Listed with another broker", "Buyer financing failed", "1031 timing", "Seller withdrew"])
    else:
        path = [s for s in opens if s.position <= tgt.position]
        stay = timedelta(days=rnd(1, int((tgt.rotting_days or 30) * 1.5)))
        last = NOW - stay
        if len(path) == 1 or last <= created + timedelta(hours=2):
            created = last - timedelta(days=rnd(0, 6)) if len(path) == 1 else created
            deal.created_at = deal.updated_at = created
            last = max(last, created + timedelta(hours=1))
        times = [created] + sorted(created + (last - created) * random.random() for _ in path[2:]) + ([last] if len(path) > 1 else [])
        times = times[: len(path)]
        _history(db, deal, pipe, path, times, owner.id)
    for p in parties:
        db.add(DealParty(deal_id=deal.id, **p))
    return deal


def add_splits(db, deal, brokers):
    gross = svc.gross_of(deal)
    if not gross:
        return
    lead = next((b for b in brokers if b.id == deal.owner_user_id), brokers[0])
    r = random.random()
    if r < 0.45:
        db.add(CommissionSplit(deal_id=deal.id, recipient_user_id=lead.id, kind="internal", split_type="percent", pct=100))
    elif r < 0.75:
        other = pick([b for b in brokers if b.id != lead.id])
        db.add(CommissionSplit(deal_id=deal.id, recipient_user_id=lead.id, kind="internal", split_type="percent", pct=60))
        db.add(CommissionSplit(deal_id=deal.id, recipient_user_id=other.id, kind="internal", split_type="percent", pct=40))
    else:
        db.add(CommissionSplit(deal_id=deal.id, recipient_user_id=lead.id, kind="internal", split_type="percent", pct=70))
        db.add(CommissionSplit(deal_id=deal.id, external_name=pick(["CBRE", "Marcus & Millichap", "Lee & Associates", "Colliers", "Voit"]) + " (co-broker)", kind="co_broker", split_type="percent", pct=30))


def seed(db, ctx):
    today = date.today()
    svc.ensure_default_pipelines(db)
    pipes = {p.key: p for p in db.scalars(select(Pipeline))}
    seller = pipes["seller"]
    brokers = ctx["brokers"]
    deals = []
    # ---- seller-side deals mirror listings ----
    for l in ctx["listings"]:
        owner = next(b for b in brokers if b.id == l.owner_user_id)
        p = l.property
        name = f"{p.name or p.address} — Sale"
        parties = []
        if l.seller_contact_id:
            parties.append({"role": "seller", "contact_id": l.seller_contact_id})
        if l.seller_company_id:
            parties.append({"role": "seller", "company_id": l.seller_company_id})
        created = l.created_at
        if l.status == "closed":
            d = make_deal(db, seller, "closed", name, created, owner, l.sold_price, l.commission_rate_bps, p, l, parties, closed_on=l.closed_date)
            d.expected_close_date = l.closed_date
        elif l.status == "under_contract":
            tgt = pick(["under_contract", "due_diligence"])
            exp = today + timedelta(days=rnd(15, 80))
            top = db.scalar(select(BuyerInterest).where(BuyerInterest.listing_id == l.id, BuyerInterest.offer_amount.is_not(None)).order_by(BuyerInterest.offer_amount.desc()))
            price = top.offer_amount if top else int((l.list_price or 4e6) * 0.95) // 5000 * 5000
            if top:
                parties.append({"role": "buyer", "contact_id": top.contact_id})
            parties += [{"role": "lender", "company_id": pick(ctx["companies_by_kind"]["lender"]).id}, {"role": "title", "company_id": pick([c for c in ctx["companies_by_kind"]["other"] if "Title" in c.name or "Escrow" in c.name]).id}]
            d = make_deal(db, seller, tgt, name, created, owner, price, l.commission_rate_bps, p, l, parties, expected_close=exp, dd=(today + timedelta(days=rnd(3, 28))) if tgt == "due_diligence" else None)
            d.loan_contingency_date = today + timedelta(days=rnd(10, 40))
        elif l.status == "active":
            d = make_deal(db, seller, pick(["marketing"] * 7 + ["offers"] * 3), name, created, owner, l.list_price, l.commission_rate_bps, p, l, parties, expected_close=today + timedelta(days=rnd(60, 270)))
        elif l.status == "prospect":
            d = make_deal(db, seller, pick(["prospect", "pitch", "listing_agreement"]), name, created, owner, l.list_price or p.estimated_value, l.commission_rate_bps, p, l, parties,
                          expected_close=today + timedelta(days=rnd(120, 330)), source="trigger lead")
        else:
            d = make_deal(db, seller, "lost", name, created, owner, l.list_price, l.commission_rate_bps, p, l, parties, lost_reason="Listing expired" if l.status == "expired" else "Seller withdrew")
        l.deal_id = d.id
        deals.append(d)
    # ---- early-stage seller deals from converted leads ----
    for lead in db.scalars(select(Lead).where(Lead.status == "converted", Lead.conversion_outcome == "deal")):
        p = lead.property
        if p is None or db.scalar(select(Deal).where(Deal.property_id == p.id, Deal.status == "open")):
            lead.conversion_outcome = "contact"
            continue
        owner = next(b for b in brokers if b.id == lead.owner_user_id)
        d = make_deal(db, seller, pick(["prospect", "pitch"]), f"{p.address} — Sale", lead.converted_at or lead.created_at, owner, p.estimated_value, pick([250, 300]), p, None,
                      [{"role": "seller", "contact_id": lead.contact_id}] if lead.contact_id else [], expected_close=today + timedelta(days=rnd(150, 330)), source="lead conversion")
        lead.deal_id = d.id
        deals.append(d)
    # ---- buyer representation ----
    buyers = ctx["buyer_contacts"] + ctx["inv_contacts"]
    for i in range(14):
        b = pick(buyers)
        p = pick(ctx["properties"])
        owner = pick(brokers)
        tgt = ["closed", "closed", "closed", "lost", "lost", "qualification", "search", "search", "offer", "offer", "under_contract", "due_diligence", "search", "qualification"][i]
        price = int((p.estimated_value or 4e6) * random.uniform(0.9, 1.0)) // 25000 * 25000
        created = _dt(today - timedelta(days=rnd(30, 330)))
        closed_on = today - timedelta(days=rnd(10, max((today - created.date()).days - 20, 11))) if tgt == "closed" else None
        d = make_deal(db, pipes["buyer"], tgt, f"Buyer rep: {b.full_name} — {p.address}", created, owner, price, pick([100, 125, 150]), p, None, [{"role": "buyer", "contact_id": b.id}],
                      expected_close=today + timedelta(days=rnd(20, 200)), closed_on=closed_on, source="buyer relationship", dd=today + timedelta(days=rnd(5, 30)) if tgt == "due_diligence" else None)
        deals.append(d)
    # ---- capital raises (1880 Capital) ----
    funds = [c for c in ctx["companies_by_kind"]["fund"] if "1880" in c.name or "Syndic" in c.name or "Partners" in c.name]
    for i in range(12):
        inv = pick(ctx["inv_contacts"])
        fund = pick(funds)
        owner = next(b for b in brokers if b.name == "Tyler Brooks") if i % 2 else pick(brokers)
        tgt = ["committed", "committed", "soft_circled", "soft_circled", "soft_circled", "materials", "materials", "initial_discussion", "initial_discussion", "closed", "closed", "lost"][i]
        amt = pick([250_000, 500_000, 750_000, 1_000_000, 1_500_000, 2_000_000, 3_000_000])
        created = _dt(today - timedelta(days=rnd(20, 300)))
        closed_on = today - timedelta(days=rnd(5, 60)) if tgt == "closed" else None
        d = make_deal(db, pipes["capital"], tgt, f"{fund.name}: {inv.full_name} commitment", created, owner, amt, pick([100, 150, 200]), None, None,
                      [{"role": "buyer", "contact_id": inv.id}, {"role": "other", "company_id": fund.id}], expected_close=today + timedelta(days=rnd(15, 150)), closed_on=closed_on, source="1880 Capital")
        deals.append(d)
    # ---- leasing ----
    tenants = db.scalars(select(Contact).where(Contact.contact_types.like('%"tenant"%'))).all()
    for i in range(10):
        t = pick(tenants)
        p = pick(ctx["properties"])
        owner = pick(brokers)
        tgt = ["inquiry", "tour", "tour", "proposal", "proposal", "lease_negotiation", "closed", "closed", "closed", "lost"][i]
        sf = p.building_sf or 10000
        total = int(sf * 0.35 * 12 * 5 * random.uniform(0.2, 0.6) / 1000) * 1000 + 150_000
        created = _dt(today - timedelta(days=rnd(25, 280)))
        closed_on = today - timedelta(days=rnd(5, 90)) if tgt == "closed" else None
        d = make_deal(db, pipes["leasing"], tgt, f"Lease: {t.full_name} — {p.address}", created, owner, total, pick([400, 500, 600]), p, None, [{"role": "buyer", "contact_id": t.id}],
                      expected_close=today + timedelta(days=rnd(20, 140)), closed_on=closed_on, source="inbound")
        deals.append(d)
    db.flush()
    for d in deals:
        if d.status in ("won",) or (d.stage.key in ("under_contract", "due_diligence", "offers", "committed", "lease_negotiation")):
            add_splits(db, d, brokers)
    # ---- weekly pipeline snapshots reconstructed from real stage history ----
    hist = {}
    for h in db.scalars(select(DealStageHistory).order_by(DealStageHistory.at, DealStageHistory.id)):
        hist.setdefault(h.deal_id, []).append(h)
    stages = {s.id: s for p in pipes.values() for s in p.stages}
    for w in range(52, -1, -1):
        day = today - timedelta(weeks=w)
        t = _dt(day, 23)
        agg = {}
        for d in deals:
            rows = [h for h in hist.get(d.id, []) if h.at <= t]
            if not rows:
                continue
            st = stages[rows[-1].to_stage_id]
            if st.is_won or st.is_lost:
                continue
            a = agg.setdefault(d.pipeline_id, [0, 0, 0, 0])
            price = d.price or 0
            g = svc.gross_of(d) or 0
            a[0] += 1
            a[1] += price
            a[2] += round(price * st.probability / 100)
            a[3] += round(g * st.probability / 100)
        for pid, (n, vol, wv, wc) in agg.items():
            db.add(PipelineSnapshot(taken_on=day, pipeline_id=pid, open_deals=n, volume=vol, weighted_volume=wv, weighted_commission=wc))
    db.flush()
    ctx["deals"] = deals
