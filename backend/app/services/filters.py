"""One filter engine for lists, views, search filters, exports and workflow rules (ADR 0015, ADR 0032)."""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models.core import Company, Contact, ContactCompanyRole, Property, PropertyOwnership
from ..models.core_sys import User
from ..models.deals import Deal
from ..models.pipeline import Lead, Listing
from ..models.platform import FieldDefinition
from ..security import can_see_commission
from . import deals as deals_svc
from .search import current_owners, holdings_of_contact
from .visibility import Visibility

ENTITY_MODELS = {"contact": Contact, "company": Company, "property": Property, "listing": Listing, "deal": Deal, "lead": Lead}

OPS = {
    "text": ["eq", "ne", "contains", "starts_with", "in", "is_null", "not_null"],
    "number": ["eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "is_null", "not_null"],
    "money": ["eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "is_null", "not_null"],
    "date": ["eq", "ne", "gt", "gte", "lt", "lte", "between", "within_days", "older_than_days", "is_null", "not_null"],
    "bool": ["eq"],
    "enum": ["eq", "ne", "in", "is_null", "not_null"],
    "list": ["contains", "not_contains", "is_empty", "not_empty"],
    "user": ["eq", "ne", "in", "is_null", "not_null"],
}


@dataclass
class F:
    key: str
    label: str
    type: str
    getter: Callable[[Session, Any, dict], Any]
    group: str = "Fields"
    options: list = field(default_factory=list)
    restricted: bool = False
    multi: bool = False


# ---------- relation helpers (cached per evaluation) ----------
def _cache(ctx, key, fn):
    if key not in ctx:
        ctx[key] = fn()
    return ctx[key]


def props_of_contact(db, c, ctx) -> list[Property]:
    def load():
        ids = [h["property_id"] for h in holdings_of_contact(db, c.id)]
        return [db.get(Property, i) for i in ids]
    return _cache(ctx, ("pc", c.id), load)


def props_of_company(db, co, ctx) -> list[Property]:
    return _cache(ctx, ("pco", co.id), lambda: [o.property for o in db.scalars(select(PropertyOwnership).where(PropertyOwnership.company_id == co.id, PropertyOwnership.disposed_date.is_(None)))])


def roles_of_contact(db, c, ctx):
    return _cache(ctx, ("rc", c.id), lambda: db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.contact_id == c.id)).all())


def owners_of_property(db, p, ctx):
    return _cache(ctx, ("op", p.id), lambda: current_owners(db, p.id))


def hold_years(db, p, ctx):
    from .entities import hold_years as hy
    return _cache(ctx, ("hy", p.id), lambda: hy(db, p))


def _d(v):
    return v.date() if isinstance(v, datetime) else v


def _tags(o):
    return list(o.tags or [])


def _prop_fields(prefix: str, get: Callable, group: str, multi=False) -> list[F]:
    """Property attributes reachable from another entity (e.g. holdings.loan_maturity_date)."""
    spec = [("city", "City", "text"), ("property_type", "Property type", "enum"), ("market", "Market", "enum"), ("estimated_value", "Value", "money"),
            ("loan_maturity_date", "Loan maturity", "date"), ("hold_intent", "Hold intent", "enum"), ("building_sf", "Building SF", "number"), ("address", "Address", "text")]
    out = []
    for k, label, t in spec:
        opts = {"property_type": ["retail", "industrial"], "hold_intent": ["unknown", "hold", "open_to_sell", "selling_soon"], "market": ["Orange County", "Los Angeles", "Inland Empire", "San Diego"]}.get(k, [])
        out.append(F(f"{prefix}.{k}", f"{group}: {label}", t, (lambda kk: lambda db, o, ctx: [getattr(p, kk) for p in get(db, o, ctx)])(k), group, opts, multi=True))
    return out


def registry(entity: str) -> list[F]:
    me = lambda k: (lambda db, o, ctx: getattr(o, k))  # noqa: E731
    base_user = F("owner_user_id", "Broker", "user", me("owner_user_id"), "Record")
    if entity == "contact":
        return [
            F("full_name", "Name", "text", me("full_name")), F("title", "Title", "text", me("title")), F("city", "City", "text", me("city")),
            F("status", "Status", "enum", me("status"), options=["active", "inactive"]),
            F("lifecycle_stage", "Lifecycle stage", "enum", me("lifecycle_stage"), options=["prospect", "active_relationship", "client", "past_client", "inactive"]),
            F("contact_types", "Contact types", "list", lambda db, o, ctx: o.contact_types or [], options=["owner", "buyer", "investor", "lender", "attorney", "tenant", "broker", "other"]),
            F("tags", "Tags", "list", lambda db, o, ctx: _tags(o)), base_user, F("last_contact_at", "Last contact", "date", lambda db, o, ctx: _d(o.last_contact_at)),
            F("do_not_contact", "Do not contact", "bool", me("do_not_contact")), F("source", "Source", "text", me("source")), F("created_at", "Created", "date", lambda db, o, ctx: _d(o.created_at)),
            F("email", "Email", "text", lambda db, o, ctx: [e.email for e in o.emails], multi=True), F("phone", "Phone", "text", lambda db, o, ctx: [p.phone for p in o.phones], multi=True),
            F("company.name", "Company: Name", "text", lambda db, o, ctx: [r.company.name for r in roles_of_contact(db, o, ctx)], "Company", multi=True),
            F("company.kind", "Company: Kind", "enum", lambda db, o, ctx: [r.company.kind for r in roles_of_contact(db, o, ctx)], "Company", ["llc", "trust", "fund", "family_office", "corporation", "lender", "brokerage", "other"], multi=True),
            F("holdings_count", "Properties held", "number", lambda db, o, ctx: len(props_of_contact(db, o, ctx)), "Holdings"),
            *_prop_fields("holdings", props_of_contact, "Holdings", multi=True),
        ]
    if entity == "company":
        return [
            F("name", "Name", "text", me("name")), F("kind", "Kind", "enum", me("kind"), options=["llc", "trust", "fund", "family_office", "corporation", "lender", "brokerage", "other"]), F("city", "City", "text", me("city")),
            F("tags", "Tags", "list", lambda db, o, ctx: _tags(o)), base_user, F("last_contact_at", "Last contact", "date", lambda db, o, ctx: _d(o.last_contact_at)),
            F("properties_count", "Properties held", "number", lambda db, o, ctx: len(props_of_company(db, o, ctx)), "Holdings"),
            F("portfolio_value", "Portfolio value", "money", lambda db, o, ctx: sum(p.estimated_value or 0 for p in props_of_company(db, o, ctx)), "Holdings"),
            F("principals.name", "Principal: Name", "text", lambda db, o, ctx: [r.contact.full_name for r in db.scalars(select(ContactCompanyRole).where(ContactCompanyRole.company_id == o.id))], "Principals", multi=True),
            *_prop_fields("holdings", props_of_company, "Holdings", multi=True),
        ]
    if entity == "property":
        owner_names = lambda db, o, ctx: [x["company"] or x.get("name") for x in owners_of_property(db, o, ctx)]  # noqa: E731
        return [
            F("address", "Address", "text", me("address")), F("city", "City", "text", me("city")), F("county", "County", "text", me("county")),
            F("property_type", "Property type", "enum", me("property_type"), options=["retail", "industrial"]), F("subtype", "Subtype", "text", me("subtype")),
            F("market", "Market", "enum", me("market"), options=["Orange County", "Los Angeles", "Inland Empire", "San Diego"]), F("submarket", "Submarket", "text", me("submarket")),
            F("building_sf", "Building SF", "number", me("building_sf")), F("land_acres", "Land acres", "number", me("land_acres")), F("year_built", "Year built", "number", me("year_built")),
            F("noi", "NOI", "money", me("noi")), F("cap_rate_bps", "Cap rate (bps)", "number", me("cap_rate_bps")), F("estimated_value", "Value", "money", me("estimated_value")),
            F("loan_maturity_date", "Loan maturity", "date", me("loan_maturity_date")), F("lender", "Lender", "text", me("lender")),
            F("hold_intent", "Hold intent", "enum", me("hold_intent"), options=["unknown", "hold", "open_to_sell", "selling_soon"]),
            F("hold_years", "Hold period (years)", "number", lambda db, o, ctx: hold_years(db, o, ctx), "Ownership"),
            F("last_contact_at", "Last contact", "date", lambda db, o, ctx: _d(o.last_contact_at)), F("tags", "Tags", "list", lambda db, o, ctx: _tags(o)), base_user,
            F("owner.name", "Owner: Name", "text", owner_names, "Ownership", multi=True),
            F("owner.kind", "Owner: Kind", "enum", lambda db, o, ctx: [db.get(Company, x["company_id"]).kind for x in owners_of_property(db, o, ctx) if x["company_id"]], "Ownership", ["llc", "trust", "fund", "family_office", "corporation"], multi=True),
            F("principal.name", "Principal: Name", "text", lambda db, o, ctx: [p["name"] for x in owners_of_property(db, o, ctx) for p in x["principals"]], "Ownership", multi=True),
            F("has_active_listing", "Has active listing", "bool", lambda db, o, ctx: bool(db.scalar(select(Listing.id).where(Listing.property_id == o.id, Listing.status.in_(["active", "under_contract"]), Listing.deleted_at.is_(None)))), "Pipeline"),
        ]
    if entity == "listing":
        prop = lambda k: (lambda db, o, ctx: getattr(o.property, k))  # noqa: E731
        return [
            F("status", "Status", "enum", me("status"), options=["prospect", "active", "under_contract", "closed", "expired", "withdrawn"]), F("list_price", "List price", "money", me("list_price")),
            F("sold_price", "Sold price", "money", me("sold_price")), F("agreement_date", "Agreement date", "date", me("agreement_date")), F("expiration_date", "Expiration", "date", me("expiration_date")),
            F("days_on_market", "Days on market", "number", lambda db, o, ctx: ((o.closed_date if o.status == "closed" and o.closed_date else date.today()) - o.active_date).days if o.active_date else None),
            F("confidential", "Confidential", "bool", me("confidential")), base_user, F("commission_rate_bps", "Commission (bps)", "number", me("commission_rate_bps"), restricted=True),
            F("property.address", "Property: Address", "text", prop("address"), "Property"), F("property.city", "Property: City", "text", prop("city"), "Property"),
            F("property.property_type", "Property: Type", "enum", prop("property_type"), "Property", ["retail", "industrial"]), F("property.market", "Property: Market", "enum", prop("market"), "Property"),
            F("property.building_sf", "Property: SF", "number", prop("building_sf"), "Property"),
        ]
    if entity == "deal":
        prop = lambda k: (lambda db, o, ctx: getattr(o.property, k) if o.property else None)  # noqa: E731
        return [
            F("name", "Name", "text", me("name")), F("status", "Status", "enum", me("status"), options=["open", "won", "lost"]), F("pipeline.key", "Pipeline", "enum", lambda db, o, ctx: o.pipeline.key, options=["seller", "buyer", "capital", "leasing"]),
            F("stage.key", "Stage", "text", lambda db, o, ctx: o.stage.key), F("price", "Price", "money", me("price")), F("probability", "Probability", "number", lambda db, o, ctx: deals_svc.effective_probability(o)),
            F("expected_close_date", "Expected close", "date", me("expected_close_date")), F("actual_close_date", "Actual close", "date", me("actual_close_date")), base_user,
            F("gross_commission", "Gross commission", "money", lambda db, o, ctx: deals_svc.gross_of(o), restricted=True),
            F("days_in_stage", "Days in stage", "number", lambda db, o, ctx: deals_svc.days_in_stage(o)), F("rotting", "Stalled", "bool", lambda db, o, ctx: deals_svc.is_rotting(o)),
            F("property.city", "Property: City", "text", prop("city"), "Property"), F("property.property_type", "Property: Type", "enum", prop("property_type"), "Property", ["retail", "industrial"]),
        ]
    if entity == "lead":
        prop = lambda k: (lambda db, o, ctx: getattr(o.property, k) if o.property else None)  # noqa: E731
        return [
            F("name", "Name", "text", me("name")), F("status", "Status", "enum", me("status"), options=["new", "contacted", "qualified", "converted", "disqualified"]), F("score", "Score", "number", me("score")),
            F("source.name", "Source", "text", lambda db, o, ctx: o.source.name if o.source else None), base_user, F("created_at", "Created", "date", lambda db, o, ctx: _d(o.created_at)),
            F("property.city", "Property: City", "text", prop("city"), "Property"), F("property.property_type", "Property: Type", "enum", prop("property_type"), "Property", ["retail", "industrial"]),
        ]
    raise HTTPException(422, f"entity must be one of {list(ENTITY_MODELS)}")


CUSTOM_TYPE = {"text": "text", "long_text": "text", "number": "number", "currency": "money", "date": "date", "checkbox": "bool", "single_select": "enum", "multi_select": "list", "lookup_user": "user", "lookup_record": "number"}


def fields_for(db: Session, entity: str, user: User) -> dict[str, F]:
    out = {f.key: f for f in registry(entity)}
    for d in db.scalars(select(FieldDefinition).where(FieldDefinition.entity == entity, FieldDefinition.active.is_(True)).order_by(FieldDefinition.position)):
        if d.restricted and not can_see_commission(user):
            continue
        k = f"custom.{d.key}"
        out[k] = F(k, d.label, CUSTOM_TYPE[d.type], (lambda kk: lambda db_, o, ctx: (o.custom or {}).get(kk))(d.key), "Custom fields", list(d.options or []) if d.type in ("single_select", "multi_select") else [], d.restricted)
    if not can_see_commission(user):
        out = {k: f for k, f in out.items() if not f.restricted}
    return out


def field_meta(db: Session, entity: str, user: User) -> list[dict]:
    return [{"key": f.key, "label": f.label, "type": f.type, "operators": OPS[f.type], "options": f.options, "group": f.group, "multi": f.multi} for f in fields_for(db, entity, user).values()]


# ---------- evaluation ----------
def _coerce(t: str, v):
    try:
        if t in ("number", "money"):
            return float(v)
        if t == "date":
            return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])
        if t == "bool":
            if isinstance(v, bool):
                return v
            return str(v).lower() in ("true", "1", "yes")
        if t == "user":
            return int(v)
        return v if isinstance(v, (int, float)) else str(v)
    except (ValueError, TypeError):
        raise HTTPException(422, f"Invalid value {v!r} for a {t} field")


def validate(node: dict, fields: dict[str, F], depth=0, counter=None):
    counter = counter if counter is not None else [0]
    if depth > 4:
        raise HTTPException(422, "Filter groups are nested too deeply")
    if not isinstance(node, dict):
        raise HTTPException(422, "Filter must be an object")
    if "conditions" in node:
        if node.get("op", "and") not in ("and", "or"):
            raise HTTPException(422, "Group op must be and or or")
        for c in node["conditions"]:
            validate(c, fields, depth + 1, counter)
        return
    counter[0] += 1
    if counter[0] > 50:
        raise HTTPException(422, "Too many conditions")
    f = fields.get(node.get("field", ""))
    if not f:
        raise HTTPException(422, f"Unknown or restricted filter field: {node.get('field')!r}")
    op = node.get("operator")
    if op not in OPS[f.type]:
        raise HTTPException(422, f"Operator {op!r} is not valid for {f.label} ({f.type}); use one of {OPS[f.type]}")
    if op in ("is_null", "not_null", "is_empty", "not_empty"):
        return
    if "value" not in node:
        raise HTTPException(422, "A value is required")
    v = node["value"]
    if op in ("in",):
        if not isinstance(v, list) or not v:
            raise HTTPException(422, "'in' needs a non-empty list")
        [_coerce(f.type, x) for x in v]
    elif op == "between":
        if not isinstance(v, list) or len(v) != 2:
            raise HTTPException(422, "'between' needs [low, high]")
        [_coerce(f.type, x) for x in v]
    elif op in ("within_days", "older_than_days"):
        if not isinstance(v, int) or v < 0:
            raise HTTPException(422, f"{op} needs a non-negative integer")
    elif f.type not in ("list",):
        _coerce(f.type, v)


def _cmp(op: str, val, v, t: str, today: date):
    if op == "is_null":
        return val is None or val == ""
    if op == "not_null":
        return not (val is None or val == "")
    if val is None:
        return False
    if t in ("number", "money"):
        val = float(val)
    if op == "eq":
        return (str(val).lower() == str(_coerce(t, v)).lower()) if t in ("text", "enum") else val == _coerce(t, v)
    if op == "ne":
        return not _cmp("eq", val, v, t, today)
    if op == "in":
        return any(_cmp("eq", val, x, t, today) for x in v)
    if op == "contains":
        return str(v).lower() in str(val).lower()
    if op == "starts_with":
        return str(val).lower().startswith(str(v).lower())
    if op in ("gt", "gte", "lt", "lte"):
        c = _coerce(t, v)
        return {"gt": val > c, "gte": val >= c, "lt": val < c, "lte": val <= c}[op]
    if op == "between":
        lo, hi = _coerce(t, v[0]), _coerce(t, v[1])
        return lo <= val <= hi
    if op == "within_days":
        return today <= val <= today + timedelta(days=v)
    if op == "older_than_days":
        return val < today - timedelta(days=v)
    return False


def evaluate(db: Session, node: dict, obj, fields: dict[str, F], ctx: dict, today: date) -> bool:
    if "conditions" in node:
        res = [evaluate(db, c, obj, fields, ctx, today) for c in node["conditions"]]
        if not res:
            return True
        return any(res) if node.get("op", "and") == "or" else all(res)
    f = fields[node["field"]]
    val = f.getter(db, obj, ctx)
    op, v = node["operator"], node.get("value")
    if f.type == "list":
        items = [str(x).lower() for x in (val or [])]
        if op == "contains":
            return str(v).lower() in items
        if op == "not_contains":
            return str(v).lower() not in items
        return (not items) if op == "is_empty" else bool(items)
    vals = val if f.multi else [val]
    if f.multi and not isinstance(val, list):
        vals = [val]
    if op in ("is_null", "not_null"):
        has = any(x not in (None, "") for x in vals)
        return has if op == "not_null" else not has
    if op in ("ne",):
        return not any(_cmp("eq", x, v, f.type, today) for x in vals if x is not None)
    return any(_cmp(op, x, v, f.type, today) for x in vals)


DEFAULT_COLUMNS = {
    "contact": ["full_name", "title", "company.name", "contact_types", "lifecycle_stage", "last_contact_at"],
    "company": ["name", "kind", "city", "properties_count", "portfolio_value"],
    "property": ["address", "city", "property_type", "building_sf", "estimated_value", "loan_maturity_date", "hold_years", "owner.name"],
    "listing": ["property.address", "status", "list_price", "expiration_date", "days_on_market"],
    "deal": ["name", "pipeline.key", "stage.key", "price", "expected_close_date", "status"],
    "lead": ["name", "status", "score", "source.name", "property.city"],
}
LABEL = {"contact": lambda o: o.full_name, "company": lambda o: o.name, "property": lambda o: o.address, "listing": lambda o: f"Listing: {o.property.address}", "deal": lambda o: o.name, "lead": lambda o: o.name}
URL = {"contact": "/contacts/{}", "company": "/companies/{}", "property": "/properties/{}", "listing": "/listings/{}", "deal": "/deals/{}", "lead": "/prospecting"}


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, list):
        return ", ".join(str(x) for x in v if x is not None)
    return v


def run(db: Session, entity: str, flt: dict | None, user: User, columns: list[str] | None = None, sort_field: str | None = None, sort_dir: str = "asc",
        page: int = 1, limit: int = 50, restrict_ids: list[int] | None = None, today: date | None = None) -> dict:
    fields = fields_for(db, entity, user)
    flt = flt or {"op": "and", "conditions": []}
    validate(flt, fields)
    cols = columns or [c for c in DEFAULT_COLUMNS[entity] if c in fields]
    for c in cols:
        if c not in fields:
            raise HTTPException(422, f"Unknown or restricted column: {c!r}")
    if sort_field and sort_field not in fields:
        raise HTTPException(422, f"Unknown or restricted sort field: {sort_field!r}")
    if sort_dir not in ("asc", "desc"):
        raise HTTPException(422, "sort_dir must be asc or desc")
    M = ENTITY_MODELS[entity]
    vis = Visibility(db, user)
    today = today or date.today()
    ctx: dict = {}
    stmt = select(M)
    if hasattr(M, "deleted_at"):
        stmt = stmt.where(M.deleted_at.is_(None))
    if restrict_ids is not None:
        stmt = stmt.where(M.id.in_(restrict_ids or [-1]))
    matched = [o for o in db.scalars(stmt).unique() if vis.can_see(o) and evaluate(db, flt, o, fields, ctx, today)]
    if sort_field:
        sf = fields[sort_field]
        keyed = []
        for o in matched:
            v = sf.getter(db, o, ctx)
            v = v[0] if isinstance(v, list) and v else (None if isinstance(v, list) else v)
            keyed.append((v, o))
        present = sorted([x for x in keyed if x[0] is not None], key=lambda x: x[0] if not isinstance(x[0], str) else x[0].lower(), reverse=(sort_dir == "desc"))
        matched = [o for _, o in present] + [o for v, o in keyed if v is None]  # nulls always last
    else:
        matched.sort(key=lambda o: o.id)
    total = len(matched)
    page_items = matched[(page - 1) * limit: page * limit]
    rows = [{"id": o.id, "label": LABEL[entity](o), "url": URL[entity].format(o.id), **{c: _jsonable(fields[c].getter(db, o, ctx)) for c in cols}} for o in page_items]
    return {"entity": entity, "total": total, "page": page, "limit": limit, "columns": [{"key": c, "label": fields[c].label, "type": fields[c].type} for c in cols], "items": rows, "ids": [o.id for o in matched] if total <= 5000 else []}


def matching_ids(db: Session, entity: str, flt: dict | None, user: User) -> list[int]:
    return run(db, entity, flt, user, limit=1)["ids"]
