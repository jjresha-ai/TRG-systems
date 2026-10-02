"""Stage 5 seed: investor profiles, 1880 Capital funds, commitments."""
import random
from datetime import date, timedelta

from sqlalchemy import select

from ..models.core import Company, Property
from ..models.deals import Deal
from ..models.investors import Commitment, Fund, FundDeal, FundProperty, InvestorProfile
from .gen import pick, rnd

TODAY = date.today()
MARKETS = ["Orange County", "Los Angeles", "Inland Empire", "San Diego"]
TIERS = [(100_000, 500_000), (250_000, 1_000_000), (500_000, 2_000_000), (1_000_000, 5_000_000), (2_000_000, 10_000_000), (5_000_000, 25_000_000)]


def seed(db, ctx):
    users = ctx["users"]
    tyler = users[4]
    profiles = []
    for c in ctx["inv_contacts"]:
        lo, hi = pick(TIERS)
        acc = random.choices(["accredited", "pending", "unknown", "not_accredited"], weights=[72, 11, 13, 4])[0]
        dl = TODAY + timedelta(days=rnd(15, 170)) if random.random() < 0.3 else None
        p = InvestorProfile(contact_id=c.id, asset_classes=pick([["retail"], ["industrial"], ["retail", "industrial"], ["industrial"]]), markets=random.sample(MARKETS, rnd(1, 3)),
                            min_check=lo, max_check=hi, min_cap_rate_bps=pick([None, None, 450, 500, 525, 550]), exchange_1031=bool(dl) or random.random() < 0.15, exchange_deadline=dl,
                            target_return_notes=pick(["12-15% IRR target", "8% cash-on-cash minimum", "Value-add, 5-7 year hold", "Stabilized NNN, 10+ year lease term", "Core-plus, low leverage", None]),
                            accreditation_status=acc, accreditation_verified_on=TODAY - timedelta(days=rnd(10, 330)) if acc == "accredited" else None,
                            preferred_channel=pick(["email", "phone", "phone", "text", "in_person"]), owner_user_id=tyler.id if random.random() < 0.55 else pick(ctx["brokers"]).id,
                            created_at=c.created_at, notes=pick(["Prefers short summaries. Responds fast to text.", "Family office: decisions go through the CFO.", "Active buyer: has closed two deals with us.", None, None]))
        db.add(p)
        profiles.append(p)
    fam = [c for c in ctx["companies_by_kind"]["fund"] if c.kind == "family_office"][:6]
    for co in fam:
        lo, hi = pick(TIERS[3:])
        p = InvestorProfile(company_id=co.id, asset_classes=["industrial", "retail"], markets=random.sample(MARKETS, rnd(2, 4)), min_check=lo, max_check=hi, accreditation_status="accredited",
                            accreditation_verified_on=TODAY - timedelta(days=rnd(30, 300)), preferred_channel="email", owner_user_id=tyler.id, exchange_1031=False)
        db.add(p)
        profiles.append(p)
    db.flush()
    sponsor = next(c for c in ctx["companies_by_kind"]["fund"] if "1880 Capital Fund I" in c.name)
    funds_spec = [
        ("1880 Capital Fund I", "raising", 25_000_000, 100_000, "Value-add retail and light industrial across Orange County and the Inland Empire", "12-14% target IRR", 270, None, 0.56, 0.2, 0.3),
        ("1880 Capital Industrial Income LP", "closed", 40_000_000, 250_000, "Stabilized multi-tenant industrial, IE West and South Bay", "7% cash yield, 15% IRR", 520, 150, 0.99, 0.0, 0.0),
        ("Orange Coast NNN Syndication I", "raising", 12_500_000, 50_000, "Single-tenant NNN retail, 10+ years remaining term", "6.5% cash-on-cash", 150, None, 0.48, 0.15, 0.25),
        ("Inland Empire IOS Opportunity Fund", "planning", 18_000_000, 150_000, "Industrial outdoor storage yards in the IE", "15-18% target IRR", 40, None, 0.0, 0.0, 0.15),
        ("Westgate Retail Value-Add LP", "deployed", 9_000_000, 100_000, "Grocery-anchored value-add, South Bay", "14% target IRR", 640, 380, 1.0, 0.0, 0.0),
    ]
    funds = []
    accredited = [p for p in profiles if p.accreditation_status == "accredited"]
    others = [p for p in profiles if p.accreditation_status != "accredited"]
    for name, status, target, minimum, strat, ret, opened_days, closed_days, firm_pct, soft_pct, int_pct in funds_spec:
        f = Fund(name=name, sponsor_company_id=sponsor.id, status=status, target_raise=target, minimum_investment=minimum, strategy=strat, target_return_notes=ret,
                 opened_on=TODAY - timedelta(days=opened_days), closing_date=(TODAY - timedelta(days=closed_days)) if closed_days else (TODAY + timedelta(days=rnd(60, 200)) if status != "deployed" else None))
        db.add(f)
        db.flush()
        funds.append(f)
        used = set()

        def add(profile, amount, st):
            if profile.id in used:
                return 0
            used.add(profile.id)
            start = f.opened_on + timedelta(days=rnd(0, max(opened_days - 20, 1)))
            c = Commitment(investor_id=profile.id, fund_id=f.id, amount=amount, status=st, interested_on=start)
            if st in ("soft_circled", "committed", "funded"):
                c.soft_circled_on = start + timedelta(days=rnd(3, 25))
            if st in ("committed", "funded"):
                c.committed_on = c.soft_circled_on + timedelta(days=rnd(3, 30))
            if st == "funded":
                c.funded_on = min(c.committed_on + timedelta(days=rnd(7, 45)), TODAY)
            for k in ("interested_on", "soft_circled_on", "committed_on", "funded_on"):
                if getattr(c, k) and getattr(c, k) > TODAY:
                    setattr(c, k, TODAY - timedelta(days=rnd(1, 20)))
            db.add(c)
            return amount

        def fill(goal, st_pool, pool):
            tot, tries = 0, 0
            while tot < goal and tries < 400:
                tries += 1
                p = pick(pool)
                step = max(minimum, 50_000)
                cap = min(p.max_check or 1_000_000, max(minimum * 10, target * 0.05))
                amount = int(max(step, random.uniform(max(p.min_check or step, step), max(cap, step))) // 25_000 * 25_000)
                amount = max(amount, minimum)
                if tot + amount > goal * 1.0 + 1:
                    amount = int((goal - tot) // 25_000 * 25_000)
                    if amount < minimum:
                        break
                tot += add(p, amount, pick(st_pool))
            return tot

        firm_target = int(target * firm_pct)
        if status in ("closed", "deployed"):
            fill(firm_target, ["funded"], accredited)
        else:
            fill(int(firm_target * 0.55), ["funded"], accredited)
            fill(int(firm_target * 0.45), ["committed"], accredited)
        fill(int(target * soft_pct), ["soft_circled"], accredited)
        fill(int(target * int_pct), ["interested"], accredited + others)
        db.flush()
    # link properties and capital deals
    inds = [p for p in ctx["properties"] if p.property_type == "industrial"]
    rets = [p for p in ctx["properties"] if p.property_type == "retail"]
    for f, pool, n in [(funds[0], ctx["properties"], 3), (funds[1], inds, 5), (funds[2], rets, 2), (funds[3], inds, 2), (funds[4], rets, 3)]:
        for p in random.sample(pool, n):
            db.add(FundProperty(fund_id=f.id, property_id=p.id))
    cap_deals = [d for d in ctx["deals"] if d.pipeline.key == "capital"]
    for d in cap_deals:
        for f in funds:
            if f.name.split(":")[0] in d.name or f.name in d.name:
                db.add(FundDeal(fund_id=f.id, deal_id=d.id))
                break
    db.flush()
    ctx["funds"], ctx["investor_profiles"] = funds, profiles
