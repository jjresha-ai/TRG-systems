"""Stage 1 seed: contacts, companies, properties, ownership (the owner graph)."""
import random
from collections import defaultdict
from datetime import datetime, timedelta

from ..models.core import (Company, Contact, ContactCompanyRole, ContactEmail, ContactPhone, ExternalId, Property, PropertyOwnership)
from ..services.dedupe import scan_all
from ..services.normalize import norm_address, norm_apn, norm_company_name, norm_domain, norm_email, norm_phone
from .gen import *  # noqa: F403
from .gen import AREAS, FIRST, LAST, pick, rnd

TAGS_OWNER = ["long-hold", "absentee", "1031 candidate", "trust", "family-owned", "out-of-state", "estate planning", "retail-focus", "industrial-focus", "refinance risk"]
TAGS_INV = ["1031 buyer", "syndicator", "family office", "cash buyer", "value-add", "NNN buyer", "industrial-focus"]


def seed(db, ctx):
    today = date.today()
    users = ctx["users"]
    brokers = [u for u in users if u.role in ("admin", "broker")]
    ctx["brokers"] = brokers
    used_emails, used_phones, used_names = set(), set(), set()

    def new_contact(types, area=None, title=None, tags=None, lifecycle=None, company_domain=None, created=None):
        for _ in range(50):
            f, l = pick(FIRST), pick(LAST)
            if (f, l) not in used_names:
                used_names.add((f, l))
                break
        dom = company_domain or pick(["gmail.com", "yahoo.com", "outlook.com", "icloud.com", "aol.com", "comcast.net", "cox.net", "sbcglobal.net"])
        em = f"{f[0].lower()}{l.lower().replace(chr(39), '')}@{dom}"
        n = 2
        while em in used_emails:
            em = f"{f.lower()}.{l.lower().replace(chr(39), '')}{n}@{dom}"
            n += 1
        used_emails.add(em)
        ph = phone(area[5] if area else None)
        while norm_phone(ph) in used_phones:
            ph = phone(area[5] if area else None)
        used_phones.add(norm_phone(ph))
        a = area or pick(AREAS)
        created = created or dt_last_year()
        c = Contact(first_name=f, last_name=l, full_name=f"{f} {l}", title=title, address=street_address(), city=a[0], state="CA", zip=a[4],
                    contact_types=types, status="active", lifecycle_stage=lifecycle or pick(["prospect", "prospect", "active_relationship", "client", "past_client"]),
                    owner_user_id=pick(brokers).id, source=pick(SOURCES), tags=tags or [], created_at=created, updated_at=created, custom={})
        c.emails.append(ContactEmail(email=em, normalized=norm_email(em), label="work" if company_domain else "personal", is_primary=True))
        c.phones.append(ContactPhone(phone=ph, normalized=norm_phone(ph), label="mobile", is_primary=True))
        if random.random() < 0.35:
            p2 = phone(a[5])
            if norm_phone(p2) not in used_phones:
                used_phones.add(norm_phone(p2))
                c.phones.append(ContactPhone(phone=p2, normalized=norm_phone(p2), label="office"))
        db.add(c)
        return c

    def new_company(name, kind, area=None, website=None, tags=None, created=None, parent=None):
        a = area or pick(AREAS)
        created = created or dt_last_year()
        co = Company(name=name, normalized_name=norm_company_name(name), kind=kind, website=website, domain=norm_domain(website),
                     address=street_address(), city=a[0], state="CA", zip=a[4], owner_user_id=pick(brokers).id, source=pick(SOURCES),
                     tags=tags or [], created_at=created, updated_at=created, parent_company_id=parent.id if parent else None, custom={})
        co.normalized_address = norm_address(co.address, co.city)
        db.add(co)
        return co

    # ---------- supporting companies ----------
    companies_by_kind = defaultdict(list)
    for name in LENDERS[:14]:
        co = new_company(name, "lender", website=f"https://www.{name.lower().split(' (')[0].replace(' ', '').replace('&', 'and')}.com")
        companies_by_kind["lender"].append(co)
    for name, site in [("Sperry Commercial Global Affiliates", "sperrycga.com"), ("CBRE", "cbre.com"), ("Marcus & Millichap", "marcusmillichap.com"), ("Lee & Associates", "lee-associates.com"),
                       ("Voit Real Estate Services", "voitco.com"), ("Colliers", "colliers.com"), ("Kidder Mathews", "kidder.com"), ("Newmark", "nmrk.com"), ("Cushman & Wakefield", "cushwake.com"), ("Daum Commercial", "daumcommercial.com")]:
        companies_by_kind["brokerage"].append(new_company(name, "brokerage", website=f"https://{site}"))
    for name in ["Coastline Law Group", "Brandt & Hale LLP", "Meridian Escrow", "First American Title (Irvine)", "Orange Coast Title", "Fidelity National Title", "Kessler Tax Advisors", "Pacific 1031 Exchange Services"]:
        companies_by_kind["other"].append(new_company(name, "other"))
    fund_names = ["1880 Capital Fund I", "1880 Capital Industrial Income LP", "Beacon Hill Family Office", "Westgate Private Capital", "Santa Rosa Syndications", "Lakeshore 1031 Partners",
                  "Camino Real Capital", "Redwood Peak Investors", "Southland NNN Fund", "Palmetto Ridge Capital", "Tidewater Equity Group", "Bluebird Real Estate Fund", "Granite Bay Family Office", "Orion Value-Add Partners"]
    for i, name in enumerate(fund_names):
        companies_by_kind["fund"].append(new_company(name, "fund" if "Fund" in name or "LP" in name or "Syndic" in name else "family_office",
                                                    website=f"https://www.{name.lower().replace(' ', '').replace(chr(39), '')}.com", tags=["investor"]))
    # ---------- owner families: contacts + holding entities ----------
    owner_entities = []   # (company, [principals])
    owner_contacts = []
    n_families = 62
    for i in range(n_families):
        home = pick(AREAS)
        tags = random.sample(TAGS_OWNER, rnd(0, 3))
        fam_last = pick(LAST)
        principals = []
        for _ in range(rnd(1, 3)):
            c = new_contact(["owner"], area=home, title=pick(["Owner", "Managing Member", "Trustee", "President", "Co-Trustee", "Partner", "Owner / Operator"]), tags=tags,
                            created=dt_last_year() - timedelta(days=rnd(0, 120)))
            principals.append(c)
            owner_contacts.append(c)
        n_ent = rnd(1, 4)
        parent = None
        for j in range(n_ent):
            kind = pick(["llc", "llc", "llc", "trust", "corporation"])
            base = pick(FAM_PREFIX)
            suffix = pick(FAM_SUFFIX)
            if kind == "trust":
                nm = f"{principals[0].last_name} Family Trust" + (f" {pick(['2004','1998','2011','2016','2009'])}" if j else "")
            elif kind == "corporation":
                nm = f"{base} {suffix} Inc"
            else:
                nm = f"{base} {pick(['Plaza','Center','Commerce','Industrial','Retail','Gateway','Ridge','Park','Crossing','Row'])} {suffix} LLC"
            if norm_company_name(nm) in {c.normalized_name for c, _ in owner_entities}:
                nm = nm.replace(" LLC", "").replace(" Inc", "") + f" {pick(['Alpha','Bravo','Delta','Echo','Sierra','Tango','Zulu','Omega'])} {pick(['Group','Trust','Co'])} LLC"
            co = new_company(nm, kind, area=home, tags=tags, parent=parent, created=dt_last_year() - timedelta(days=rnd(0, 120)))
            db.flush()
            if j == 0 and n_ent > 2:
                parent = co
            owner_entities.append((co, principals))
            for k, p in enumerate(principals):
                db.add(ContactCompanyRole(contact_id=p.id, company_id=co.id, role="principal" if k == 0 else pick(["principal", "manager", "principal"]),
                                          is_primary=(k == 0), start_date=day(3, 25)))
    # representatives: asset managers / attorneys for some entities
    rep_contacts = []
    for co, _ in random.sample(owner_entities, 30):
        r = new_contact(["other"], title=pick(["Asset Manager", "Property Manager", "Controller", "Estate Attorney"]), company_domain=f"{co.normalized_name.split()[0]}re.com" if co.normalized_name else None)
        rep_contacts.append(r)
        db.flush()
        db.add(ContactCompanyRole(contact_id=r.id, company_id=co.id, role=pick(["asset_manager", "representative", "attorney"]), start_date=day(1, 8)))
    # buyers, investors, lenders, attorneys, brokers, tenants
    inv_contacts, buyer_contacts = [], []
    for i in range(55):
        c = new_contact(["buyer", "investor"] if i % 3 == 0 else ["investor"], title=pick(["Principal", "Managing Director", "Partner", "Investor", "Acquisitions Director"]), tags=random.sample(TAGS_INV, rnd(1, 3)),
                        lifecycle=pick(["active_relationship", "prospect", "client"]))
        inv_contacts.append(c)
        db.flush()
        if i < 28:
            co = pick(companies_by_kind["fund"])
            db.add(ContactCompanyRole(contact_id=c.id, company_id=co.id, role=pick(["principal", "manager", "employee"]), is_primary=True))
    for i in range(40):
        c = new_contact(["buyer"], title=pick(["Principal", "Investor", "Owner", "VP Acquisitions"]), tags=random.sample(TAGS_INV, rnd(0, 2)))
        buyer_contacts.append(c)
    for i in range(14):
        c = new_contact(["lender"], title=pick(["VP Commercial Lending", "Relationship Manager", "SVP Real Estate", "Loan Officer"]), company_domain="bankmail.com", lifecycle="active_relationship")
        db.flush()
        db.add(ContactCompanyRole(contact_id=c.id, company_id=pick(companies_by_kind["lender"]).id, role="employee", is_primary=True))
    for i in range(12):
        c = new_contact(["attorney"], title=pick(["Partner", "Attorney", "Real Estate Counsel"]), company_domain="lawfirm.com", lifecycle="active_relationship")
        db.flush()
        db.add(ContactCompanyRole(contact_id=c.id, company_id=pick([x for x in companies_by_kind["other"] if "Law" in x.name or "LLP" in x.name] or companies_by_kind["other"]).id, role="attorney", is_primary=True))
    for i in range(14):
        c = new_contact(["broker"], title="Broker", company_domain="brokerage.com", lifecycle="active_relationship")
        db.flush()
        db.add(ContactCompanyRole(contact_id=c.id, company_id=pick(companies_by_kind["brokerage"]).id, role="employee", is_primary=True))
    for i in range(18):
        new_contact(["tenant"], title=pick(["Owner", "Franchisee", "Operations Director", "Real Estate Manager"]), lifecycle="prospect")
    # planted possible duplicates for the review queue
    for src in random.sample(owner_contacts, 4):
        db.flush()
        alt = {"Robert": "Bob", "William": "Bill", "Michael": "Mike"}.get(src.first_name, src.first_name + "e")
        d = Contact(first_name=alt, last_name=src.last_name, full_name=f"{alt} {src.last_name}", title=src.title, city=src.city, state="CA", contact_types=["owner"],
                    lifecycle_stage="prospect", owner_user_id=src.owner_user_id, source="CoStar export", tags=[], created_at=dt_last_year(), custom={})
        em = f"{alt.lower()}.{src.last_name.lower()}@gmail.com"
        d.emails.append(ContactEmail(email=em, normalized=em, is_primary=True))
        db.add(d)
        db.flush()
        role = db.query(ContactCompanyRole).filter_by(contact_id=src.id).first()
        if role:
            db.add(ContactCompanyRole(contact_id=d.id, company_id=role.company_id, role="principal"))
    db.flush()

    # ---------- properties ----------
    props = []
    entities_pool = owner_entities[:]
    # weight: some owners hold many properties
    weights = [rnd(1, 3) if random.random() > 0.2 else rnd(4, 8) for _ in entities_pool]
    used_apn, used_addr = set(), set()
    for i in range(155):
        area = pick(AREAS)
        is_retail = random.random() < 0.52
        sub = pick(RETAIL_SUBTYPES if is_retail else [s for s in IND_SUBTYPES if s[1][1] > 0])
        sf = rnd(*sub[1]) // 100 * 100
        psf = rnd(*sub[2])
        value = sf * psf if sf else rnd(2_000_000, 9_000_000)
        value = value // 10000 * 10000
        cap = rnd(450, 700) if is_retail else rnd(400, 580)
        acre = round(max(sf / (rnd(28, 55) * 1000) if is_retail else sf / (rnd(18, 28) * 1000), 0.2), 2) if sf else round(rnd(15, 90) / 10, 1)
        addr = street_address()
        while addr in used_addr:
            addr = street_address()
        used_addr.add(addr)
        apn = f"{rnd(100, 999)}-{rnd(100, 999)}-{rnd(10, 99)}"
        while apn in used_apn:
            apn = f"{rnd(100, 999)}-{rnd(100, 999)}-{rnd(10, 99)}"
        used_apn.add(apn)
        has_loan = random.random() < 0.78
        loan = int(value * rnd(45, 66) / 100) // 1000 * 1000
        mat = today + timedelta(days=rnd(-150, 365 * 6)) if has_loan else None
        hold = pick(["unknown", "unknown", "unknown", "hold", "hold", "open_to_sell", "open_to_sell", "selling_soon"])
        p = Property(name=None, address=addr, normalized_address=norm_address(addr, area[0]), city=area[0], state="CA", zip=area[4], apn=apn, apn_norm=norm_apn(apn),
                     county=area[1], property_type="retail" if is_retail else "industrial", subtype=sub[0], market=area[2], submarket=area[3],
                     building_sf=sf or None, land_acres=acre, units=None, year_built=rnd(1962, 2022), zoning=pick(["C-2", "C-1", "CG", "M-1", "M-2", "MG", "I-1", "PD"]),
                     noi=int(value * cap / 10000), cap_rate_bps=cap, estimated_value=value,
                     lat=round(area[6] + random.uniform(-0.04, 0.04), 5), lng=round(area[7] + random.uniform(-0.04, 0.04), 5),
                     lender=pick(LENDERS) if has_loan else None, loan_original_amount=loan if has_loan else None,
                     loan_rate_type=pick(["fixed", "fixed", "floating", "hybrid"]) if has_loan else None, loan_maturity_date=mat,
                     hold_intent=hold, pricing_expectation=int(value * random.uniform(0.95, 1.15)) // 10000 * 10000 if hold in ("open_to_sell", "selling_soon") else None,
                     owner_user_id=pick(brokers).id, source=pick(SOURCES), tags=random.sample(["value-add", "NNN", "vacant", "deferred maintenance", "below-market rents", "owner-user possible", "IOS", "redevelopment"], rnd(0, 2)),
                     created_at=dt_last_year(), custom={})
        if sub[0] == "Industrial Outdoor Storage":
            p.subtype = "Industrial Outdoor Storage"
            p.name = f"{area[0]} IOS Yard"
        elif sub[0] in ("Neighborhood Center", "Grocery-Anchored", "Strip Center"):
            p.name = f"{pick(['Plaza', 'Village', 'Marketplace', 'Crossing', 'Towne Center', 'Square'])} at {pick(STREETS).split()[0]}"
        db.add(p)
        props.append(p)
    db.flush()
    # ownership with history
    for p in props:
        co, principals = random.choices(entities_pool, weights=weights)[0]
        acquired = day(0.4, 28)
        # prior owners
        prior_acq = acquired
        for _ in range(random.choices([0, 1, 2], weights=[50, 38, 12])[0]):
            prev_co, _ = random.choice(entities_pool)
            if prev_co.id == co.id:
                continue
            start = prior_acq - timedelta(days=rnd(900, 3800))
            db.add(PropertyOwnership(property_id=p.id, company_id=prev_co.id, acquired_date=start, disposed_date=prior_acq, ownership_pct=100,
                                     acquisition_price=int((p.estimated_value or 3_000_000) * rnd(35, 80) / 100)))
            prior_acq = start
        pct = 100
        if random.random() < 0.12:
            co2, _ = random.choice(entities_pool)
            if co2.id != co.id:
                pct = 50
                db.add(PropertyOwnership(property_id=p.id, company_id=co2.id, acquired_date=acquired, ownership_pct=50, acquisition_price=int((p.estimated_value or 3e6) * rnd(40, 90) / 100)))
        db.add(PropertyOwnership(property_id=p.id, company_id=co.id, acquired_date=acquired, ownership_pct=pct,
                                 acquisition_price=int((p.estimated_value or 3e6) * rnd(30, 95) / 100) // 1000 * 1000))
    db.flush()
    # external ids for imported-source records (re-import mapping)
    for i, p in enumerate(props[:60]):
        db.add(ExternalId(entity="property", entity_id=p.id, system="CoStar", external_id=f"CS-{100000 + i}"))
    scan_all(db)
    db.flush()
    ctx.update(properties=props, owner_entities=owner_entities, owner_contacts=owner_contacts, inv_contacts=inv_contacts,
               buyer_contacts=buyer_contacts, companies_by_kind=companies_by_kind)
    from ..models.core import Contact as C
    ctx["all_contacts"] = db.query(C).filter(C.deleted_at.is_(None)).all()
