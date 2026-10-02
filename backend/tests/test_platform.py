from datetime import date, timedelta

import pytest

from tests.test_core import mk_company, mk_contact, mk_property, u
from tests.test_prospecting_listings import mk_owned_property


def q(client, h, entity, flt=None, **kw):
    r = client.post("/api/query", json={"entity": entity, "filter": flt, **kw}, headers=h)
    return r


def cond(field, operator, value=None):
    c = {"field": field, "operator": operator}
    if value is not None:
        c["value"] = value
    return c


def group(op, *conds):
    return {"op": op, "conditions": list(conds)}


def tag():
    return f"zq{u()}"


# ---------------- filter engine ----------------
def test_filter_fields_metadata_and_restrictions(client, admin, headers_for):
    f = client.get("/api/filter-fields", params={"entity": "deal"}, headers=admin).json()["fields"]
    keys = {x["key"] for x in f}
    assert {"stage.key", "price", "gross_commission", "expected_close_date"} <= keys
    assert [x for x in f if x["key"] == "price"][0]["operators"][:3] == ["eq", "ne", "gt"]
    restricted = {x["key"] for x in client.get("/api/filter-fields", params={"entity": "deal"}, headers=headers_for("assistant")).json()["fields"]}
    assert "gross_commission" not in restricted and "price" in restricted
    assert client.get("/api/filter-fields", params={"entity": "wizard"}, headers=admin).status_code == 422


def test_query_and_or_groups_and_nested(client, admin):
    t = tag()
    a = mk_property(client, admin, city="Brea", property_type="retail", building_sf=10_000, tags=[t])
    b = mk_property(client, admin, city="Brea", property_type="industrial", building_sf=60_000, tags=[t])
    c = mk_property(client, admin, city="Tustin", property_type="industrial", building_sf=90_000, tags=[t])
    base = cond("tags", "contains", t)
    ids = lambda f: {x["id"] for x in q(client, admin, "property", f, limit=200).json()["items"]}  # noqa: E731
    assert ids(group("and", base, cond("city", "eq", "brea"))) == {a["id"], b["id"]}  # text eq is case-insensitive
    assert ids(group("and", base, cond("city", "eq", "Brea"), cond("property_type", "eq", "industrial"))) == {b["id"]}
    assert ids(group("and", base, group("or", cond("building_sf", "lt", 20_000), cond("building_sf", "gte", 90_000)))) == {a["id"], c["id"]}
    assert ids(group("and", base, cond("building_sf", "between", [50_000, 100_000]))) == {b["id"], c["id"]}
    assert ids(group("and", base, cond("city", "in", ["Tustin", "Irvine"]))) == {c["id"]}
    assert ids(group("and", base, cond("city", "ne", "Brea"))) == {c["id"]}
    assert ids(group("and", base, cond("city", "starts_with", "tus"))) == {c["id"]}
    assert ids(group("and", base, cond("subtype", "is_null"))) == {a["id"], b["id"], c["id"]}
    assert ids(group("and", base, cond("tags", "not_contains", "nope"))) == {a["id"], b["id"], c["id"]}


def test_related_record_conditions_any_match(client, admin):
    """Contacts whose holdings include a property with a loan maturing within 12 months (ADR 0015)."""
    prop_soon, llc1, p1 = mk_owned_property(client, admin, years_held=5, maturity_months=6)
    prop_far, llc2, p2 = mk_owned_property(client, admin, years_held=5, maturity_months=40)
    f = group("and", cond("holdings.loan_maturity_date", "within_days", 365))
    r = q(client, admin, "contact", f, limit=200).json()
    ids = {x["id"] for x in r["items"]}
    assert p1["id"] in ids and p2["id"] not in ids
    # company-level and property-level related conditions
    c = q(client, admin, "company", group("and", cond("holdings.loan_maturity_date", "within_days", 365)), limit=200).json()
    assert llc1["id"] in {x["id"] for x in c["items"]} and llc2["id"] not in {x["id"] for x in c["items"]}
    pr = q(client, admin, "property", group("and", cond("principal.name", "contains", p1["last_name"])), limit=200).json()
    assert [x["id"] for x in pr["items"]] == [prop_soon["id"]]
    owned = q(client, admin, "property", group("and", cond("owner.name", "eq", llc2["name"]), cond("hold_years", "gte", 4)), limit=200).json()
    assert [x["id"] for x in owned["items"]] == [prop_far["id"]]


def test_date_operators(client, admin):
    t = tag()
    a = mk_property(client, admin, loan_maturity_date=(date.today() + timedelta(days=30)).isoformat(), tags=[t])
    b = mk_property(client, admin, loan_maturity_date=(date.today() - timedelta(days=400)).isoformat(), tags=[t])
    base = cond("tags", "contains", t)
    ids = lambda f: {x["id"] for x in q(client, admin, "property", f, limit=200).json()["items"]}  # noqa: E731
    assert ids(group("and", base, cond("loan_maturity_date", "within_days", 90))) == {a["id"]}
    assert ids(group("and", base, cond("loan_maturity_date", "older_than_days", 365))) == {b["id"]}
    assert ids(group("and", base, cond("loan_maturity_date", "gt", "2000-01-01"))) == {a["id"], b["id"]}


@pytest.mark.parametrize("flt,msg", [
    (group("and", cond("nonsense", "eq", 1)), "Unknown or restricted filter field"),
    (group("and", cond("city", "gt", "x")), "not valid for"),
    (group("and", cond("building_sf", "eq", "abc")), "Invalid value"),
    (group("and", cond("building_sf", "between", [1])), "between"),
    (group("and", cond("city", "in", [])), "non-empty list"),
    (group("and", cond("loan_maturity_date", "within_days", -3)), "non-negative"),
    (group("xor", cond("city", "eq", "a")), "and or or"),
    ({"field": "city", "operator": "eq"}, "value is required"),
])
def test_invalid_filters_are_rejected_with_reasons(client, admin, flt, msg):
    r = q(client, admin, "property", flt)
    assert r.status_code == 422 and msg in r.text


def test_depth_and_size_limits(client, admin):
    deep = cond("city", "eq", "x")
    for _ in range(6):
        deep = group("and", deep)
    assert q(client, admin, "property", deep).status_code == 422
    many = group("and", *[cond("city", "eq", f"c{i}") for i in range(60)])
    assert q(client, admin, "property", many).status_code == 422


def test_restricted_field_cannot_be_used_by_unauthorized_roles(client, admin, headers_for):
    assert q(client, admin, "deal", group("and", cond("gross_commission", "gt", 1))).status_code == 200
    r = q(client, headers_for("assistant"), "deal", group("and", cond("gross_commission", "gt", 1)))
    assert r.status_code == 422 and "restricted" in r.text
    assert q(client, headers_for("assistant"), "deal", None, columns=["name", "gross_commission"]).status_code == 422
    assert q(client, headers_for("assistant"), "deal", None, sort_field="gross_commission").status_code == 422


def test_sort_pagination_columns_and_nulls_last(client, admin):
    t = tag()
    ps = [mk_property(client, admin, tags=[t], estimated_value=v) for v in (3_000_000, 1_000_000, 2_000_000)] + [mk_property(client, admin, tags=[t])]
    f = cond("tags", "contains", t)
    r = q(client, admin, "property", f, columns=["address", "estimated_value"], sort_field="estimated_value", sort_dir="asc").json()
    assert [x["estimated_value"] for x in r["items"]] == [1_000_000, 2_000_000, 3_000_000, None]
    d = q(client, admin, "property", f, columns=["estimated_value"], sort_field="estimated_value", sort_dir="desc").json()
    assert [x["estimated_value"] for x in d["items"]] == [3_000_000, 2_000_000, 1_000_000, None]
    p1 = q(client, admin, "property", f, sort_field="estimated_value", limit=3, page=1).json()
    p2 = q(client, admin, "property", f, sort_field="estimated_value", limit=3, page=2).json()
    assert p1["total"] == 4 and len(p1["items"]) == 3 and len(p2["items"]) == 1
    assert [c["key"] for c in r["columns"]] == ["address", "estimated_value"] and r["items"][0]["url"].startswith("/properties/")


# ---------------- saved views ----------------
def test_views_validate_visibility_and_run(client, admin, headers_for):
    t = tag()
    mk_property(client, admin, tags=[t], city="Brea")
    body = {"name": f"Brea {t}", "entity": "property", "filter": group("and", cond("tags", "contains", t)), "columns": ["address", "city"], "sort_field": "address", "visibility": "shared"}
    bad = client.post("/api/views", json={**body, "filter": group("and", cond("zzz", "eq", 1))}, headers=admin)
    assert bad.status_code == 422
    v = client.post("/api/views", json=body, headers=admin)
    assert v.status_code == 201
    vid = v.json()["id"]
    run = client.get(f"/api/views/{vid}/run", headers=headers_for("read_only")).json()
    assert run["total"] == 1 and [c["key"] for c in run["columns"]] == ["address", "city"]
    private = client.post("/api/views", json={**body, "name": f"Mine {t}", "visibility": "private"}, headers=admin).json()
    assert private["id"] not in [x["id"] for x in client.get("/api/views", params={"entity": "property"}, headers=headers_for("broker")).json()["items"]]
    assert client.get(f"/api/views/{private['id']}/run", headers=headers_for("broker")).status_code == 404
    assert client.patch(f"/api/views/{vid}", json={"name": "x"}, headers=headers_for("broker")).status_code == 403
    assert client.patch(f"/api/views/{vid}", json={"filter": group("and", cond("zzz", "eq", 1))}, headers=admin).status_code == 422
    assert client.delete(f"/api/views/{vid}", headers=admin).status_code == 204
    assert client.get(f"/api/views/{vid}/run", headers=admin).status_code == 404


# ---------------- lists ----------------
def test_dynamic_list_recomputes_and_static_list_is_a_fixed_snapshot(client, admin):
    t = tag()
    a = mk_property(client, admin, tags=[t])
    flt = group("and", cond("tags", "contains", t))
    dyn = client.post("/api/lists", json={"name": f"Dyn {t}", "entity": "property", "kind": "dynamic", "filter": flt}, headers=admin).json()
    assert dyn["member_count"] == 1
    snap = client.post(f"/api/lists/{dyn['id']}/snapshot", headers=admin).json()
    assert snap["kind"] == "static" and snap["member_count"] == 1
    b = mk_property(client, admin, tags=[t])
    assert client.get(f"/api/lists/{dyn['id']}", headers=admin).json()["member_count"] == 2
    assert {x["id"] for x in client.get(f"/api/lists/{dyn['id']}/members", headers=admin).json()["items"]} == {a["id"], b["id"]}
    assert {x["id"] for x in client.get(f"/api/lists/{snap['id']}/members", headers=admin).json()["items"]} == {a["id"]}
    r = client.patch(f"/api/lists/{snap['id']}/members", json={"add": [b["id"]], "remove": [a["id"]]}, headers=admin)
    assert r.status_code == 200 and {x["id"] for x in client.get(f"/api/lists/{snap['id']}/members", headers=admin).json()["items"]} == {b["id"]}
    assert client.patch(f"/api/lists/{dyn['id']}/members", json={"add": [b["id"]]}, headers=admin).status_code == 409
    assert client.patch(f"/api/lists/{snap['id']}/members", json={"add": [99999999]}, headers=admin).status_code == 422


def test_list_validation_and_privacy(client, admin, headers_for):
    assert client.post("/api/lists", json={"name": "x", "entity": "property", "kind": "dynamic"}, headers=admin).status_code == 422
    assert client.post("/api/lists", json={"name": "x", "entity": "property", "kind": "static"}, headers=admin).status_code == 422
    assert client.post("/api/lists", json={"name": "x", "entity": "property", "kind": "sometimes", "filter": {}}, headers=admin).status_code == 422
    assert client.post("/api/lists", json={"name": "x", "entity": "property", "kind": "dynamic", "filter": group("and", cond("zzz", "eq", 1))}, headers=admin).status_code == 422
    mine = client.post("/api/lists", json={"name": f"Priv {u()}", "entity": "contact", "kind": "static", "member_ids": [], "visibility": "private"}, headers=admin).json()
    assert client.get(f"/api/lists/{mine['id']}", headers=headers_for("broker")).status_code == 404
    shared = client.post("/api/lists", json={"name": f"Shared {u()}", "entity": "contact", "kind": "static", "member_ids": [], "visibility": "shared"}, headers=admin).json()
    assert client.get(f"/api/lists/{shared['id']}", headers=headers_for("read_only")).status_code == 200
    assert client.delete(f"/api/lists/{shared['id']}", headers=headers_for("broker")).status_code == 403


# ---------------- tags ----------------
def test_bulk_tags_normalize_count_and_filter(client, admin):
    cs = [mk_contact(client, admin) for _ in range(3)]
    t = f"  Hot  {u()} "
    r = client.post("/api/tags/bulk", json={"entity": "contact", "ids": [c["id"] for c in cs], "add": [t, "VIP"]}, headers=admin)
    assert r.json()["updated"] == 3
    norm = f"hot {t.split()[-1]}"
    assert [x for x in client.get("/api/tags", params={"entity": "contact"}, headers=admin).json()["items"] if x["tag"] == norm][0]["count"] == 3
    assert client.post("/api/tags/bulk", json={"entity": "contact", "ids": [cs[0]["id"]], "remove": [norm]}, headers=admin).json()["updated"] == 1
    res = q(client, admin, "contact", cond("tags", "contains", norm), limit=50).json()
    assert {x["id"] for x in res["items"]} == {cs[1]["id"], cs[2]["id"]}
    assert client.post("/api/tags/bulk", json={"entity": "contact", "ids": [cs[1]["id"]], "add": ["x" * 41]}, headers=admin).status_code == 422
    assert client.post("/api/tags/bulk", json={"entity": "contact", "ids": [99999999], "add": ["a"]}, headers=admin).status_code == 422
    assert client.post("/api/tags/bulk", json={"entity": "lead", "ids": [1], "add": ["a"]}, headers=admin).status_code == 422


# ---------------- custom fields ----------------
def mkfield(client, h, entity="property", **kw):
    body = {"entity": entity, "key": f"f_{u()}", "label": "Test field", "type": "text", **kw}
    r = client.post("/api/custom-fields", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_custom_field_admin_only_and_definition_validation(client, admin, headers_for):
    base = {"entity": "property", "key": f"k_{u()}", "label": "X", "type": "text"}
    assert client.post("/api/custom-fields", json=base, headers=headers_for("manager")).status_code == 403
    assert client.post("/api/custom-fields", json={**base, "key": "Bad Key"}, headers=admin).status_code == 422
    assert client.post("/api/custom-fields", json={**base, "type": "formula"}, headers=admin).status_code == 422
    assert client.post("/api/custom-fields", json={**base, "entity": "widget"}, headers=admin).status_code == 422
    assert client.post("/api/custom-fields", json={**base, "type": "single_select"}, headers=admin).status_code == 422
    assert client.post("/api/custom-fields", json=base, headers=admin).status_code == 201
    assert client.post("/api/custom-fields", json=base, headers=admin).status_code == 409


def test_custom_values_validated_by_type(client, admin):
    p = mk_property(client, admin)
    f = {t: mkfield(client, admin, type=t, **({"options": ["a", "b"]} if "select" in t else {})) for t in ("text", "number", "currency", "date", "checkbox", "single_select", "multi_select")}
    patch = lambda **vals: client.patch(f"/api/properties/{p['id']}", json={"custom": {f[k]["key"]: v for k, v in vals.items()}}, headers=admin)  # noqa: E731
    ok = patch(text="hi", number=3, currency=250000.5, date="2026-03-01", checkbox=True, single_select="a", multi_select=["b", "a", "a"])
    assert ok.status_code == 200
    got = ok.json()["custom"]
    assert got[f["multi_select"]["key"]] == ["a", "b"] and got[f["date"]["key"]] == "2026-03-01"
    for bad in ({"number": "3"}, {"number": True}, {"date": "tomorrow"}, {"checkbox": "yes"}, {"single_select": "z"}, {"multi_select": ["z"]}, {"text": 5}, {"text": "x" * 400}):
        assert patch(**bad).status_code == 422, bad
    assert client.patch(f"/api/properties/{p['id']}", json={"custom": {"not_a_field": 1}}, headers=admin).status_code == 422
    cleared = patch(text=None)
    assert f["text"]["key"] not in cleared.json()["custom"]


def test_required_and_conditionally_required_fields(client, admin):
    always = mkfield(client, admin, entity="company", required=True)
    cr = client.post("/api/companies", json={"name": f"Req {u()} LLC"}, headers=admin)
    assert cr.status_code == 422 and "required" in cr.text
    ok = client.post("/api/companies", json={"name": f"Req {u()} LLC", "custom": {always["key"]: "yes"}}, headers=admin)
    assert ok.status_code == 201 and ok.json()["custom"][always["key"]] == "yes"
    client.patch(f"/api/custom-fields/{always['id']}", json={"active": False}, headers=admin)  # retire so later tests are unaffected
    cond_field = mkfield(client, admin, entity="property", required_when={"property_type": "retail"})
    r = client.post("/api/properties", json={"address": f"{u()} Cond St", "city": "Irvine", "property_type": "retail"}, headers=admin)
    assert r.status_code == 422 and "required" in r.text
    r = client.post("/api/properties", json={"address": f"{u()} Cond St", "city": "Irvine", "property_type": "industrial"}, headers=admin)
    assert r.status_code == 201  # not required for industrial
    r = client.post("/api/properties", json={"address": f"{u()} Cond St", "city": "Irvine", "property_type": "retail", "custom": {cond_field["key"]: "ok"}}, headers=admin)
    assert r.status_code == 201
    client.patch(f"/api/custom-fields/{cond_field['id']}", json={"active": False}, headers=admin)


def test_retired_field_hidden_but_data_kept(client, admin):
    f = mkfield(client, admin, entity="contact")
    c = mk_contact(client, admin)
    r = client.patch(f"/api/contacts/{c['id']}", json={"custom": {f["key"]: "keep me"}}, headers=admin)
    assert r.json()["custom"][f["key"]] == "keep me"
    assert client.patch(f"/api/custom-fields/{f['id']}", json={"active": False}, headers=admin).status_code == 200
    assert f["key"] not in client.get(f"/api/contacts/{c['id']}", headers=admin).json()["custom"]
    assert client.patch(f"/api/contacts/{c['id']}", json={"custom": {f["key"]: "x"}}, headers=admin).status_code == 422
    assert f["id"] not in [x["id"] for x in client.get("/api/custom-fields", params={"entity": "contact"}, headers=admin).json()["items"]]
    assert f["id"] in [x["id"] for x in client.get("/api/custom-fields", params={"entity": "contact", "include_retired": True}, headers=admin).json()["items"]]
    from app.db import SessionLocal
    from app.models.core import Contact
    with SessionLocal() as db:
        assert db.get(Contact, c["id"]).custom[f["key"]] == "keep me"  # data is retained
    dup = client.post("/api/custom-fields", json={"entity": "contact", "key": f["key"], "label": "again", "type": "text"}, headers=admin)
    assert dup.status_code == 409


def test_field_type_and_options_are_protected(client, admin):
    f = mkfield(client, admin, type="single_select", options=["a", "b"])
    assert client.patch(f"/api/custom-fields/{f['id']}", json={"type": "text"}, headers=admin).status_code == 409
    assert client.patch(f"/api/custom-fields/{f['id']}", json={"options": ["a"]}, headers=admin).status_code == 409
    assert client.patch(f"/api/custom-fields/{f['id']}", json={"options": ["a", "b", "c"]}, headers=admin).status_code == 200


def test_custom_fields_in_filters_and_columns(client, admin):
    f = mkfield(client, admin, entity="property", type="single_select", options=["gold", "silver"], label="Tier")
    t = tag()
    a, b = mk_property(client, admin, tags=[t]), mk_property(client, admin, tags=[t])
    client.patch(f"/api/properties/{a['id']}", json={"custom": {f["key"]: "gold"}}, headers=admin)
    client.patch(f"/api/properties/{b['id']}", json={"custom": {f["key"]: "silver"}}, headers=admin)
    r = q(client, admin, "property", group("and", cond("tags", "contains", t), cond(f"custom.{f['key']}", "eq", "gold")), columns=["address", f"custom.{f['key']}"]).json()
    assert [x["id"] for x in r["items"]] == [a["id"]] and r["items"][0][f"custom.{f['key']}"] == "gold" and r["columns"][1]["label"] == "Tier"


def test_restricted_custom_fields(client, admin, headers_for):
    f = mkfield(client, admin, entity="deal", restricted=True, label="Referral fee note")
    from tests.test_deals import mk_deal
    d = mk_deal(client, admin)
    assert client.patch(f"/api/deals/{d['id']}", json={"custom": {f["key"]: "secret"}}, headers=admin).status_code == 200
    assert client.get(f"/api/deals/{d['id']}", headers=admin).json()["custom"][f["key"]] == "secret"
    assert f["key"] not in client.get(f"/api/deals/{d['id']}", headers=headers_for("assistant")).json()["custom"]
    assert client.patch(f"/api/deals/{d['id']}", json={"custom": {f["key"]: "x"}}, headers=headers_for("assistant")).status_code == 403
    assert f["key"] not in [x["key"] for x in client.get("/api/custom-fields", params={"entity": "deal"}, headers=headers_for("assistant")).json()["items"]]


def test_custom_field_changes_are_audited(client, admin):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    f = mkfield(client, admin, entity="company")
    co = mk_company(client, admin)
    client.patch(f"/api/companies/{co['id']}", json={"custom": {f["key"]: "v1"}}, headers=admin)
    with SessionLocal() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "companies", AuditEvent.entity_id == co["id"], AuditEvent.action == "update")).all()
        defs = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "field_definitions", AuditEvent.entity_id == f["id"])).all()
    assert any("custom" in e.changes for e in ev) and len(defs) >= 1


# ---------------- visibility ----------------
def test_confidential_records_hidden_from_non_owners_everywhere(client, admin, headers_for):
    owner = headers_for("broker")
    c = client.post("/api/contacts", json={"first_name": "Secret", "last_name": f"Sauce{u()}", "emails": [{"email": f"{u()}@s.test"}]}, headers=owner).json()
    assert client.patch(f"/api/contacts/{c['id']}", json={"confidential": True}, headers=owner).status_code == 200
    assistant, ro = headers_for("assistant"), headers_for("read_only")
    assert client.get(f"/api/contacts/{c['id']}", headers=owner).status_code == 200  # owner
    assert client.get(f"/api/contacts/{c['id']}", headers=admin).status_code == 200  # admin
    assert client.get(f"/api/contacts/{c['id']}", headers=headers_for("manager")).status_code == 200
    for h in (assistant, ro):
        assert client.get(f"/api/contacts/{c['id']}", headers=h).status_code == 404
        assert c["id"] not in [x["id"] for x in client.get("/api/contacts", params={"q": c["last_name"]}, headers=h).json()["items"]]
        assert c["id"] not in [x["id"] for x in client.get("/api/search", params={"q": c["last_name"]}, headers=h).json()["results"]]
        assert c["id"] not in [x["id"] for x in q(client, h, "contact", cond("full_name", "contains", c["last_name"])).json()["items"]]
    assert c["id"] in [x["id"] for x in client.get("/api/search", params={"q": c["last_name"]}, headers=admin).json()["results"]]
    assert client.patch(f"/api/contacts/{c['id']}", json={"confidential": False}, headers=assistant).status_code == 404
    other_broker_conf = client.patch(f"/api/contacts/{c['id']}", json={"confidential": False}, headers=admin)
    assert other_broker_conf.status_code == 200
    assert client.get(f"/api/contacts/{c['id']}", headers=assistant).status_code == 200


def test_only_owner_or_manager_can_mark_confidential(client, admin, headers_for):
    c = mk_contact(client, admin)  # owned by admin
    r = client.patch(f"/api/contacts/{c['id']}", json={"confidential": True}, headers=headers_for("assistant"))
    assert r.status_code == 403
