"""CSV/XLSX import (ADR 0016): mapping, preview through the duplicate service, commit, provenance, external IDs, rollback."""
import csv
import io
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import current_actor
from ..db import SessionLocal, utcnow
from ..models.core import (Company, Contact, ContactCompanyRole, ExternalId, Property, PropertyOwnership)
from ..models.core_sys import User
from ..models.imports import IMPORT_ENTITIES, IMPORT_MODES, ImportJob, ImportRow
from ..models.work import ActivityAssociation
from . import dedupe, entities as ent
from .normalize import norm_address, norm_apn, norm_company_name, norm_domain, norm_email, norm_phone

MAX_ROWS = 20000
MAX_BYTES = 5 * 1024 * 1024
CITY_INFO = {  # county, market, submarket used to fill gaps from a city name
    "Irvine": ("Orange", "Orange County", "Central OC"), "Anaheim": ("Orange", "Orange County", "North OC"), "Santa Ana": ("Orange", "Orange County", "Central OC"), "Tustin": ("Orange", "Orange County", "Central OC"),
    "Costa Mesa": ("Orange", "Orange County", "Central OC"), "Fullerton": ("Orange", "Orange County", "North OC"), "Orange": ("Orange", "Orange County", "Central OC"), "Garden Grove": ("Orange", "Orange County", "West OC"),
    "Huntington Beach": ("Orange", "Orange County", "West OC"), "Lake Forest": ("Orange", "Orange County", "South OC"), "Mission Viejo": ("Orange", "Orange County", "South OC"), "Brea": ("Orange", "Orange County", "North OC"),
    "Torrance": ("Los Angeles", "Los Angeles", "South Bay"), "Carson": ("Los Angeles", "Los Angeles", "South Bay"), "Long Beach": ("Los Angeles", "Los Angeles", "South Bay"), "Commerce": ("Los Angeles", "Los Angeles", "Mid-Counties"),
    "Pasadena": ("Los Angeles", "Los Angeles", "San Gabriel Valley"), "Ontario": ("San Bernardino", "Inland Empire", "IE West"), "Rancho Cucamonga": ("San Bernardino", "Inland Empire", "IE West"),
    "Fontana": ("San Bernardino", "Inland Empire", "IE West"), "Chino": ("San Bernardino", "Inland Empire", "IE West"), "Riverside": ("Riverside", "Inland Empire", "IE East"), "Corona": ("Riverside", "Inland Empire", "IE East"),
    "Temecula": ("Riverside", "Inland Empire", "IE South"), "San Diego": ("San Diego", "San Diego", "Central SD"), "Carlsbad": ("San Diego", "San Diego", "North County"), "Oceanside": ("San Diego", "San Diego", "North County"),
}
TYPE_SYNONYMS = {"retail": "retail", "shopping center": "retail", "strip center": "retail", "nnn": "retail", "storefront": "retail", "industrial": "industrial", "warehouse": "industrial", "flex": "industrial", "manufacturing": "industrial", "distribution": "industrial"}

# (field, label, required, aliases). Aliases are matched against normalized headers (lowercase, letters and digits only).
TARGETS: dict[str, list[tuple]] = {
    "contact": [
        ("first_name", "First name", False, ["firstname", "first", "givenname"]), ("last_name", "Last name", False, ["lastname", "last", "surname", "familyname"]),
        ("full_name", "Full name", False, ["fullname", "name", "contactname", "owner", "ownername"]), ("title", "Title", False, ["title", "jobtitle", "position"]),
        ("email", "Email", False, ["email", "emailaddress", "primaryemail"]), ("email2", "Second email", False, ["email2", "secondaryemail", "altemail"]),
        ("phone", "Phone", False, ["phone", "phonenumber", "mobile", "cell", "primaryphone"]), ("phone2", "Second phone", False, ["phone2", "officephone", "workphone", "altphone"]),
        ("address", "Address", False, ["address", "streetaddress", "mailingaddress"]), ("city", "City", False, ["city"]), ("state", "State", False, ["state"]), ("zip", "ZIP", False, ["zip", "zipcode", "postalcode"]),
        ("company_name", "Company / entity", False, ["company", "companyname", "entity", "entityname", "organization"]), ("company_role", "Role at company", False, ["role", "companyrole"]),
        ("contact_types", "Contact types (comma list)", False, ["type", "types", "contacttype", "contacttypes"]), ("tags", "Tags (comma list)", False, ["tags", "tag", "labels"]),
        ("source", "Source", False, ["source", "leadsource"]), ("external_id", "External ID", False, ["externalid", "id", "sourceid", "recordid"]),
    ],
    "company": [
        ("name", "Name", True, ["name", "company", "companyname", "entity", "entityname", "organization"]), ("kind", "Kind", False, ["kind", "type", "entitytype"]), ("website", "Website", False, ["website", "url", "web"]),
        ("address", "Address", False, ["address", "streetaddress"]), ("city", "City", False, ["city"]), ("state", "State", False, ["state"]), ("zip", "ZIP", False, ["zip", "zipcode"]),
        ("tags", "Tags (comma list)", False, ["tags", "tag"]), ("external_id", "External ID", False, ["externalid", "id", "sourceid"]),
    ],
    "property": [
        ("address", "Address", True, ["address", "propertyaddress", "streetaddress", "site"]), ("city", "City", True, ["city", "propertycity"]), ("state", "State", False, ["state"]), ("zip", "ZIP", False, ["zip", "zipcode"]),
        ("apn", "APN", False, ["apn", "parcel", "parcelnumber", "assessorparcelnumber"]), ("county", "County", False, ["county"]), ("property_type", "Property type", True, ["propertytype", "type", "assetclass", "usetype"]),
        ("subtype", "Subtype", False, ["subtype", "propertysubtype", "class"]), ("market", "Market", False, ["market"]), ("submarket", "Submarket", False, ["submarket"]),
        ("building_sf", "Building SF", False, ["buildingsf", "sf", "squarefeet", "rba", "buildingsize"]), ("land_acres", "Land acres", False, ["landacres", "acres", "lotsize"]), ("year_built", "Year built", False, ["yearbuilt", "built"]),
        ("zoning", "Zoning", False, ["zoning", "zone"]), ("noi", "NOI", False, ["noi", "netoperatingincome"]), ("cap_rate_pct", "Cap rate (%)", False, ["caprate", "cap", "caprate%"]),
        ("estimated_value", "Estimated value", False, ["value", "estimatedvalue", "price", "assessedvalue"]), ("lender", "Lender", False, ["lender", "loanlender", "mortgagelender"]),
        ("loan_original_amount", "Original loan amount", False, ["loanamount", "originalloan", "loanoriginalamount", "mortgageamount"]), ("loan_maturity_date", "Loan maturity date", False, ["loanmaturity", "loanmaturitydate", "maturity", "maturitydate"]),
        ("hold_intent", "Hold intent", False, ["holdintent", "intent"]), ("tags", "Tags (comma list)", False, ["tags", "tag"]), ("external_id", "External ID", False, ["externalid", "id", "propertyid", "costarid"]),
    ],
    "owner_properties": [
        ("owner_first", "Owner first name", False, ["ownerfirst", "ownerfirstname", "firstname", "first"]), ("owner_last", "Owner last name", False, ["ownerlast", "ownerlastname", "lastname", "last"]),
        ("owner_full_name", "Owner full name", False, ["ownername", "owner", "principal", "contactname", "fullname"]), ("owner_email", "Owner email", False, ["owneremail", "email"]), ("owner_phone", "Owner phone", False, ["ownerphone", "phone", "mobile"]),
        ("entity_name", "Owner entity (LLC / trust)", False, ["entity", "entityname", "ownerentity", "llc", "owningentity", "company"]), ("entity_kind", "Entity kind", False, ["entitykind", "entitytype"]),
        ("address", "Property address", True, ["address", "propertyaddress", "streetaddress"]), ("city", "City", True, ["city"]), ("zip", "ZIP", False, ["zip", "zipcode"]), ("apn", "APN", False, ["apn", "parcel"]), ("county", "County", False, ["county"]),
        ("property_type", "Property type", True, ["propertytype", "type", "assetclass"]), ("subtype", "Subtype", False, ["subtype"]), ("building_sf", "Building SF", False, ["buildingsf", "sf", "squarefeet"]), ("year_built", "Year built", False, ["yearbuilt"]),
        ("estimated_value", "Estimated value", False, ["value", "estimatedvalue"]), ("lender", "Lender", False, ["lender"]), ("loan_maturity_date", "Loan maturity date", False, ["loanmaturity", "maturity", "maturitydate"]),
        ("acquired_date", "Date acquired", False, ["acquired", "acquireddate", "purchasedate", "saledate"]), ("acquisition_price", "Acquisition price", False, ["acquisitionprice", "purchaseprice", "saleprice"]),
        ("ownership_pct", "Ownership %", False, ["ownershippct", "ownership", "percentowned"]), ("external_id", "Property external ID", False, ["externalid", "propertyid", "costarid"]),
    ],
}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9%]", "", h.lower())


def targets_meta(entity: str, db: Session | None = None) -> list[dict]:
    out = [{"field": f, "label": l, "required": r, "aliases": a} for f, l, r, a in TARGETS[entity]]
    if db is not None and entity != "owner_properties":
        from .custom_fields import definitions
        for d in definitions(db, entity):
            out.append({"field": f"custom.{d.key}", "label": f"{d.label} (custom)", "required": d.required, "aliases": [_norm(d.label), _norm(d.key)]})
    return out


def parse_file(name: str, content: bytes) -> tuple[list[str], list[dict]]:
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "File exceeds the 5 MB import limit")
    if not content:
        raise HTTPException(422, "Empty file")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "xlsx":
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:
            raise HTTPException(422, "Could not read the .xlsx file")
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
        if not rows:
            raise HTTPException(422, "The sheet is empty")
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        body = [[("" if c is None else (c.date().isoformat() if isinstance(c, datetime) else c.isoformat() if isinstance(c, date) else str(c))) for c in r] for r in rows[1:]]
    elif ext in ("csv", "txt", "tsv"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
        if not rows:
            raise HTTPException(422, "The file is empty")
        headers = [h.strip() for h in rows[0]]
        body = rows[1:]
    else:
        raise HTTPException(415, "Import accepts .csv or .xlsx files")
    if not any(headers):
        raise HTTPException(422, "The first row must contain column headers")
    if len(set(headers)) != len(headers):
        raise HTTPException(422, "Column headers must be unique")
    if len(body) > MAX_ROWS:
        raise HTTPException(413, f"Too many rows (limit {MAX_ROWS})")
    dicts = [{h: (r[i].strip() if i < len(r) and isinstance(r[i], str) else (r[i] if i < len(r) else "")) for i, h in enumerate(headers)} for r in body if any((c or "").strip() if isinstance(c, str) else c for c in r)]
    return headers, dicts


def suggest_mapping(entity: str, headers: list[str], db: Session | None = None) -> dict[str, str]:
    mapping, used = {}, set()
    for t in targets_meta(entity, db):
        for h in headers:
            if h in used or not h:
                continue
            if _norm(h) in t["aliases"] or _norm(h) == _norm(t["field"]):
                mapping[t["field"]] = h
                used.add(h)
                break
    return mapping


def validate_mapping(entity: str, mapping: dict, headers: list[str], db: Session):
    if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
        raise HTTPException(422, "mapping must be a JSON object of target field to column name")
    valid = {t["field"] for t in targets_meta(entity, db)}
    for field, col in mapping.items():
        if field not in valid:
            raise HTTPException(422, f"Unknown target field: {field}")
        if col not in headers:
            raise HTTPException(422, f"Mapped column {col!r} is not in the file")
    reqs = [t for t in targets_meta(entity, db) if t["required"] and not t["field"].startswith("custom.")]
    missing = [t["label"] for t in reqs if t["field"] not in mapping]
    if entity == "contact" and not (("last_name" in mapping) or ("full_name" in mapping)):
        missing.append("Last name or Full name")
    if entity == "owner_properties" and not any(k in mapping for k in ("owner_last", "owner_full_name", "entity_name")):
        missing.append("Owner name or Owner entity")
    if missing:
        raise HTTPException(422, f"Map these required fields: {', '.join(missing)}")


# ---------------- value cleaning ----------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RowError(Exception):
    pass


def num(v, label):
    if v in (None, ""):
        return None
    s = re.sub(r"[$,\s]", "", str(v))
    try:
        return int(float(s))
    except ValueError:
        raise RowError(f"{label} must be a number, got {v!r}")


def fnum(v, label):
    if v in (None, ""):
        return None
    try:
        return float(re.sub(r"[,\s]", "", str(v)))
    except ValueError:
        raise RowError(f"{label} must be a number, got {v!r}")


def pdate(v, label):
    if v in (None, ""):
        return None
    s = str(v).strip()[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", str(v)) else str(v).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise RowError(f"{label} must be a date (YYYY-MM-DD or M/D/YYYY), got {v!r}")


def clist(v):
    return [x.strip().lower() for x in re.split(r"[;,|]", str(v)) if x.strip()] if v else []


def pick(row: dict, mapping: dict, field: str):
    col = mapping.get(field)
    if not col:
        return None
    v = row.get(col)
    if isinstance(v, str):
        v = v.strip()
    return v if v not in ("", None) else None


def split_name(full: str):
    parts = full.strip().split()
    return (" ".join(parts[:-1]) or parts[0], parts[-1] if len(parts) > 1 else "(unknown)")


def custom_values(db, entity, row, mapping):
    from .custom_fields import definitions
    out = {}
    for d in definitions(db, entity):
        v = pick(row, mapping, f"custom.{d.key}")
        if v is None:
            continue
        if d.type in ("number", "currency"):
            out[d.key] = fnum(v, d.label)
        elif d.type == "checkbox":
            out[d.key] = str(v).lower() in ("true", "yes", "1", "y")
        elif d.type == "multi_select":
            out[d.key] = clist(v)
        elif d.type == "date":
            out[d.key] = pdate(v, d.label).isoformat()
        else:
            out[d.key] = v
    return out


def contact_payload(db, row, mapping, prefix=""):
    g = lambda f: pick(row, mapping, prefix + f)  # noqa: E731
    first, last = g("first_name") if not prefix else g("first"), g("last_name") if not prefix else g("last")
    full = g("full_name")
    if not last and full:
        first, last = split_name(full)
    if not last:
        raise RowError("Last name (or full name) is required")
    emails = [e for e in (g("email"), g("email2") if not prefix else None) if e]
    for e in emails:
        if not EMAIL_RE.match(e):
            raise RowError(f"Invalid email: {e}")
    phones = [p for p in (g("phone"), g("phone2") if not prefix else None) if p]
    for p in phones:
        if not norm_phone(p):
            raise RowError(f"Invalid phone: {p}")
    return {"first_name": first or "(unknown)", "last_name": last, "emails": emails, "phones": phones}


def property_payload(db, row, mapping):
    g = lambda f: pick(row, mapping, f)  # noqa: E731
    addr, city = g("address"), g("city")
    if not addr or not city:
        raise RowError("Property address and city are required")
    ptype_raw = g("property_type")
    ptype = TYPE_SYNONYMS.get(str(ptype_raw).strip().lower()) if ptype_raw else None
    if not ptype:
        raise RowError(f"Property type must be retail or industrial (or a known synonym), got {ptype_raw!r}")
    info = CITY_INFO.get(city.strip().title())
    d = {"address": addr, "city": city.strip().title() if info else city, "property_type": ptype, "state": (g("state") or "CA")[:2].upper(), "zip": g("zip"), "apn": g("apn"),
         "county": g("county") or (info[0] if info else "Orange"), "subtype": g("subtype"), "market": g("market") or (info[1] if info else None), "submarket": g("submarket") or (info[2] if info else None),
         "building_sf": num(g("building_sf"), "Building SF"), "land_acres": fnum(g("land_acres"), "Land acres"), "year_built": num(g("year_built"), "Year built"), "zoning": g("zoning"),
         "noi": num(g("noi"), "NOI"), "estimated_value": num(g("estimated_value"), "Estimated value"), "lender": g("lender"), "loan_original_amount": num(g("loan_original_amount"), "Loan amount"),
         "loan_maturity_date": pdate(g("loan_maturity_date"), "Loan maturity date")}
    cap = g("cap_rate_pct")
    if cap:
        pct = fnum(str(cap).replace("%", ""), "Cap rate")
        if pct is not None and not (0 < pct < 30):
            raise RowError(f"Cap rate must be a percentage between 0 and 30, got {cap!r}")
        d["cap_rate_bps"] = round(pct * 100) if pct is not None else None
    if g("hold_intent"):
        hi = str(g("hold_intent")).strip().lower().replace(" ", "_")
        if hi not in ("unknown", "hold", "open_to_sell", "selling_soon"):
            raise RowError(f"Hold intent must be unknown, hold, open_to_sell or selling_soon, got {g('hold_intent')!r}")
        d["hold_intent"] = hi
    if g("tags"):
        d["tags"] = clist(g("tags"))
    return {k: v for k, v in d.items() if v is not None}


def company_payload(db, row, mapping, name_field="name", kind_field="kind"):
    g = lambda f: pick(row, mapping, f)  # noqa: E731
    name = g(name_field)
    if not name:
        raise RowError("Company / entity name is required")
    kind = (g(kind_field) or "").strip().lower().replace(" ", "_").replace("/", "_") or None
    if kind and kind not in ("llc", "trust", "fund", "family_office", "brokerage", "lender", "corporation", "other"):
        raise RowError(f"Company kind {kind!r} is not recognized")
    if not kind:
        low = name.lower()
        kind = "trust" if "trust" in low else "corporation" if re.search(r"\b(inc|corp)\b", low) else "llc"
    return {"name": name, "kind": kind}


# ---------------- lookups ----------------
def ext_lookup(db, job, entity, ext_id):
    if not ext_id:
        return None
    x = db.scalar(select(ExternalId).where(ExternalId.entity == entity, ExternalId.system == job.source_name, ExternalId.external_id == str(ext_id)))
    if not x:
        return None
    M = {"contact": Contact, "company": Company, "property": Property}[entity]
    o = db.get(M, x.entity_id)
    return o if o and not o.deleted_at else None


def _stamp(obj, job):
    obj.source, obj.import_job_id, obj.imported_at = job.source_name, job.id, utcnow()


def _record_ext(db, job, entity, obj, ext_id, row):
    if ext_id and not db.scalar(select(ExternalId).where(ExternalId.entity == entity, ExternalId.system == job.source_name, ExternalId.external_id == str(ext_id))):
        x = ExternalId(entity=entity, entity_id=obj.id, system=job.source_name, external_id=str(ext_id))
        db.add(x)
        db.flush()
        row["created_ids"].setdefault("external_id", []).append(x.id)


# ---------------- row processing ----------------
def process_row(db: Session, job: ImportJob, raw: dict, apply: bool, ctx: dict, user_id: int) -> dict:
    """Returns {action, message, details, created_ids, updated_ids}. With apply=False nothing is written (preview)."""
    out = {"action": "error", "message": None, "details": {}, "created_ids": {}, "updated_ids": {}}
    try:
        fn = {"contact": _row_contact, "company": _row_company, "property": _row_property, "owner_properties": _row_owner_properties}[job.entity]
        fn(db, job, raw, apply, ctx, user_id, out)
    except RowError as e:
        out.update(action="error", message=str(e))
    except HTTPException as e:
        out.update(action="error", message=str(e.detail) if isinstance(e.detail, str) else (e.detail.get("message") if isinstance(e.detail, dict) else str(e.detail)))
    return out


def _vkey(ctx, kind, key):
    return ctx.setdefault("virtual", {}).get((kind, key))


def _set_v(ctx, kind, key, row_no):
    ctx.setdefault("virtual", {})[(kind, key)] = row_no


def _find_contact(db, job, payload, ext, ctx, company_names=()):
    c = ext_lookup(db, job, "contact", ext)
    if c:
        return c, "external id", None
    d, p = dedupe.contact_matches(db, payload["emails"], payload["phones"], payload["first_name"], payload["last_name"], company_names)
    if d:
        o, why = next(iter(d.values()))
        return o, why, None
    for e in [norm_email(x) for x in payload["emails"]] + [norm_phone(x) for x in payload["phones"]] + [f"{payload['first_name']} {payload['last_name']}".lower()]:
        if e and _vkey(ctx, "contact", e):
            return None, "same as an earlier row", _vkey(ctx, "contact", e)
    return None, None, (next(iter(p.values())) if p else None)


def _row_contact(db, job, raw, apply, ctx, user_id, out):
    m = job.mapping
    payload = contact_payload(db, raw, m)
    g = lambda f: pick(raw, m, f)  # noqa: E731
    extra = {"title": g("title"), "address": g("address"), "city": g("city"), "state": (g("state") or "")[:2].upper() or None, "zip": g("zip")}
    extra = {k: v for k, v in extra.items() if v}
    types = clist(g("contact_types"))
    bad = [t for t in types if t not in ("owner", "buyer", "investor", "lender", "attorney", "tenant", "broker", "other")]
    if bad:
        raise RowError(f"Unknown contact type: {', '.join(bad)}")
    cust = custom_values(db, "contact", raw, m)
    co_name = g("company_name")
    existing, via, virtual = _find_contact(db, job, payload, g("external_id"), ctx, [co_name] if co_name else [])
    if virtual is not None and existing is None and via:
        out.update(action="duplicate" if job.mode == "create" else "update", message=f"Same person as row {virtual}")
        out["details"]["contact"] = "same as earlier row"
        return
    if existing is not None:
        out["details"]["contact"] = f"matches #{existing.id} ({via})"
        if job.mode == "create":
            out.update(action="duplicate", message=f"Already exists: {existing.full_name} (same {via})")
            return
        out.update(action="update", message=f"Updates {existing.full_name}")
        if apply:
            have_e = {e.normalized for e in existing.emails}
            have_p = {p.normalized for p in existing.phones}
            data = dict(extra)
            if payload["emails"] or payload["phones"]:
                data["emails"] = [{"email": e.email, "label": e.label, "is_primary": e.is_primary} for e in existing.emails] + [{"email": e} for e in payload["emails"] if norm_email(e) not in have_e]
                data["phones"] = [{"phone": p.phone, "label": p.label, "is_primary": p.is_primary} for p in existing.phones] + [{"phone": p} for p in payload["phones"] if norm_phone(p) not in have_p]
            if types:
                data["contact_types"] = sorted(set(existing.contact_types or []) | set(types))
            if g("tags"):
                data["tags"] = sorted(set(existing.tags or []) | set(clist(g("tags"))))
            if cust:
                data["custom"] = cust
            ent.update_contact(db, existing, data)
            if co_name:
                _link_company(db, job, existing, co_name, g("company_role"), apply, out, user_id)
            _record_ext(db, job, "contact", existing, g("external_id"), out)
            out["updated_ids"]["contact"] = [existing.id]
        return
    if job.mode == "update":
        out.update(action="skip", message="No matching contact to update")
        return
    out.update(action="create", message="Creates a contact")
    if isinstance(virtual, tuple):  # a fuzzy (possible) duplicate: created anyway and queued for human review
        out["details"]["possible_duplicate"] = virtual[0].full_name
        out["message"] += f" (possible duplicate of {virtual[0].full_name}, queued for review)"
    if apply:
        data = {**payload, **extra, "contact_types": types, "source": job.source_name, "tags": clist(g("tags"))}
        if cust:
            data["custom"] = cust
        data["emails"] = [{"email": e} for e in payload["emails"]]
        data["phones"] = [{"phone": p} for p in payload["phones"]]
        c = ent.create_contact(db, data, user_id)
        _stamp(c, job)
        out["created_ids"]["contact"] = [c.id]
        if co_name:
            _link_company(db, job, c, co_name, g("company_role"), apply, out, user_id)
        _record_ext(db, job, "contact", c, g("external_id"), out)
    else:
        for e in [norm_email(x) for x in payload["emails"]] + [norm_phone(x) for x in payload["phones"]]:
            if e:
                _set_v(ctx, "contact", e, raw.get("__row__"))
        if co_name:
            out["details"]["company"] = "will link or create " + co_name


def _link_company(db, job, contact, co_name, role, apply, out, user_id):
    d, _ = dedupe.company_matches(db, co_name)
    if d:
        co = next(iter(d.values()))[0]
        out["details"]["company"] = f"linked {co.name}"
    else:
        co = ent.create_company(db, {"name": co_name, "kind": "trust" if "trust" in co_name.lower() else "llc", "source": job.source_name}, user_id)
        _stamp(co, job)
        out["created_ids"].setdefault("company", []).append(co.id)
        out["details"]["company"] = f"created {co.name}"
    if not db.scalar(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == contact.id, ContactCompanyRole.company_id == co.id)):
        role_key = (role or "principal").strip().lower().replace(" ", "_")
        r = ContactCompanyRole(contact_id=contact.id, company_id=co.id, role=role_key if role_key in ("principal", "manager", "asset_manager", "representative", "attorney", "employee") else "principal", is_primary=True)
        db.add(r)
        db.flush()
        out["created_ids"].setdefault("role", []).append(r.id)
    return co


def _row_company(db, job, raw, apply, ctx, user_id, out):
    m = job.mapping
    p = company_payload(db, raw, m)
    g = lambda f: pick(raw, m, f)  # noqa: E731
    extra = {k: v for k, v in {"website": g("website"), "address": g("address"), "city": g("city"), "state": (g("state") or "")[:2].upper() or None, "zip": g("zip")}.items() if v}
    cust = custom_values(db, "company", raw, m)
    existing = ext_lookup(db, job, "company", g("external_id"))
    via = "external id"
    if not existing:
        d, poss = dedupe.company_matches(db, p["name"], extra.get("website"), extra.get("address"), extra.get("city"))
        if d:
            existing, via = next(iter(d.values()))
    key = norm_company_name(p["name"])
    if not existing and _vkey(ctx, "company", key):
        out.update(action="duplicate" if job.mode == "create" else "update", message=f"Same entity as row {_vkey(ctx, 'company', key)}")
        return
    if existing:
        if job.mode == "create":
            out.update(action="duplicate", message=f"Already exists: {existing.name} (same {via})")
            return
        out.update(action="update", message=f"Updates {existing.name}")
        if apply:
            data = dict(extra)
            if g("tags"):
                data["tags"] = sorted(set(existing.tags or []) | set(clist(g("tags"))))
            if cust:
                data["custom"] = cust
            if g("kind"):
                data["kind"] = p["kind"]
            ent.update_company(db, existing, data)
            _record_ext(db, job, "company", existing, g("external_id"), out)
            out["updated_ids"]["company"] = [existing.id]
        return
    if job.mode == "update":
        out.update(action="skip", message="No matching company to update")
        return
    out.update(action="create", message="Creates a company")
    if apply:
        data = {**p, **extra, "source": job.source_name, "tags": clist(g("tags"))}
        if cust:
            data["custom"] = cust
        co = ent.create_company(db, data, user_id)
        _stamp(co, job)
        out["created_ids"]["company"] = [co.id]
        _record_ext(db, job, "company", co, g("external_id"), out)
    else:
        _set_v(ctx, "company", key, raw.get("__row__"))


def _find_property(db, job, p, ext, ctx):
    o = ext_lookup(db, job, "property", ext)
    if o:
        return o, "external id"
    d, _ = dedupe.property_matches(db, p["address"], p["city"], p.get("apn"), p.get("county"))
    if d:
        return next(iter(d.values()))
    return None, None


def _row_property(db, job, raw, apply, ctx, user_id, out):
    m = job.mapping
    p = property_payload(db, raw, m)
    cust = custom_values(db, "property", raw, m)
    existing, via = _find_property(db, job, p, pick(raw, m, "external_id"), ctx)
    key = norm_apn(p.get("apn")) or norm_address(p["address"], p["city"])
    if not existing and _vkey(ctx, "property", key):
        out.update(action="duplicate" if job.mode == "create" else "update", message=f"Same property as row {_vkey(ctx, 'property', key)}")
        return
    if existing:
        if job.mode == "create":
            out.update(action="duplicate", message=f"Already exists: {existing.address}, {existing.city} (same {via})")
            return
        out.update(action="update", message=f"Updates {existing.address}")
        if apply:
            data = {k: v for k, v in p.items() if k not in ("address", "city", "state") or v}
            if "tags" in data:
                data["tags"] = sorted(set(existing.tags or []) | set(data["tags"]))
            if cust:
                data["custom"] = cust
            ent.update_property(db, existing, data)
            _record_ext(db, job, "property", existing, pick(raw, m, "external_id"), out)
            out["updated_ids"]["property"] = [existing.id]
        return
    if job.mode == "update":
        out.update(action="skip", message="No matching property to update")
        return
    out.update(action="create", message="Creates a property")
    if apply:
        data = {**p, "source": job.source_name}
        if cust:
            data["custom"] = cust
        obj = ent.create_property(db, data, user_id)
        _stamp(obj, job)
        out["created_ids"]["property"] = [obj.id]
        _record_ext(db, job, "property", obj, pick(raw, m, "external_id"), out)
    else:
        _set_v(ctx, "property", key, raw.get("__row__"))


def _row_owner_properties(db, job, raw, apply, ctx, user_id, out):
    """One row = owner (person) + holding entity + property + ownership. Existing records are linked, never duplicated."""
    m = job.mapping
    g = lambda f: pick(raw, m, f)  # noqa: E731
    prop = property_payload(db, raw, m)
    ent_name = g("entity_name")
    have_person = bool(g("owner_last") or g("owner_full_name"))
    person = None
    if have_person:
        pm = {"first_name": m.get("owner_first"), "last_name": m.get("owner_last"), "full_name": m.get("owner_full_name"), "email": m.get("owner_email"), "phone": m.get("owner_phone")}
        person = contact_payload(db, raw, {k: v for k, v in pm.items() if v})
    if not ent_name and not person:
        raise RowError("Each row needs an owner name or an owner entity")
    acquired = pdate(g("acquired_date"), "Date acquired")
    pct = fnum(g("ownership_pct"), "Ownership %") or 100.0
    if not (0 < pct <= 100):
        raise RowError("Ownership % must be between 0 and 100")
    price = num(g("acquisition_price"), "Acquisition price")
    det = out["details"]
    # ----- contact
    contact = None
    if person:
        contact, via, virt = _find_contact(db, job, person, None, ctx, [ent_name] if ent_name else [])
        if contact is not None:
            det["contact"] = f"linked #{contact.id}"
        elif virt is not None and not isinstance(virt, tuple):
            det["contact"] = f"same as row {virt}"
        else:
            det["contact"] = "created"
            if apply:
                contact = ent.create_contact(db, {**person, "contact_types": ["owner"], "source": job.source_name, "tags": [], "emails": [{"email": e} for e in person["emails"]], "phones": [{"phone": x} for x in person["phones"]]}, user_id)
                _stamp(contact, job)
                out["created_ids"].setdefault("contact", []).append(contact.id)
            else:
                for e in [norm_email(x) for x in person["emails"]] + [norm_phone(x) for x in person["phones"]]:
                    if e:
                        _set_v(ctx, "contact", e, raw.get("__row__"))
                _set_v(ctx, "contact", f"{person['first_name']} {person['last_name']}".lower(), raw.get("__row__"))
    # ----- entity
    company = None
    if ent_name:
        cp = company_payload(db, raw, {"name": m["entity_name"], **({"kind": m["entity_kind"]} if "entity_kind" in m else {})})
        d, _ = dedupe.company_matches(db, cp["name"])
        if d:
            company = next(iter(d.values()))[0]
            det["entity"] = f"linked {company.name}"
        elif _vkey(ctx, "company", norm_company_name(cp["name"])):
            det["entity"] = f"same as row {_vkey(ctx, 'company', norm_company_name(cp['name']))}"
        else:
            det["entity"] = f"created {cp['name']}"
            if apply:
                company = ent.create_company(db, {**cp, "source": job.source_name}, user_id)
                _stamp(company, job)
                out["created_ids"].setdefault("company", []).append(company.id)
            else:
                _set_v(ctx, "company", norm_company_name(cp["name"]), raw.get("__row__"))
    # ----- property
    existing, via = _find_property(db, job, prop, g("external_id"), ctx)
    pkey = norm_apn(prop.get("apn")) or norm_address(prop["address"], prop["city"])
    obj = existing
    changed = False
    if existing:
        det["property"] = f"linked #{existing.id} ({via})"
        if job.mode != "create" and apply:
            ent.update_property(db, existing, {k: v for k, v in prop.items() if k not in ("address", "city", "state")})
            out["updated_ids"].setdefault("property", []).append(existing.id)
            changed = True
        elif job.mode != "create":
            changed = True
    elif _vkey(ctx, "property", pkey):
        det["property"] = f"same as row {_vkey(ctx, 'property', pkey)}"
    else:
        if job.mode == "update":
            out.update(action="skip", message="No matching property to update")
            return
        det["property"] = "created"
        changed = True
        if apply:
            obj = ent.create_property(db, {**prop, "source": job.source_name}, user_id)
            _stamp(obj, job)
            out["created_ids"].setdefault("property", []).append(obj.id)
            _record_ext(db, job, "property", obj, g("external_id"), out)
        else:
            _set_v(ctx, "property", pkey, raw.get("__row__"))
    # ----- role + ownership
    if apply:
        if contact and company and not db.scalar(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == contact.id, ContactCompanyRole.company_id == company.id)):
            r = ContactCompanyRole(contact_id=contact.id, company_id=company.id, role="principal", is_primary=True)
            db.add(r)
            db.flush()
            out["created_ids"].setdefault("role", []).append(r.id)
        owner_company, owner_contact = company, (contact if not company else None)
        cur = db.scalars(select(PropertyOwnership).where(PropertyOwnership.property_id == obj.id, PropertyOwnership.disposed_date.is_(None))).all()
        same = [o for o in cur if (owner_company and o.company_id == owner_company.id) or (owner_contact and o.contact_id == owner_contact.id)]
        if same:
            det["ownership"] = "already recorded"
        elif cur and not acquired:
            det["ownership"] = "kept existing owner (no acquisition date to record a change)"
        else:
            o = ent.transfer_ownership(db, obj, {"company_id": owner_company.id if owner_company else None, "contact_id": owner_contact.id if owner_contact else None, "ownership_pct": pct,
                                                 "acquired_date": acquired, "acquisition_price": price, "dispose_current": bool(cur) and pct >= 100})
            out["created_ids"].setdefault("ownership", []).append(o.id)
            det["ownership"] = "recorded"
            changed = True
    else:
        det["ownership"] = "will be recorded"
    if apply:
        created_any = bool(out["created_ids"].get("contact") or out["created_ids"].get("company") or out["created_ids"].get("property"))
    else:
        created_any = any(isinstance(v, str) and v.startswith("created") for v in det.values())
    out["action"] = "create" if created_any else ("update" if changed or det.get("ownership") in ("recorded", "will be recorded") else "skip")
    out["message"] = "; ".join(f"{k}: {v}" for k, v in det.items())


# ---------------- job lifecycle ----------------
def run_preview(db: Session, job: ImportJob, rows: list[dict], user_id: int) -> dict:
    db.query(ImportRow).filter(ImportRow.job_id == job.id).delete()
    ctx: dict = {}
    counts = {"create": 0, "update": 0, "skip": 0, "duplicate": 0, "error": 0}
    for i, raw in enumerate(rows, start=2):  # row 1 is the header
        raw = {**raw, "__row__": i}
        res = process_row(db, job, raw, False, ctx, user_id)
        counts[res["action"]] += 1
        db.add(ImportRow(job_id=job.id, row_no=i, raw={k: v for k, v in raw.items() if k != "__row__"}, action=res["action"], message=res["message"], details=res["details"]))
    job.counts, job.total_rows, job.status = counts, len(rows), "previewed"
    db.flush()
    return counts


def commit_job(job_id: int, user_id: int, actor_name: str):
    """Background task: process unprocessed rows, one session per row so a bad row cannot poison the rest."""
    with SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        db.info["actor"], db.info["actor_id"] = actor_name, user_id
        current_actor.set(actor_name)
        job.status, job.started_at = "running", job.started_at or utcnow()
        db.commit()
        row_ids = [r.id for r in db.scalars(select(ImportRow).where(ImportRow.job_id == job_id, ImportRow.processed.is_(False)).order_by(ImportRow.row_no)) if r.action in ("create", "update")]
        skipped = db.scalars(select(ImportRow).where(ImportRow.job_id == job_id, ImportRow.processed.is_(False), ImportRow.action.in_(("skip", "duplicate", "error")))).all()
        for r in skipped:
            r.processed = True
        db.commit()
    ctx: dict = {}
    for rid in row_ids:
        with SessionLocal() as s:
            s.info["actor"], s.info["actor_id"] = actor_name, user_id
            job = s.get(ImportJob, job_id)
            row = s.get(ImportRow, rid)
            try:
                res = process_row(s, job, {**row.raw, "__row__": row.row_no}, True, ctx, user_id)
                if res["action"] == "error":
                    s.rollback()
                    s.expire_all()
                    row = s.get(ImportRow, rid)
                    row.action, row.message = "error", res["message"]
                else:
                    row.action, row.message, row.details = res["action"], res["message"], res["details"]
                    row.created_ids, row.updated_ids = res["created_ids"], res["updated_ids"]
                row.processed = True
                s.commit()
            except Exception as e:  # noqa: BLE001
                s.rollback()
                with SessionLocal() as s2:
                    r2 = s2.get(ImportRow, rid)
                    r2.action, r2.message, r2.processed = "error", f"Unexpected error: {e}", True
                    s2.commit()
    with SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        rows = db.scalars(select(ImportRow).where(ImportRow.job_id == job_id)).all()
        counts = {"create": 0, "update": 0, "skip": 0, "duplicate": 0, "error": 0}
        made = {"contacts": 0, "companies": 0, "properties": 0, "ownerships": 0}
        for r in rows:
            counts[r.action] += 1
            made["contacts"] += len(r.created_ids.get("contact", []))
            made["companies"] += len(r.created_ids.get("company", []))
            made["properties"] += len(r.created_ids.get("property", []))
            made["ownerships"] += len(r.created_ids.get("ownership", []))
        job.counts, job.summary, job.status, job.finished_at = counts, {"records_created": made}, "completed", utcnow()
        db.commit()


def rollback_job(db: Session, job: ImportJob) -> dict:
    """Undo an import: delete records it created that are still unmodified (ADR 0016)."""
    if job.status not in ("completed",):
        raise HTTPException(409, f"Only completed imports can be rolled back (this one is {job.status})")
    cutoff = (job.finished_at or utcnow()) + timedelta(seconds=2)
    kept, removed = [], {"contacts": 0, "companies": 0, "properties": 0}
    rows = db.scalars(select(ImportRow).where(ImportRow.job_id == job.id)).all()
    from ..models.deals import DealParty
    from ..models.pipeline import Listing
    for r in rows:
        cid = r.created_ids or {}
        for kind, Model, label in (("contact", Contact, "contacts"), ("company", Company, "companies"), ("property", Property, "properties")):
            for i in cid.get(kind, []):
                o = db.get(Model, i)
                if not o or o.deleted_at:
                    continue
                touched = o.updated_at > cutoff
                if not touched:
                    touched = bool(db.scalar(select(ActivityAssociation.id).where(ActivityAssociation.record_type == kind, ActivityAssociation.record_id == i)))
                if not touched and kind == "property":
                    touched = bool(db.scalar(select(Listing.id).where(Listing.property_id == i)))
                if not touched and kind in ("contact", "company"):
                    touched = bool(db.scalar(select(DealParty.id).where(getattr(DealParty, f"{kind}_id") == i)))
                if touched:
                    kept.append({"entity": kind, "id": i, "reason": "modified or used after import"})
                    continue
                o.deleted_at = utcnow()
                removed[label] += 1
        for oid in cid.get("ownership", []):
            ow = db.get(PropertyOwnership, oid)
            if ow:
                prop = db.get(Property, ow.property_id)
                if prop and prop.deleted_at:
                    db.delete(ow)
        for rid in cid.get("role", []):
            ro = db.get(ContactCompanyRole, rid)
            if ro and (ro.contact.deleted_at or ro.company.deleted_at):
                db.delete(ro)
        for xid in cid.get("external_id", []):
            x = db.get(ExternalId, xid)
            if x:
                M = {"contact": Contact, "company": Company, "property": Property}[x.entity]
                tgt = db.get(M, x.entity_id)
                if tgt is None or tgt.deleted_at:
                    db.delete(x)
    job.status, job.rolled_back_at = "rolled_back", utcnow()
    job.summary = {**(job.summary or {}), "rollback": {"removed": removed, "kept": kept}}
    db.flush()
    return job.summary["rollback"]
