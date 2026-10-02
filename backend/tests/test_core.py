import uuid


def u():
    return uuid.uuid4().hex[:8]


def mk_contact(client, h, first="Alex", last=None, email=None, phone=None, **kw):
    last = last or f"Tester{u()}"
    body = {"first_name": first, "last_name": last, "emails": [{"email": email or f"{u()}@ex.com"}],
            "phones": [{"phone": phone}] if phone else [], **kw}
    r = client.post("/api/contacts", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def mk_company(client, h, name=None, **kw):
    r = client.post("/api/companies", json={"name": name or f"Co {u()} LLC", **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def mk_property(client, h, **kw):
    body = {"address": f"{int(u()[:4], 16)} Test Blvd", "city": "Irvine", "property_type": "retail", **kw}
    r = client.post("/api/properties", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_contact_create_normalizes_and_returns_detail(client, admin):
    c = mk_contact(client, admin, phone="(949) 555-0142", contact_types=["owner"])
    assert c["phones"][0]["phone"] == "(949) 555-0142"
    got = client.get(f"/api/contacts/{c['id']}", headers=admin).json()
    assert got["full_name"].startswith("Alex ") and got["contact_types"] == ["owner"]


def test_definite_duplicate_by_email_is_blocked(client, admin):
    c = mk_contact(client, admin, email="dup.test@Example.com")
    r = client.post("/api/contacts", json={"first_name": "Other", "last_name": "Person", "emails": [{"email": "DUP.test@example.com "}]}, headers=admin)
    assert r.status_code == 409
    assert r.json()["detail"]["matches"][0]["id"] == c["id"]


def test_definite_duplicate_by_phone_format(client, admin):
    mk_contact(client, admin, phone="949-555-7788")
    r = client.post("/api/contacts", json={"first_name": "Z", "last_name": "Q", "phones": [{"phone": "+1 (949) 555 7788"}]}, headers=admin)
    assert r.status_code == 409


def test_possible_duplicate_is_queued_not_blocked(client, admin):
    last = f"Hernandez{u()}"
    mk_contact(client, admin, first="Robert", last=last)
    mk_contact(client, admin, first="Roberto", last=last)
    dups = client.get("/api/duplicates?entity=contact", headers=admin).json()["items"]
    assert any(d["a"]["last_name"] == last for d in dups)


def test_company_suffix_normalization_blocks_duplicate(client, admin):
    base = f"Pacific Ridge {u()}"
    mk_company(client, admin, f"{base} LLC")
    r = client.post("/api/companies", json={"name": f"{base}, L.L.C."}, headers=admin)
    assert r.status_code == 409


def test_property_apn_county_duplicate_blocked(client, admin):
    p = mk_property(client, admin, apn="123-456-78", county="Orange")
    r = client.post("/api/properties", json={"address": "999 Different Ave", "city": "Tustin", "property_type": "industrial", "apn": "12345678", "county": "Orange"}, headers=admin)
    assert r.status_code == 409 and r.json()["detail"]["matches"][0]["id"] == p["id"]


def test_owner_graph_both_directions(client, admin):
    person = mk_contact(client, admin, first="Grace", last=f"Holder{u()}")
    llc = mk_company(client, admin, f"Holder {u()} Partners LLC")
    prop = mk_property(client, admin)
    assert client.post(f"/api/contacts/{person['id']}/companies", json={"company_id": llc["id"], "role": "principal"}, headers=admin).status_code == 201
    r = client.post(f"/api/properties/{prop['id']}/ownerships", json={"company_id": llc["id"], "acquired_date": "2015-06-01"}, headers=admin)
    assert r.status_code == 201
    # who owns this property?
    d = client.get(f"/api/properties/{prop['id']}", headers=admin).json()
    assert d["owners"][0]["company"] == llc["name"]
    assert d["owners"][0]["principals"][0]["name"] == person["full_name"]
    assert d["hold_years"] > 10
    # what does this person own?
    c = client.get(f"/api/contacts/{person['id']}", headers=admin).json()
    assert [h["property_id"] for h in c["holdings"]] == [prop["id"]]


def test_ownership_transfer_keeps_history(client, admin):
    a, b = mk_company(client, admin), mk_company(client, admin)
    prop = mk_property(client, admin)
    client.post(f"/api/properties/{prop['id']}/ownerships", json={"company_id": a["id"], "acquired_date": "2010-01-01"}, headers=admin)
    client.post(f"/api/properties/{prop['id']}/ownerships", json={"company_id": b["id"], "acquired_date": "2020-01-01"}, headers=admin)
    d = client.get(f"/api/properties/{prop['id']}", headers=admin).json()
    assert [o["company"] for o in d["owners"]] == [b["name"]]
    assert len(d["ownership_history"]) == 2
    old = [o for o in d["ownership_history"] if o["company_id"] == a["id"]][0]
    assert old["disposed_date"] == "2020-01-01"


def test_search_property_address_returns_owners_and_principals(client, admin):
    person = mk_contact(client, admin, first="Walter", last=f"Graphman{u()}")
    llc = mk_company(client, admin, f"Graphman {u()} Holdings LLC")
    client.post(f"/api/contacts/{person['id']}/companies", json={"company_id": llc["id"]}, headers=admin)
    prop = mk_property(client, admin, address=f"{u()[:3]}7 Unique Search Way")
    client.post(f"/api/properties/{prop['id']}/ownerships", json={"company_id": llc["id"], "acquired_date": "2018-01-01"}, headers=admin)
    res = client.get("/api/search", params={"q": prop["address"]}, headers=admin).json()["results"]
    top = res[0]
    assert top["type"] == "property" and llc["name"] in top["connections"] and person["full_name"] in top["connections"]
    res = client.get("/api/search", params={"q": person["last_name"]}, headers=admin).json()["results"]
    assert res[0]["type"] == "contact" and prop["address"] in res[0]["connections"]


def test_search_by_email_and_phone_and_fuzzy(client, admin):
    c = mk_contact(client, admin, first="Fiona", last=f"Zephyrine{u()}", email="fiona.zeph@search.test", phone="(714) 555-0199")
    for q in ["fiona.zeph@search.test", "714-555-0199", c["last_name"][:-1] + "x"]:
        ids = [r["id"] for r in client.get("/api/search", params={"q": q}, headers=admin).json()["results"] if r["type"] == "contact"]
        assert c["id"] in ids, q


def test_merge_moves_children_and_undo_restores(client, admin):
    keep = mk_contact(client, admin, first="Carl", last=f"Merge{u()}", email=f"{u()}@a.com")
    gone = mk_contact(client, admin, first="Carl", last=keep["last_name"], email=f"{u()}@b.com", title="Managing Partner", tags=["vip"])
    llc = mk_company(client, admin)
    client.post(f"/api/contacts/{gone['id']}/companies", json={"company_id": llc["id"]}, headers=admin)
    r = client.post("/api/merge", json={"entity": "contact", "survivor_id": keep["id"], "absorbed_id": gone["id"]}, headers=admin)
    assert r.status_code == 200
    mid = r.json()["merge_id"]
    k = client.get(f"/api/contacts/{keep['id']}", headers=admin).json()
    assert len(k["emails"]) == 2 and k["title"] == "Managing Partner" and "vip" in k["tags"]
    assert [c["company_id"] for c in k["companies"]] == [llc["id"]]
    assert client.get(f"/api/contacts/{gone['id']}", headers=admin).status_code == 404
    assert client.post(f"/api/merges/{mid}/undo", headers=admin).status_code == 200
    g = client.get(f"/api/contacts/{gone['id']}", headers=admin).json()
    assert [c["company_id"] for c in g["companies"]] == [llc["id"]]
    k = client.get(f"/api/contacts/{keep['id']}", headers=admin).json()
    assert len(k["emails"]) == 1 and k["title"] is None
    assert client.post(f"/api/merges/{mid}/undo", headers=admin).status_code == 409


def test_soft_delete_hides_record(client, admin):
    c = mk_contact(client, admin)
    assert client.delete(f"/api/contacts/{c['id']}", headers=admin).status_code == 204
    assert client.get(f"/api/contacts/{c['id']}", headers=admin).status_code == 404


def test_permissions_by_role(client, headers_for, admin):
    c = mk_contact(client, admin)
    ro, asst, broker = headers_for("read_only"), headers_for("assistant"), headers_for("broker")
    assert client.get(f"/api/contacts/{c['id']}", headers=ro).status_code == 200
    assert client.post("/api/contacts", json={"first_name": "A", "last_name": "B"}, headers=ro).status_code == 403
    assert client.patch(f"/api/contacts/{c['id']}", json={"title": "X"}, headers=ro).status_code == 403
    assert client.patch(f"/api/contacts/{c['id']}", json={"title": "X"}, headers=asst).status_code == 200
    assert client.delete(f"/api/contacts/{c['id']}", headers=broker).status_code == 403
    assert client.post("/api/merge", json={"entity": "contact", "survivor_id": 1, "absorbed_id": 2}, headers=broker).status_code == 403


def test_property_filters(client, admin):
    mk_property(client, admin, address=f"{u()} Filter Rd", city="Anaheim", property_type="industrial", building_sf=50000,
                loan_maturity_date="2027-01-15", market="North OC")
    r = client.get("/api/properties", params={"city": "Anaheim", "type": "industrial", "min_sf": 40000, "maturity_within_months": 24}, headers=admin).json()
    assert r["total"] >= 1 and all(p["city"] == "Anaheim" for p in r["items"])


def test_validation_errors(client, admin):
    assert client.post("/api/properties", json={"address": "1 A St", "city": "X", "property_type": "hotel"}, headers=admin).status_code == 422
    assert client.post("/api/contacts", json={"first_name": "", "last_name": "x"}, headers=admin).status_code == 422
    assert client.post("/api/contacts", json={"first_name": "a", "last_name": "b", "phones": [{"phone": "12"}]}, headers=admin).status_code == 422


def test_audit_trail_records_changes(client, admin):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    c = mk_contact(client, admin)
    client.patch(f"/api/contacts/{c['id']}", json={"title": "Principal"}, headers=admin)
    with SessionLocal() as db:
        evs = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "contacts", AuditEvent.entity_id == c["id"])).all()
    assert {e.action for e in evs} >= {"create", "update"}
    upd = [e for e in evs if e.action == "update"][0]
    assert upd.changes["title"] == [None, "Principal"] and upd.actor == "Admin Tester"
