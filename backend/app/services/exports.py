"""Permission-aware, audited, rate-limited export (ADR 0016, 0017, 0018)."""
import csv
import io
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import log_event
from ..models.core import Company, Contact, ContactCompanyRole, Property, PropertyOwnership
from ..models.core_sys import User
from ..models.deals import Deal
from ..models.pipeline import BuyerInterest, Lead, Listing
from ..models.work import Activity, Note
from ..security import ROLE_ACTIONS, can_see_commission
from . import deals as deals_svc
from . import filters as flt
from .visibility import Visibility

_calls: dict[int, deque] = defaultdict(deque)


def limit_per_hour() -> int:
    return int(os.environ.get("TRG_EXPORT_LIMIT", "20"))


def check_export_allowed(user: User):
    if "export" not in ROLE_ACTIONS.get(user.role, set()):
        raise HTTPException(403, f"Role '{user.role}' may not export")
    now, q = time.time(), _calls[user.id]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= limit_per_hour():
        raise HTTPException(429, f"Export limit reached ({limit_per_hour()} per hour). Try again later.")
    q.append(now)


def reset_limits():
    _calls.clear()


def table_for(db: Session, entity: str, user: User, columns: list[str] | None, flt_def: dict | None, restrict_ids: list[int] | None = None, sort_field=None, sort_dir="asc"):
    fields = flt.fields_for(db, entity, user)
    cols = columns or ["id"] + [k for k in fields if "." not in k or k.startswith("custom.")]
    cols = [c for c in cols if c == "id" or c in fields]
    r = flt.run(db, entity, flt_def, user, [c for c in cols if c != "id"], sort_field, sort_dir, 1, 100000, restrict_ids)
    header = [("id" if c == "id" else fields[c].label) for c in cols]
    rows = [[(it["id"] if c == "id" else it.get(c)) for c in cols] for it in r["items"]]
    return header, rows


def to_csv(header, rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(sheets: dict[str, tuple[list, list]]) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, (header, rows) in sheets.items():
        ws = wb.create_sheet(name[:31])
        ws.append(header)
        for r in rows:
            ws.append(["" if v is None else v for v in r])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(max(len(str(col[0].value or "")) + 2, 10), 40)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def full_export(db: Session, user: User) -> dict[str, tuple[list, list]]:
    """Everything the firm needs to leave with: entities plus relationship history. Field restrictions and note privacy still apply."""
    vis = Visibility(db, user)
    sheets: dict[str, tuple[list, list]] = {}
    for entity, name in (("contact", "Contacts"), ("company", "Companies"), ("property", "Properties"), ("listing", "Listings"), ("deal", "Deals"), ("lead", "Leads")):
        sheets[name] = table_for(db, entity, user, None, None)
    names = {u.id: u.name for u in db.scalars(select(User))}
    own = []
    for o in db.scalars(select(PropertyOwnership).order_by(PropertyOwnership.property_id, PropertyOwnership.acquired_date)):
        if vis.can_see(o.property):
            own.append([o.property_id, o.property.address, o.property.city, o.company.name if o.company else None, o.contact.full_name if o.contact else None, o.ownership_pct, o.acquired_date, o.disposed_date, o.acquisition_price])
    sheets["Ownership history"] = (["property_id", "address", "city", "owner_entity", "owner_person", "ownership_pct", "acquired", "disposed", "acquisition_price"], own)
    roles = [[r.contact_id, r.contact.full_name, r.company_id, r.company.name, r.role, r.is_primary, r.start_date, r.end_date] for r in db.scalars(select(ContactCompanyRole)) if not r.contact.deleted_at and not r.company.deleted_at]
    sheets["Contact-company roles"] = (["contact_id", "contact", "company_id", "company", "role", "primary", "start", "end"], roles)
    acts = []
    for a in db.scalars(select(Activity).where(Activity.status != "cancelled").order_by(Activity.id)):
        acts.append([a.id, a.type, a.subject, a.status, a.due_at, a.completed_at, a.outcome, names.get(a.assignee_user_id), "; ".join(f"{x.record_type}:{x.record_id}" for x in a.associations)])
    sheets["Activities"] = (["id", "type", "subject", "status", "due", "completed", "outcome", "assignee", "records"], acts)
    notes = []
    for n in db.scalars(select(Note).where(Note.deleted_at.is_(None))):
        if n.visibility == "team" or n.author_user_id == user.id:  # metadata only; bodies stay in the CRM
            notes.append([n.id, names.get(n.author_user_id), n.created_at, n.visibility, n.pinned, "; ".join(f"{x.record_type}:{x.record_id}" for x in n.associations), len(n.body)])
    sheets["Notes (metadata)"] = (["id", "author", "created", "visibility", "pinned", "records", "length"], notes)
    bi = [[i.listing_id, i.contact_id, i.stage, i.offer_amount if can_see_commission(user) else None, i.channel] for i in db.scalars(select(BuyerInterest))]
    sheets["Buyer interest"] = (["listing_id", "contact_id", "stage", "offer_amount", "channel"], bi)
    return sheets
