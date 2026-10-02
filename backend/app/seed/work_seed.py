"""Stage 4 seed: a year of activities, open tasks, cadences, notes, mentions and real stored documents (valid PDFs/PNGs)."""
import hashlib
import random
import struct
import zlib
from datetime import date, datetime, timedelta

from sqlalchemy import select

from .. import config
from ..models.core import Company, Contact, Property
from ..models.core_sys import User
from ..models.deals import Deal
from ..models.pipeline import BuyerInterest, Lead, Listing
from ..models.work import (Activity, ActivityAssociation, CadenceTemplate, Document, DocumentAssociation, Note, NoteAssociation, NoteVersion, Notification)
from ..services import prospecting, work as svc
from .gen import pick, rnd

NOW = datetime.utcnow()
TODAY = date.today()


def make_pdf(title: str, lines: list[str]) -> bytes:
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    text = "BT /F1 20 Tf 72 720 Td (" + esc(title) + ") Tj /F1 11 Tf 0 -34 Td 16 TL\n" + "\n".join(f"({esc(l)}) Tj T*" for l in lines) + "\nET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(text)} >>\nstream\n{text}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def make_png(w=480, h=300, base=(30, 60, 100)) -> bytes:
    rows = b""
    for y in range(h):
        r = bytes(v for x in range(w) for v in (min(255, base[0] + x // 4 + y // 6), min(255, base[1] + y // 3), min(255, base[2] + (x + y) // 8)))
        rows += b"\x00" + r
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b"")


def store(content: bytes):
    digest = hashlib.sha256(content).hexdigest()
    path = config.STORAGE_DIR / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(content)
    return digest, str(path)


def seed(db, ctx):
    brokers = ctx["brokers"]
    users = ctx["users"]
    all_users = users
    jim = users[0]
    contacts = [c for c in ctx["all_contacts"]]
    # a handful of do-not-contact people (outreach is blocked for them in the backend)
    dnc = random.sample(ctx["owner_contacts"], 6)
    for c, why in zip(dnc, ["Asked to be removed from calls", "Estate attorney requested no direct contact", "Litigation hold", "Requested email only", "Do not solicit: prior dispute", "Moved out of state, not selling"]):
        c.do_not_contact, c.do_not_contact_reason = True, why
    dnc_ids = {c.id for c in dnc}
    # ---------------- cadences ----------------
    cads = [
        CadenceTemplate(name="Owner prospecting (90-day)", record_type="contact", description="Intro call, email, then spaced follow-ups for a hold/sell owner",
                        steps=[{"day_offset": 0, "type": "call", "subject": "Intro call: hold/sell plans", "priority": "high"}, {"day_offset": 2, "type": "email", "subject": "Send market update and recent comps"},
                               {"day_offset": 14, "type": "call", "subject": "Follow-up call"}, {"day_offset": 45, "type": "meeting", "subject": "Coffee / property walk"}, {"day_offset": 90, "type": "call", "subject": "90-day check-in"}]),
        CadenceTemplate(name="Post-listing follow-up", record_type="listing", description="Weekly seller update rhythm after launch",
                        steps=[{"day_offset": 7, "type": "call", "subject": "Week-1 seller update call"}, {"day_offset": 14, "type": "email", "subject": "Buyer activity report to seller"}, {"day_offset": 30, "type": "meeting", "subject": "30-day marketing review"}]),
        CadenceTemplate(name="Buyer follow-up after tour", record_type="contact", description="Keep tour attendees warm until an offer or pass",
                        steps=[{"day_offset": 1, "type": "call", "subject": "Post-tour feedback call", "priority": "high"}, {"day_offset": 5, "type": "email", "subject": "Send financials and rent roll"}, {"day_offset": 10, "type": "call", "subject": "Offer timing check"}]),
    ]
    db.add_all(cads)
    db.flush()
    # ---------------- completed activities (the last 12 months) ----------------
    props = ctx["properties"]
    activities = []
    CALL_SUBJ = ["Call: hold/sell plans", "Call: loan maturity discussion", "Intro call", "Follow-up on market update", "Call: pricing expectations", "Call: refinance vs sell", "Check-in call", "Call re: tenant roll"]
    EMAIL_SUBJ = ["Sent market update", "Sent recent comps", "Emailed broker opinion of value", "Sent listing flyer", "Followed up on call", "Sent cap rate trends memo"]
    MEET_SUBJ = ["Lunch meeting", "Listing presentation", "Coffee at owner's office", "Portfolio review meeting", "Zoom: valuation walkthrough"]
    SITE_SUBJ = ["Walked the property", "Site visit with owner", "Roof/parking lot walk", "Tenant tour of space"]

    def day_weighted():
        d = int(random.random() ** 1.6 * 365)
        return NOW - timedelta(days=d, hours=rnd(0, 8), minutes=rnd(0, 59))

    def when():
        t = day_weighted().replace(hour=rnd(8, 17), minute=rnd(0, 59), second=0, microsecond=0)
        while t.weekday() >= 5:
            t -= timedelta(days=1)
        return min(t, NOW - timedelta(hours=2))

    def add_act(type_, subject, links, user, completed=None, due=None, outcome=None, body=None, prio="normal", recurrence=None, cadence=None):
        a = Activity(type=type_, subject=subject, body=body, status="completed" if completed else "planned", completed_at=completed, due_at=due or completed, assignee_user_id=user.id,
                     created_by_user_id=user.id, priority=prio, outcome=outcome, recurrence_days=recurrence, cadence_id=cadence, created_at=(completed or NOW) - timedelta(days=rnd(0, 5)))
        for rt, rid in dict.fromkeys(links):
            a.associations.append(ActivityAssociation(record_type=rt, record_id=rid))
        db.add(a)
        activities.append(a)
        return a

    def pick_outcome():
        return random.choices(["spoke", "left_voicemail", "no_answer", "not_interested", "meeting_set"], weights=[40, 28, 22, 6, 4])[0]

    owner_pairs = []
    for p in random.sample(props, 120):
        contact, company = prospecting.primary_principal(db, p)
        if contact and contact.id not in dnc_ids:
            owner_pairs.append((p, contact, company))
    for i in range(430):
        p, c, co = pick(owner_pairs)
        u = next(b for b in brokers if b.id == (c.owner_user_id or brokers[0].id)) if random.random() < 0.7 else pick(brokers)
        t = when()
        links = [("contact", c.id), ("property", p.id)] + ([("company", co.id)] if co and random.random() < 0.5 else [])
        r = random.random()
        if r < 0.5:
            add_act("call", pick(CALL_SUBJ), links, u, completed=t, outcome=pick_outcome())
        elif r < 0.75:
            add_act("email", pick(EMAIL_SUBJ), links, u, completed=t)
        elif r < 0.9:
            add_act("meeting", pick(MEET_SUBJ), links, u, completed=t, body=pick(["Discussed 1031 timing", "Owner open to an offer above $X", "Wants to hold until lease renewal", "Estate planning is driving the decision", None]))
        else:
            add_act("site_visit", pick(SITE_SUBJ), links, u, completed=t)
    # listing / buyer activity
    for l in ctx["listings"]:
        if l.status in ("prospect", "withdrawn"):
            continue
        u = next(b for b in brokers if b.id == l.owner_user_id)
        base = datetime.combine(l.active_date or l.agreement_date or TODAY - timedelta(days=30), datetime.min.time())
        for k in range(rnd(2, 6)):
            t = min(base + timedelta(days=rnd(1, 120), hours=rnd(8, 17)), NOW - timedelta(hours=3))
            add_act(pick(["call", "email", "meeting"]), pick(["Seller update call", "Buyer activity report", "Marketing review", "Broker open house"]), [("listing", l.id), ("property", l.property_id)], u, completed=t,
                    outcome="spoke")
        for i in db.scalars(select(BuyerInterest).where(BuyerInterest.listing_id == l.id).limit(5)):
            if i.contact_id in dnc_ids:
                continue
            t = min(i.events[-1].at + timedelta(hours=rnd(1, 30)), NOW - timedelta(hours=1)) if i.events else when()
            add_act(pick(["call", "email", "site_visit"]), pick(["Buyer follow-up", "Sent OM and rent roll", "Property tour", "Discussed offer terms"]), [("contact", i.contact_id), ("listing", l.id)], u, completed=t,
                    outcome="spoke")
    # lead work
    for lead in db.scalars(select(Lead).where(Lead.status.in_(["contacted", "qualified", "converted"])).limit(120)):
        u = next((b for b in brokers if b.id == lead.owner_user_id), pick(brokers))
        t = max(lead.created_at + timedelta(days=rnd(0, 20)), NOW - timedelta(days=360))
        t = min(t.replace(hour=rnd(8, 17)), NOW - timedelta(hours=2))
        add_act("call", "Prospecting call: " + lead.name, [("lead", lead.id)] + ([("property", lead.property_id)] if lead.property_id else []), u, completed=t, outcome=pick_outcome())
    # investor relationship (1880 Capital)
    tyler = users[4]
    for c in random.sample(ctx["inv_contacts"], 30):
        if c.id in dnc_ids:
            continue
        for k in range(rnd(1, 4)):
            add_act(pick(["call", "email", "meeting"]), pick(["1880 Capital: fund update", "Investor criteria review", "Intro to new syndication", "1031 timeline check-in", "Sent offering summary"]), [("contact", c.id)], tyler if random.random() < 0.6 else pick(brokers), completed=when(), outcome="spoke")
    # deal activities
    for d in random.sample(ctx["deals"], 40):
        u = next((b for b in brokers if b.id == d.owner_user_id), pick(brokers))
        add_act("meeting", pick(["Deal strategy meeting", "Lender call", "Buyer/seller call", "Closing coordination"]), [("deal", d.id)] + ([("property", d.property_id)] if d.property_id else []), u, completed=when())
    # ---------------- open tasks ----------------
    def due_at(days, hour=None):
        return datetime.combine(TODAY + timedelta(days=days), datetime.min.time()) + timedelta(hours=hour or rnd(8, 16))
    n_open = 0
    for days in [-14, -9, -6, -4, -3, -2, -1, -1, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 5, 6] * 3 + [rnd(7, 70) for _ in range(40)]:
        p, c, co = pick(owner_pairs)
        u = jim if random.random() < 0.4 else pick(brokers)
        t = pick(["call", "call", "email", "meeting"])
        verb = {"call": ["Call", "Follow-up call with"], "email": ["Email", "Send comps to"], "meeting": ["Schedule meeting with", "Meet with"]}[t]
        subj = pick(verb) + f" {c.full_name}: " + pick(["loan maturity", "listing interest", "market update", "hold/sell decision", "tenant renewal", "refi quote"])
        add_act(t, subj, [("contact", c.id), ("property", p.id)], u, due=due_at(days), prio=pick(["normal", "normal", "high", "low"]))
        n_open += 1
    for c in random.sample(ctx["owner_contacts"], 12):
        if c.id in dnc_ids:
            continue
        add_act("call", "90-day owner check-in", [("contact", c.id)], pick(brokers), due=due_at(rnd(3, 80)), recurrence=90)
    for c in random.sample([x for x in ctx["owner_contacts"] if x.id not in dnc_ids], 6):
        for st_i, st in enumerate(cads[0].steps):
            a = Activity(type=st["type"], subject=st["subject"], status="planned", due_at=due_at(st["day_offset"] - rnd(0, 20)), assignee_user_id=c.owner_user_id, created_by_user_id=jim.id, priority=st.get("priority", "normal"),
                         cadence_id=cads[0].id, source_key=f"cadence:{cads[0].id}:contact:{c.id}:seed:{st_i}")
            a.associations.append(ActivityAssociation(record_type="contact", record_id=c.id))
            db.add(a)
    db.flush()
    for a in activities:
        if a.status == "completed":
            svc.apply_last_contact(db, a)
    db.flush()
    # open deal key-date tasks come from the real hook
    for d in ctx["deals"]:
        if d.status == "open":
            svc.sync_key_date_tasks(db, d)
    # ---------------- notes ----------------
    NOTES = ["Owner is thinking about selling in the next 12-18 months. Wants to see what the property would trade for before deciding.",
             "Prefers phone to email. Best time is early morning. Spouse is on title.",
             "Loan matures next year and the lender is asking for a paydown. Considering a sale instead of refinancing.",
             "Told us pricing expectation is around $X but acknowledged cap rates have moved. Open to a BOV.",
             "Tenant roll: two anchors renew in 2027. Owner nervous about rollover risk.",
             "Estate situation. Daughters will decide. Do not press, check back after the holidays.",
             "Wants a 1031 into industrial in the Inland Empire. Needs replacement property identified within 45 days.",
             "Previously worked with another broker and was unhappy. Wants a senior point of contact.",
             "Property needs roof work. Capex is part of the sell-vs-hold decision.",
             "Met at ICSC. Strong relationship with the anchor tenant. Hold intent is genuine for now.",
             "Asked us to send quarterly market updates. No pressure to sell.",
             "Wants to know the value as-is vs after rent bumps. Will share rent roll once NDA is signed.",
             "Buyer is an all-cash 1031 exchange buyer. Closing timeline is flexible.",
             "Investor prefers NNN with 10+ years remaining. Minimum check $500K."]
    user_pool = [u for u in all_users]
    n_notes = 0
    for i in range(170):
        r = random.random()
        if r < 0.55:
            p, c, co = pick(owner_pairs)
            links = [("contact", c.id), ("property", p.id)]
        elif r < 0.7 and ctx["listings"]:
            l = pick(ctx["listings"])
            links = [("listing", l.id), ("property", l.property_id)]
        elif r < 0.82:
            d = pick(ctx["deals"])
            links = [("deal", d.id)]
        else:
            c = pick(ctx["inv_contacts"] + ctx["buyer_contacts"])
            links = [("contact", c.id)]
        author = pick(brokers)
        created = when()
        body = pick(NOTES).replace("$X", f"${rnd(2, 20)}.{rnd(0, 9)}M")
        mention = None
        if random.random() < 0.18:
            mention = pick([u for u in user_pool if u.id != author.id])
            body += f" @[{mention.name}] FYI."
        n = Note(body=body, author_user_id=author.id, pinned=random.random() < 0.08, visibility="private" if random.random() < 0.06 else "team", version=1, created_at=created, updated_at=created)
        for rt, rid in dict.fromkeys(links):
            n.associations.append(NoteAssociation(record_type=rt, record_id=rid))
        n.versions.append(NoteVersion(version=1, body=body, edited_by_user_id=author.id, edited_at=created))
        if random.random() < 0.1:
            n.version, n.body = 2, body + " Update: spoke again, same position."
            n.versions.append(NoteVersion(version=2, body=n.body, edited_by_user_id=author.id, edited_at=created + timedelta(days=rnd(1, 20))))
        db.add(n)
        db.flush()
        if mention and n.visibility == "team":
            db.add(Notification(user_id=mention.id, kind="mention", message=f"{author.name} mentioned you: {body[:120]}", record_type=links[0][0], record_id=links[0][1], key=f"mention:{n.id}:{n.version}:{mention.id}",
                                created_at=created, read_at=created + timedelta(days=1) if random.random() < 0.6 else None))
        n_notes += 1
    # ---------------- documents (real files on disk) ----------------
    def add_doc(name, dtype, content, ctype, links, user, created, visibility="team", version=1, group=None):
        digest, path = store(content)
        d = Document(file_name=name, doc_type=dtype, content_type=ctype, size=len(content), content_hash=digest, storage_path=path, uploader_user_id=user.id, visibility=visibility, version=version,
                     group_id=group, created_at=created, updated_at=created)
        for rt, rid in dict.fromkeys(links):
            d.associations.append(DocumentAssociation(record_type=rt, record_id=rid))
        db.add(d)
        db.flush()
        if not d.group_id:
            d.group_id = d.id
        return d

    for l in ctx["listings"]:
        if l.status in ("prospect", "withdrawn"):
            continue
        p = l.property
        u = next(b for b in brokers if b.id == l.owner_user_id)
        t0 = datetime.combine(l.agreement_date or TODAY, datetime.min.time()) + timedelta(days=rnd(1, 10), hours=11)
        links = [("listing", l.id), ("property", p.id)]
        info = [f"{p.address}, {p.city}, CA", f"{p.subtype} | {p.building_sf or 0:,} SF | Built {p.year_built}", f"List price: ${l.list_price or 0:,}", f"NOI: ${p.noi or 0:,} | Cap rate: {(p.cap_rate_bps or 0) / 100:.2f}%", "Offering Memorandum - The Resha Group, Sperry Commercial"]
        om1 = add_doc(f"OM - {p.address}.pdf", "om", make_pdf(f"Offering Memorandum: {p.address}", info + ["Draft v1"]), "application/pdf", links, u, t0)
        if random.random() < 0.35:
            add_doc(om1.file_name, "om", make_pdf(f"Offering Memorandum: {p.address}", info + ["Revised v2: updated rent roll and pricing"]), "application/pdf", links, u, t0 + timedelta(days=rnd(10, 40)), version=2, group=om1.group_id)
        add_doc(f"CA - {p.address}.pdf", "ca", make_pdf("Confidentiality Agreement", [f"Re: {p.address}, {p.city}", "Recipient agrees to keep all offering materials confidential."]), "application/pdf", links, u, t0)
        if random.random() < 0.5:
            add_doc(f"Flyer - {p.address}.pdf", "flyer", make_pdf(f"FOR SALE: {p.address}", info[:3]), "application/pdf", links, u, t0 + timedelta(days=2))
        if l.status in ("under_contract", "closed"):
            add_doc(f"PSA - {p.address}.pdf", "psa", make_pdf("Purchase and Sale Agreement", [f"Property: {p.address}, {p.city}", f"Price: ${(l.sold_price or l.list_price or 0):,}", "Draft for review by counsel"]), "application/pdf", links, u, t0 + timedelta(days=rnd(60, 140)), visibility="confidential")
            add_doc(f"Rent Roll - {p.address}.pdf", "rent_roll", make_pdf("Rent Roll", [p.address, "Tenant, SF, Rent/SF, Expiration"] + [f"Suite {chr(65 + k)}, {rnd(1, 9) * 1000} SF, ${rnd(15, 40) / 10:.2f}, 20{rnd(27, 33)}" for k in range(5)]), "application/pdf", links, u, t0, visibility="confidential")
    for p in random.sample(props, 30):
        add_doc(f"Photo - {p.address}.png", "photo", make_png(base=(rnd(10, 120), rnd(40, 120), rnd(60, 160))), "image/png", [("property", p.id)], pick(brokers), when())
    for d in random.sample([x for x in ctx["deals"] if x.status in ("open", "won")], 12):
        add_doc(f"LOI - {d.name[:40]}.pdf", "loi", make_pdf("Letter of Intent", [d.name, f"Proposed price: ${d.price or 0:,}"]), "application/pdf", [("deal", d.id)], next((b for b in brokers if b.id == d.owner_user_id), brokers[0]), when(), visibility="confidential")
    db.flush()
    ctx["activities_count"] = len(activities)
