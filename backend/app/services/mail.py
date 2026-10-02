"""Email and calendar capture (ADR 0014, 0029). Provider-agnostic: a MailProvider interface, with database-backed capture as the first implementation."""
import base64
import hashlib
import hmac
import re
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..db import utcnow
from ..models.core import Company, Contact, ContactEmail, Property
from ..models.core_sys import User
from ..models.deals import Deal, DealParty
from ..models.mail import (VISIBILITY, BulkSend, CalendarAssociation, CalendarEvent, EmailAccountConnection, EmailAssociation, EmailContactShare, EmailMessage, EmailTemplate, ExclusionRule, Unsubscribe)
from .normalize import norm_email
from .search import holdings_of_contact

ADDR_RE = re.compile(r"<([^>]+)>")


# ---------------- provider interface ----------------
class MailProvider(ABC):
    """Everything the CRM needs from a mailbox provider. Microsoft 365 and Google adapters implement this later without changing the stored model."""
    name = "abstract"

    @abstractmethod
    def fetch_new(self, conn: EmailAccountConnection) -> list[dict]: ...

    @abstractmethod
    def send(self, conn: EmailAccountConnection, to: list[str], subject: str, body: str) -> str: ...


class CaptureProvider(MailProvider):
    """Messages arrive through the capture API or BCC-to-CRM; nothing is pulled and nothing can be sent."""
    name = "capture"

    def fetch_new(self, conn):
        return []

    def send(self, conn, to, subject, body):
        raise HTTPException(501, "No mail provider is connected. Choose Microsoft 365 or Google to enable sending (ADR 0029).")


PROVIDERS: dict[str, MailProvider] = {"capture": CaptureProvider()}


def provider_for(conn: EmailAccountConnection | None) -> MailProvider:
    return PROVIDERS.get(conn.provider if conn else "capture", PROVIDERS["capture"])


# ---------------- token encryption ----------------
def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("mail-tokens:" + config.SECRET).encode()).digest()))


def encrypt_tokens(tokens: dict) -> str:
    import json
    return _fernet().encrypt(json.dumps(tokens).encode()).decode()


def decrypt_tokens(blob: str | None) -> dict:
    import json
    return json.loads(_fernet().decrypt(blob.encode())) if blob else {}


# ---------------- helpers ----------------
def clean_addr(a: str) -> str:
    m = ADDR_RE.search(a or "")
    return (m.group(1) if m else (a or "")).strip().lower()


def _addrs(v) -> list[str]:
    return [x for x in (clean_addr(a) for a in (v or [])) if x]


def get_connection(db: Session, user: User, create=True) -> EmailAccountConnection | None:
    c = db.scalar(select(EmailAccountConnection).where(EmailAccountConnection.user_id == user.id))
    if not c and create:
        c = EmailAccountConnection(user_id=user.id, provider="capture", email_address=user.email, scopes=["capture"], bcc_token=secrets.token_urlsafe(24))
        db.add(c)
        db.flush()
    return c


def is_excluded(db: Session, user_id: int, addrs: list[str], text: str) -> str | None:
    low = text.lower()
    for r in db.scalars(select(ExclusionRule).where(ExclusionRule.user_id == user_id)):
        v = r.value.lower()
        if r.kind == "domain" and any(a.endswith("@" + v) or a.endswith("." + v) for a in addrs):
            return f"excluded domain {r.value}"
        if r.kind == "address" and v in addrs:
            return f"excluded address {r.value}"
        if r.kind == "keyword" and v in low:
            return f"excluded keyword {r.value}"
    return None


def match_contacts(db: Session, addrs: list[str]) -> list[Contact]:
    out, seen = [], set()
    for a in addrs:
        n = norm_email(a)
        if not n:
            continue
        for c in db.scalars(select(Contact).join(ContactEmail).where(ContactEmail.normalized == n, Contact.deleted_at.is_(None))):
            if c.id not in seen:
                seen.add(c.id)
                out.append(c)
    return out


def related_records(db: Session, contacts: list[Contact]) -> list[tuple[str, int]]:
    """Related open deals and properties, only where unambiguous (ADR 0014)."""
    out = []
    for c in contacts:
        deals = db.scalars(select(Deal).join(DealParty, DealParty.deal_id == Deal.id).where(DealParty.contact_id == c.id, Deal.status == "open", Deal.deleted_at.is_(None))).unique().all()
        if len(deals) == 1:
            out.append(("deal", deals[0].id))
            if deals[0].property_id:
                out.append(("property", deals[0].property_id))
        else:
            props = holdings_of_contact(db, c.id)
            if len(props) == 1:
                out.append(("property", props[0]["property_id"]))
    return list(dict.fromkeys(out))


def effective_visibility(db: Session, user_id: int, contacts: list[Contact]) -> str:
    best = "private"
    for c in contacts:
        s = db.scalar(select(EmailContactShare).where(EmailContactShare.user_id == user_id, EmailContactShare.contact_id == c.id))
        if s and VISIBILITY.index(s.level) > VISIBILITY.index(best):
            best = s.level
    return best


def _touch(db: Session, contacts: list[Contact], related: list[tuple[str, int]], when: datetime, user_id: int):
    """Email and meetings update last-contact data (ADR 0011, 0014)."""
    for c in contacts:
        if c.last_contact_at is None or c.last_contact_at < when:
            c.last_contact_at, c.last_contact_user_id = when, user_id
    for rt, rid in related:
        if rt == "property":
            p = db.get(Property, rid)
            if p and (p.last_contact_at is None or p.last_contact_at < when):
                p.last_contact_at, p.last_contact_user_id = when, user_id


def capture_message(db: Session, user: User, p: dict, channel: str = "api") -> dict:
    conn = get_connection(db, user)
    from_addr = clean_addr(p["from_addr"])
    to_addrs, cc_addrs = _addrs(p.get("to_addrs")), _addrs(p.get("cc_addrs"))
    if not from_addr or not (to_addrs or cc_addrs):
        raise HTTPException(422, "from_addr and at least one recipient are required")
    sent_at = p.get("sent_at") or utcnow()
    subject = (p.get("subject") or "(no subject)")[:300]
    body = p.get("body") or ""
    why = is_excluded(db, user.id, [from_addr, *to_addrs, *cc_addrs], subject + "\n" + body)
    if why:
        return {"stored": False, "reason": why}  # excluded messages are never stored
    mid = p.get("message_id") or hashlib.sha256(f"{p.get('thread_id')}|{sent_at.isoformat()}|{from_addr}|{subject}".encode()).hexdigest()[:40]
    existing = db.scalar(select(EmailMessage).where(EmailMessage.user_id == user.id, EmailMessage.message_id == mid))
    if existing:
        return {"stored": True, "id": existing.id, "duplicate": True, "reason": "already captured"}
    own = norm_email(conn.email_address) if conn else norm_email(user.email)
    direction = p.get("direction") or ("outbound" if norm_email(from_addr) == own else "inbound")
    if direction not in ("inbound", "outbound"):
        raise HTTPException(422, "direction must be inbound or outbound")
    others = [a for a in [from_addr, *to_addrs, *cc_addrs] if norm_email(a) != own]
    contacts = match_contacts(db, others)
    related = related_records(db, contacts)
    vis = p.get("visibility") or effective_visibility(db, user.id, contacts)
    if vis not in VISIBILITY:
        raise HTTPException(422, f"visibility must be one of {VISIBILITY}")
    m = EmailMessage(user_id=user.id, message_id=mid, thread_id=p.get("thread_id"), subject=subject, body=body, sent_at=sent_at, direction=direction, from_addr=from_addr,
                     to_addrs=to_addrs, cc_addrs=cc_addrs, visibility=vis, channel=channel)
    for c in contacts:
        m.associations.append(EmailAssociation(record_type="contact", record_id=c.id, auto=True))
    for rt, rid in related:
        m.associations.append(EmailAssociation(record_type=rt, record_id=rid, auto=True))
    db.add(m)
    _touch(db, contacts, related, sent_at, user.id)
    conn.last_synced_at = utcnow()
    db.flush()
    out = {"stored": True, "id": m.id, "direction": direction, "associated": {"contacts": [c.id for c in contacts], "related": [{"type": t, "id": i} for t, i in related]}, "visibility": vis}
    if direction == "outbound" and any(c.do_not_contact for c in contacts):
        out["outreach_warning"] = "A recipient is marked do-not-contact"
    return out


def capture_event(db: Session, user: User, p: dict) -> dict:
    ext = p["external_id"]
    attendees = [{"email": clean_addr(a["email"]), "name": a.get("name")} for a in (p.get("attendees") or []) if a.get("email")]
    if p["end"] < p["start"]:
        raise HTTPException(422, "end must not be before start")
    why = is_excluded(db, user.id, [a["email"] for a in attendees], p["title"])
    if why:
        return {"stored": False, "reason": why}
    e = db.scalar(select(CalendarEvent).where(CalendarEvent.user_id == user.id, CalendarEvent.external_id == ext))
    new = e is None
    if new:
        e = CalendarEvent(user_id=user.id, external_id=ext, title=p["title"][:300], start_at=p["start"], end_at=p["end"], location=p.get("location"), attendees=attendees,
                          visibility=p.get("visibility") or "private")
        db.add(e)
    else:
        e.title, e.start_at, e.end_at, e.location, e.attendees = p["title"][:300], p["start"], p["end"], p.get("location"), attendees
        if p.get("visibility"):
            e.visibility = p["visibility"]
    conn = get_connection(db, user)
    own = norm_email(conn.email_address)
    contacts = match_contacts(db, [a["email"] for a in attendees if norm_email(a["email"]) != own])
    related = related_records(db, contacts)
    have = {(a.record_type, a.record_id) for a in e.associations}
    db.flush()
    for rt, rid in [("contact", c.id) for c in contacts] + related:
        if (rt, rid) not in have:
            e.associations.append(CalendarAssociation(record_type=rt, record_id=rid))
    if e.end_at <= utcnow():  # a meeting that already happened counts as contact
        _touch(db, contacts, related, e.end_at, user.id)
    db.flush()
    return {"stored": True, "id": e.id, "created": new, "associated": {"contacts": [c.id for c in contacts], "related": [{"type": t, "id": i} for t, i in related]}}


# ---------------- reading with privacy ----------------
def message_out(m: EmailMessage, viewer: User, names: dict) -> dict | None:
    own = m.user_id == viewer.id
    if not own and m.visibility == "private":
        return None
    level = "team_full" if own else m.visibility
    out = {"id": m.id, "direction": m.direction, "sent_at": m.sent_at, "from_addr": m.from_addr, "to_addrs": m.to_addrs, "cc_addrs": m.cc_addrs, "thread_id": m.thread_id, "visibility": m.visibility,
           "owner_user_id": m.user_id, "owner": names.get(m.user_id), "mine": own, "channel": m.channel,
           "associations": [{"record_type": a.record_type, "record_id": a.record_id, "auto": a.auto} for a in m.associations]}
    if level in ("team_subject", "team_full"):
        out["subject"] = m.subject
    else:
        out["subject"] = None
        out["subject_hidden"] = True
    if level == "team_full":
        out["body"] = m.body
    return out


def event_out(e: CalendarEvent, viewer: User, names: dict) -> dict | None:
    own = e.user_id == viewer.id
    if not own and e.visibility == "private":
        return None
    full = own or e.visibility in ("team_subject", "team_full")
    return {"id": e.id, "title": e.title if full else "Meeting", "start_at": e.start_at, "end_at": e.end_at, "location": e.location if full else None, "owner": names.get(e.user_id), "mine": own, "visibility": e.visibility,
            "attendees": e.attendees if (own or e.visibility == "team_full") else [{"email": a["email"]} for a in e.attendees],
            "associations": [{"record_type": a.record_type, "record_id": a.record_id} for a in e.associations]}


# ---------------- templates, merge fields, bulk, unsubscribe ----------------
MERGE_FIELDS = {"first_name", "last_name", "full_name", "company", "title", "property_address", "property_city", "list_price", "broker_name"}
FIELD_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def validate_template(subject: str, body: str):
    bad = {f for f in FIELD_RE.findall(subject + "\n" + body) if f not in MERGE_FIELDS}
    if bad:
        raise HTTPException(422, f"Unknown merge fields: {sorted(bad)}. Available: {sorted(MERGE_FIELDS)}")


def render(db: Session, t: EmailTemplate, contact: Contact, user: User, listing=None, prop=None) -> dict:
    role = None
    from ..models.core import ContactCompanyRole
    role = db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == contact.id).order_by(ContactCompanyRole.is_primary.desc())).first()
    p = prop or (listing.property if listing else None)
    vals = {"first_name": contact.first_name, "last_name": contact.last_name, "full_name": contact.full_name, "company": role.company.name if role else "", "title": contact.title or "",
            "property_address": p.address if p else "", "property_city": p.city if p else "", "list_price": f"${listing.list_price:,}" if listing and listing.list_price else "", "broker_name": user.name}
    sub = lambda s: FIELD_RE.sub(lambda m: str(vals.get(m.group(1), "")), s)  # noqa: E731
    return {"subject": sub(t.subject), "body": sub(t.body)}


def unsubscribe_token(email: str) -> str:
    return hmac.new(config.SECRET.encode(), f"unsub:{norm_email(email)}".encode(), hashlib.sha256).hexdigest()[:32] + "." + base64.urlsafe_b64encode(norm_email(email).encode()).decode().rstrip("=")


def read_unsubscribe_token(token: str) -> str | None:
    try:
        sig, enc = token.split(".", 1)
        email = base64.urlsafe_b64decode(enc + "=" * (-len(enc) % 4)).decode()
        return email if hmac.compare_digest(sig, unsubscribe_token(email).split(".")[0]) else None
    except Exception:
        return None


def prepare_bulk(db: Session, user: User, name: str, t: EmailTemplate, contacts: list[Contact], listing, list_id) -> BulkSend:
    unsub = {u.email for u in db.scalars(select(Unsubscribe))}
    rows, counts = [], {"eligible": 0, "excluded_dnc": 0, "excluded_unsubscribed": 0, "no_email": 0}
    for c in contacts:
        email = next((e.email for e in c.emails if e.is_primary), c.emails[0].email if c.emails else None)
        if not email:
            st = "no_email"
        elif c.do_not_contact:
            st = "excluded_dnc"
        elif norm_email(email) in unsub:
            st = "excluded_unsubscribed"
        else:
            st = "eligible"
        counts[st] += 1
        r = {"contact_id": c.id, "name": c.full_name, "email": email, "status": st}
        if st == "eligible":
            rendered = render(db, t, c, user, listing)
            r.update(subject=rendered["subject"], unsubscribe_token=unsubscribe_token(email))
        rows.append(r)
    b = BulkSend(name=name, owner_user_id=user.id, template_id=t.id, list_id=list_id, listing_id=listing.id if listing else None, counts=counts, recipients=rows)
    db.add(b)
    db.flush()
    return b
