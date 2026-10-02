"""Stage 7 seed: custom fields (and values), tags, saved views, dynamic and static lists."""
import random
from datetime import datetime

from ..models.core import Company, Contact, Property
from ..models.deals import Deal
from ..models.pipeline import Listing
from ..models.platform import FieldDefinition, ListDef, SavedView
from .gen import pick, rnd

F = lambda *a: {"field": a[0], "operator": a[1], **({"value": a[2]} if len(a) > 2 else {})}  # noqa: E731
G = lambda op, *c: {"op": op, "conditions": list(c)}  # noqa: E731


def seed(db, ctx):
    jim = ctx["users"][0]
    maria = ctx["users"][1]
    kevin = ctx["users"][2]
    defs = [
        FieldDefinition(entity="property", key="roof_age_years", label="Roof age (years)", type="number", position=0),
        FieldDefinition(entity="property", key="seller_motivation", label="Seller motivation", type="single_select", options=["Estate / succession", "Refinance risk", "Retirement", "Portfolio rebalance", "1031 into larger asset", "Unknown"], position=1),
        FieldDefinition(entity="property", key="tenant_concentration", label="Tenant concentration risk", type="checkbox", position=2),
        FieldDefinition(entity="contact", key="best_time_to_call", label="Best time to call", type="single_select", options=["Early morning", "Mid-day", "Late afternoon", "Evenings", "Email only"], position=0),
        FieldDefinition(entity="contact", key="referred_by", label="Referred by", type="text", position=1),
        FieldDefinition(entity="listing", key="marketing_package", label="Marketing package", type="multi_select", options=["OM", "Flyer", "Video tour", "Drone", "Broker open house", "Email blast"], position=0),
        FieldDefinition(entity="deal", key="coop_split_note", label="Co-op split note", type="text", position=0),
        FieldDefinition(entity="deal", key="referral_fee_note", label="Referral fee note", type="long_text", restricted=True, position=1),
    ]
    db.add_all(defs)
    db.flush()
    for p in random.sample(ctx["properties"], 110):
        p.custom = {"roof_age_years": rnd(2, 32), "seller_motivation": pick(["Estate / succession", "Refinance risk", "Retirement", "Portfolio rebalance", "1031 into larger asset", "Unknown"]), "tenant_concentration": random.random() < 0.3}
    for c in random.sample(ctx["all_contacts"], 120):
        c.custom = {"best_time_to_call": pick(["Early morning", "Mid-day", "Late afternoon", "Evenings", "Email only"]), **({"referred_by": pick(["Estate attorney", "Lender", "Past client", "ICSC", "CREW networking"])} if random.random() < 0.4 else {})}
    for l in ctx["listings"]:
        if l.status in ("active", "under_contract", "closed"):
            l.custom = {"marketing_package": sorted(random.sample(["OM", "Flyer", "Video tour", "Drone", "Broker open house", "Email blast"], rnd(2, 5)))}
    for d in random.sample(ctx["deals"], 30):
        d.custom = {"coop_split_note": pick(["50/50 with buyer's broker", "Co-broker gets 25%", "Referral to attorney: 10%"]), **({"referral_fee_note": "Referral fee owed to CPA at close (confidential)"} if random.random() < 0.3 else {})}
    # tags
    for c in random.sample(ctx["owner_contacts"], 60):
        c.tags = sorted(set(c.tags or []) | {pick(["call-campaign-q4", "icsc-2026", "vip", "estate-planning"])})
    for c in random.sample(ctx["inv_contacts"], 25):
        c.tags = sorted(set(c.tags or []) | {pick(["1880-fund-i-prospect", "industrial-buyer", "vip"])})
    for p in random.sample(ctx["properties"], 40):
        p.tags = sorted(set(p.tags or []) | {pick(["q4-target", "bov-requested", "off-market"])})
    db.flush()
    views = [
        ("Loan maturing within 12 months", "property", G("and", F("loan_maturity_date", "within_days", 365)), ["address", "city", "property_type", "loan_maturity_date", "lender", "owner.name", "principal.name"], "loan_maturity_date", "asc", "shared", jim),
        ("Industrial 50k+ SF held 10+ years", "property", G("and", F("property_type", "eq", "industrial"), F("building_sf", "gte", 50000), F("hold_years", "gte", 10)), ["address", "city", "building_sf", "estimated_value", "hold_years", "owner.name"], "hold_years", "desc", "shared", jim),
        ("Retail owners open to sell", "property", G("and", F("property_type", "eq", "retail"), F("hold_intent", "in", ["open_to_sell", "selling_soon"])), ["address", "city", "estimated_value", "hold_intent", "owner.name", "last_contact_at"], "estimated_value", "desc", "shared", kevin),
        ("Hot leads (score 60+)", "lead", G("and", F("status", "eq", "new"), F("score", "gte", 60)), ["name", "score", "source.name", "property.city"], "score", "desc", "shared", jim),
        ("Deals closing in the next 60 days", "deal", G("and", F("status", "eq", "open"), F("expected_close_date", "within_days", 60)), ["name", "pipeline.key", "stage.key", "price", "expected_close_date"], "expected_close_date", "asc", "shared", maria),
        ("Owners untouched 90+ days (mine)", "contact", G("and", F("contact_types", "contains", "owner"), G("or", F("last_contact_at", "older_than_days", 90), F("last_contact_at", "is_null"))), ["full_name", "company.name", "last_contact_at", "holdings_count"], "last_contact_at", "asc", "private", jim),
    ]
    for name, ent, flt, cols, sf, sd, vis, owner in views:
        db.add(SavedView(name=name, entity=ent, filter=flt, columns=cols, sort_field=sf, sort_dir=sd, visibility=vis, owner_user_id=owner.id))
    lists = [
        ListDef(name="Q4 call campaign: owners with maturing loans", entity="contact", kind="dynamic", filter=G("and", F("contact_types", "contains", "owner"), F("holdings.loan_maturity_date", "within_days", 365)),
                description="Owners with a loan maturing in the next 12 months", visibility="shared", owner_user_id=jim.id),
        ListDef(name="1031 buyers: industrial", entity="contact", kind="dynamic", filter=G("and", F("tags", "contains", "industrial-buyer")), description="Tagged industrial buyers for listing blasts", visibility="shared", owner_user_id=ctx["users"][4].id),
        ListDef(name="Trust & estate owners", entity="company", kind="dynamic", filter=G("and", F("kind", "eq", "trust")), visibility="shared", owner_user_id=maria.id),
        ListDef(name="ICSC 2026 follow-ups", entity="contact", kind="static", members=sorted(c.id for c in random.sample(ctx["owner_contacts"], 25)), snapshot_at=datetime.utcnow(), description="People met at ICSC", visibility="shared", owner_user_id=jim.id),
        ListDef(name="Off-market targets", entity="property", kind="dynamic", filter=G("and", F("tags", "contains", "off-market")), visibility="shared", owner_user_id=kevin.id),
    ]
    db.add_all(lists)
    db.flush()
