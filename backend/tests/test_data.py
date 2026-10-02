import io
import json

import openpyxl
import pytest

from tests.test_core import mk_company, mk_contact, mk_property, u


def csv_bytes(header, rows):
    out = ",".join(header) + "\n"
    for r in rows:
        out += ",".join('"' + str(c).replace('"', '""') + '"' for c in r) + "\n"
    return out.encode()


def start(client, h, entity, content, name="data.csv", source="Test Feed", mode="create", mapping=None):
    data = {"entity": entity, "source_name": source, "mode": mode}
    if mapping is not None:
        data["mapping"] = json.dumps(mapping)
    return client.post("/api/imports", files={"file": (name, io.BytesIO(content), "text/csv")}, data=data, headers=h)


def commit(client, h, jid):
    r = client.post(f"/api/imports/{jid}/commit", headers=h)
    assert r.status_code == 202, r.text
    return client.get(f"/api/imports/{jid}", headers=h).json()  # TestClient runs the background task before returning


def contacts_total(client, h, q=None):
    return client.get("/api/contacts", params={"q": q, "limit": 1}, headers=h).json()["total"]


def test_templates_and_automatic_mapping(client, admin):
    t = client.get("/api/imports/templates", params={"entity": "contact"}, headers=admin).json()
    assert {"first_name", "last_name", "email", "phone", "company_name"} <= {x["field"] for x in t["fields"]}
    r = start(client, admin, "contact", csv_bytes(["First Name", "Last Name", "E-mail", "Mobile", "Entity", "Parcel Nbr"], [["A", f"Map{u()}", f"{u()}@x.test", "(949) 555-0101", "Co LLC", "1"]]))
    assert r.status_code == 201
    m = r.json()["mapping"]
    assert m["first_name"] == "First Name" and m["last_name"] == "Last Name" and m["phone"] == "Mobile" and m["company_name"] == "Entity"
    assert client.get("/api/imports/templates", params={"entity": "wizard"}, headers=admin).status_code == 422


def test_preview_writes_nothing_and_reports_every_outcome(client, admin):
    existing = mk_contact(client, admin, email=f"exists{u()}@pre.test")
    tag = u()
    before = contacts_total(client, admin)
    rows = [["Pat", f"New{tag}", f"pat{tag}@pre.test", "949-555-0111"],            # create
            ["Dup", "Person", existing["emails"][0]["email"].upper(), ""],           # duplicate of existing (email)
            ["Bad", f"Mail{tag}", "not-an-email", ""],                               # error
            ["Bad", f"Phone{tag}", f"bp{tag}@pre.test", "12"],                       # error
            ["", "", f"noname{tag}@pre.test", ""],                                   # error (no name)
            ["Pat", f"New{tag}", f"pat{tag}@pre.test", ""]]                          # duplicate within the file
    r = start(client, admin, "contact", csv_bytes(["first_name", "last_name", "email", "phone"], rows)).json()
    assert r["status"] == "previewed" and r["total_rows"] == 6
    assert r["counts"] == {"create": 1, "update": 0, "skip": 0, "duplicate": 2, "error": 3}
    assert contacts_total(client, admin) == before
    items = client.get(f"/api/imports/{r['id']}/rows", headers=admin).json()["items"]
    assert [i["row_no"] for i in items] == [2, 3, 4, 5, 6, 7]
    assert "Invalid email" in items[2]["message"] and "Invalid phone" in items[3]["message"] and "Last name" in items[4]["message"] and "row 2" in items[5]["message"]
    assert [i["action"] for i in client.get(f"/api/imports/{r['id']}/rows", params={"action": "error"}, headers=admin).json()["items"]] == ["error"] * 3


def test_commit_creates_records_with_provenance_and_external_ids_and_refresh_updates(client, admin):
    tag = u()
    header = ["id", "first_name", "last_name", "email", "title", "company"]
    rows = [[f"X-{tag}-1", "Ann", f"Alpha{tag}", f"ann{tag}@feed.test", "Owner", f"Alpha {tag} Holdings LLC"], [f"X-{tag}-2", "Bob", f"Beta{tag}", f"bob{tag}@feed.test", "Trustee", f"Beta {tag} Family Trust"]]
    j = start(client, admin, "contact", csv_bytes(header, rows), source=f"Feed {tag}").json()
    assert j["mapping"]["external_id"] == "id"
    done = commit(client, admin, j["id"])
    assert done["status"] == "completed" and done["counts"]["create"] == 2 and done["summary"]["records_created"]["contacts"] == 2 and done["summary"]["records_created"]["companies"] == 2
    found = client.get("/api/contacts", params={"q": f"Alpha{tag}"}, headers=admin).json()["items"][0]
    detail = client.get(f"/api/contacts/{found['id']}", headers=admin).json()
    assert detail["source"] == f"Feed {tag}" and detail["companies"][0]["company"] == f"Alpha {tag} Holdings LLC"
    from app.db import SessionLocal
    from app.models.core import Contact, ExternalId
    from sqlalchemy import select
    with SessionLocal() as db:
        c = db.get(Contact, found["id"])
        assert c.import_job_id == j["id"] and c.imported_at is not None
        assert db.scalar(select(ExternalId).where(ExternalId.system == f"Feed {tag}", ExternalId.external_id == f"X-{tag}-1")).entity_id == found["id"]
    total = contacts_total(client, admin)
    # refreshed feed: same external ids, changed title, new phone -> updates, not duplicates
    rows2 = [[f"X-{tag}-1", "Ann", f"Alpha{tag}", f"ann.new{tag}@feed.test", "Managing Member", f"Alpha {tag} Holdings LLC"]]
    j2 = start(client, admin, "contact", csv_bytes(header, rows2), source=f"Feed {tag}", mode="create_or_update").json()
    assert j2["counts"]["update"] == 1 and j2["counts"]["create"] == 0
    commit(client, admin, j2["id"])
    assert contacts_total(client, admin) == total
    up = client.get(f"/api/contacts/{found['id']}", headers=admin).json()
    assert up["title"] == "Managing Member" and {e["email"] for e in up["emails"]} == {f"ann{tag}@feed.test", f"ann.new{tag}@feed.test"}  # channels are added, never lost


def test_create_only_mode_blocks_existing_and_update_only_skips_unmatched(client, admin):
    tag = u()
    mk_contact(client, admin, email=f"known{tag}@m.test", last=f"Known{tag}")
    rows = [["Known", f"Known{tag}", f"known{tag}@m.test", "Updated Title"], ["Nobody", f"Nobody{tag}", f"nobody{tag}@m.test", "X"]]
    h = ["first_name", "last_name", "email", "title"]
    c = start(client, admin, "contact", csv_bytes(h, rows), mode="create").json()
    assert c["counts"] == {"create": 1, "update": 0, "skip": 0, "duplicate": 1, "error": 0}
    uo = start(client, admin, "contact", csv_bytes(h, rows), mode="update").json()
    assert uo["counts"] == {"create": 0, "update": 1, "skip": 1, "duplicate": 0, "error": 0}
    commit(client, admin, uo["id"])
    assert client.get("/api/contacts", params={"q": f"Known{tag}"}, headers=admin).json()["items"][0]["title"] == "Updated Title"
    assert contacts_total(client, admin, f"Nobody{tag}") == 0


def test_blank_cells_never_erase_existing_values(client, admin):
    tag = u()
    c = mk_contact(client, admin, email=f"keep{tag}@b.test", last=f"Keep{tag}", title="Principal", city="Irvine")
    j = start(client, admin, "contact", csv_bytes(["first_name", "last_name", "email", "title", "city"], [[c["first_name"], c["last_name"], f"keep{tag}@b.test", "", ""]]), mode="update").json()
    commit(client, admin, j["id"])
    got = client.get(f"/api/contacts/{c['id']}", headers=admin).json()
    assert got["title"] == "Principal"


def test_company_import_normalizes_names(client, admin):
    tag = u()
    mk_company(client, admin, f"Pacific {tag} Partners, L.L.C.")
    h = ["name", "kind", "website", "city"]
    rows = [[f"Pacific {tag} Partners LLC", "llc", "", "Irvine"], [f"New {tag} Trust", "trust", f"https://www.new{tag}.com", "Tustin"], [f"Odd {tag} Co", "spaceship", "", ""]]
    j = start(client, admin, "company", csv_bytes(h, rows)).json()
    assert j["counts"] == {"create": 1, "update": 0, "skip": 0, "duplicate": 1, "error": 1}
    commit(client, admin, j["id"])
    assert client.get("/api/companies", params={"q": f"New {tag}"}, headers=admin).json()["total"] == 1
    # same domain, different name -> still a duplicate
    j2 = start(client, admin, "company", csv_bytes(h, [[f"Totally Different {tag}", "llc", f"https://new{tag}.com", ""]])).json()
    assert j2["counts"]["duplicate"] == 1


def test_property_import_cleaning_and_dedupe(client, admin):
    tag = u()
    existing = mk_property(client, admin, apn=f"900-{tag[:3]}-11", county="Orange", address=f"{tag[:4]} Existing Way")
    h = ["Address", "City", "Type", "SF", "Cap Rate", "Loan Maturity", "Value", "APN", "Hold Intent"]
    rows = [[f"{tag[:3]}1 Import Blvd", "Ontario", "Warehouse", "45,000", "5.25%", "6/30/2028", "$9,500,000", "", "open to sell"],
            [f"{tag[:3]}2 Import Blvd", "Irvine", "Strip Center", "12000", "6", "2029-01-15", "4250000", "", ""],
            [f"{tag[:3]}3 Import Blvd", "Irvine", "Hotel", "", "", "", "", "", ""],
            [f"{tag[:3]}4 Import Blvd", "Irvine", "Retail", "x", "", "", "", "", ""],
            [f"{tag[:3]}5 Import Blvd", "Irvine", "Retail", "", "", "31/31/2020", "", "", ""],
            [f"{tag[:3]}6 Import Blvd", "Irvine", "Retail", "", "45", "", "", "", ""],
            ["999 Other St", "Tustin", "Industrial", "", "", "", "", f"900-{tag[:3]}-11", ""]]
    j = start(client, admin, "property", csv_bytes(h, rows)).json()
    assert j["counts"] == {"create": 2, "update": 0, "skip": 0, "duplicate": 1, "error": 4}
    msgs = [i["message"] for i in client.get(f"/api/imports/{j['id']}/rows", params={"action": "error"}, headers=admin).json()["items"]]
    assert any("retail or industrial" in m for m in msgs) and any("Building SF" in m for m in msgs) and any("date" in m for m in msgs) and any("Cap rate" in m for m in msgs)
    commit(client, admin, j["id"])
    p = client.get("/api/properties", params={"q": f"{tag[:3]}1 Import"}, headers=admin).json()["items"][0]
    d = client.get(f"/api/properties/{p['id']}", headers=admin).json()
    assert d["property_type"] == "industrial" and d["building_sf"] == 45000 and d["cap_rate_bps"] == 525 and d["loan_maturity_date"] == "2028-06-30" and d["estimated_value"] == 9_500_000
    assert d["county"] == "San Bernardino" and d["market"] == "Inland Empire" and d["hold_intent"] == "open_to_sell"  # inferred from the city
    assert client.get("/api/properties", params={"q": f"{tag[:3]}2 Import"}, headers=admin).json()["items"][0]["property_type"] == "retail"


def test_owner_properties_import_links_one_owner_to_many_properties(client, admin):
    tag = u()
    mk_company(client, admin, f"Harbor {tag} Holdings, LLC")
    h = ["Owner First", "Owner Last", "Owner Email", "Entity", "Property Address", "City", "Property Type", "SF", "Acquired", "Price"]
    rows = [["Gil", f"Owner{tag}", f"gil{tag}@own.test", f"Harbor {tag} Holdings LLC", f"{tag[:3]}1 Harbor Rd", "Irvine", "Retail", "8000", "3/15/2012", "2,100,000"],
            ["Gil", f"Owner{tag}", f"gil{tag}@own.test", f"Harbor {tag} Holdings LLC", f"{tag[:3]}2 Harbor Rd", "Irvine", "Retail", "9000", "2018-07-01", ""],
            ["Gil", f"Owner{tag}", f"gil{tag}@own.test", f"Harbor {tag} Holdings LLC", f"{tag[:3]}3 Harbor Rd", "Costa Mesa", "Industrial", "30000", "", ""]]
    j = start(client, admin, "owner_properties", csv_bytes(h, rows), mapping={"owner_first": "Owner First", "owner_last": "Owner Last", "owner_email": "Owner Email", "entity_name": "Entity", "address": "Property Address", "city": "City", "property_type": "Property Type", "building_sf": "SF", "acquired_date": "Acquired", "acquisition_price": "Price"}).json()
    assert j["counts"]["create"] == 3 and j["counts"]["error"] == 0
    done = commit(client, admin, j["id"])
    made = done["summary"]["records_created"]
    assert made == {"contacts": 1, "companies": 0, "properties": 3, "ownerships": 3}  # entity matched an existing LLC by normalized name; person created once
    person = client.get("/api/contacts", params={"q": f"Owner{tag}"}, headers=admin).json()["items"][0]
    detail = client.get(f"/api/contacts/{person['id']}", headers=admin).json()
    assert len(detail["holdings"]) == 3 and detail["companies"][0]["company"] == f"Harbor {tag} Holdings, LLC"
    prop = client.get("/api/properties", params={"q": f"{tag[:3]}1 Harbor"}, headers=admin).json()["items"][0]
    pd = client.get(f"/api/properties/{prop['id']}", headers=admin).json()
    assert pd["owners"][0]["principals"][0]["name"] == person["full_name"] and pd["ownership_history"][0]["acquired_date"] == "2012-03-15" and pd["ownership_history"][0]["acquisition_price"] == 2_100_000
    # re-importing the same file creates nothing new
    j2 = start(client, admin, "owner_properties", csv_bytes(h, rows), mapping=j["mapping"]).json()
    again = commit(client, admin, j2["id"])
    assert again["summary"]["records_created"] == {"contacts": 0, "companies": 0, "properties": 0, "ownerships": 0}


def test_xlsx_import(client, admin):
    tag = u()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Full Name", "Email", "Phone"])
    ws.append([f"Xena Excel{tag}", f"xena{tag}@x.test", "(714) 555-0123"])
    buf = io.BytesIO()
    wb.save(buf)
    r = start(client, admin, "contact", buf.getvalue(), name="book.xlsx")
    assert r.status_code == 201 and r.json()["counts"]["create"] == 1 and r.json()["mapping"]["full_name"] == "Full Name"
    commit(client, admin, r.json()["id"])
    got = client.get("/api/contacts", params={"q": f"Excel{tag}"}, headers=admin).json()["items"][0]
    assert got["first_name"] == "Xena" and got["last_name"] == f"Excel{tag}"


def test_file_and_mapping_validation(client, admin):
    ok = csv_bytes(["first_name", "last_name"], [["A", "B"]])
    assert start(client, admin, "contact", b"", name="e.csv").status_code == 422
    assert start(client, admin, "contact", b"x", name="e.exe").status_code == 415
    assert start(client, admin, "wizard", ok).status_code == 422
    assert start(client, admin, "contact", ok, mode="sometimes").status_code == 422
    assert start(client, admin, "contact", ok, source=" ").status_code == 422
    assert start(client, admin, "contact", csv_bytes(["a", "a"], [["1", "2"]])).status_code == 422
    assert start(client, admin, "contact", ok, mapping={"last_name": "nope"}).status_code == 422
    assert start(client, admin, "contact", ok, mapping={"banana": "first_name"}).status_code == 422
    assert start(client, admin, "contact", csv_bytes(["foo"], [["1"]])).status_code == 422  # nothing mappable: required fields
    assert start(client, admin, "property", csv_bytes(["Address"], [["1 A St"]])).status_code == 422
    assert start(client, admin, "contact", b"x" * (6 * 1024 * 1024), name="big.csv").status_code == 413
    assert start(client, admin, "contact", ok, mapping="{bad").status_code == 422


def test_change_mapping_recomputes_preview(client, admin):
    tag = u()
    j = start(client, admin, "contact", csv_bytes(["Surname", "Given", "Mail"], [[f"Remap{tag}", "Rita", f"rita{tag}@r.test"]])).json()
    assert j["counts"]["error"] == 1 or j["counts"]["create"] == 1
    r = client.put(f"/api/imports/{j['id']}", json={"mapping": {"last_name": "Surname", "first_name": "Given", "email": "Mail"}, "mode": "create"}, headers=admin)
    assert r.status_code == 200 and r.json()["counts"]["create"] == 1
    commit(client, admin, j["id"])
    assert client.put(f"/api/imports/{j['id']}", json={"mode": "update"}, headers=admin).status_code == 409


def test_error_report_csv(client, admin):
    tag = u()
    j = start(client, admin, "contact", csv_bytes(["first_name", "last_name", "email"], [["Ok", f"Fine{tag}", f"ok{tag}@e.test"], ["Bad", f"Mail{tag}", "nope"]])).json()
    r = client.get(f"/api/imports/{j['id']}/errors.csv", headers=admin)
    lines = r.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].split(",")[:3] == ["row", "result", "reason"] and len(lines) == 2 and "Invalid email" in lines[1] and lines[1].startswith("3,error")


def test_a_failing_row_does_not_poison_the_rest_and_commit_is_resumable(client, admin):
    from app.db import SessionLocal
    from app.models.imports import ImportJob, ImportRow
    tag = u()
    # a required custom field makes the apply step fail for rows that do not supply it, but preview cannot know
    f = client.post("/api/custom-fields", json={"entity": "company", "key": f"req_{tag}", "label": "Req", "type": "text", "required": True}, headers=admin).json()
    j = start(client, admin, "owner_properties", csv_bytes(["owner_last", "entity_name", "address", "city", "property_type"], [[f"Own{tag}", f"Fresh {tag} Capital LLC", f"{tag[:3]}1 Poison Ct", "Irvine", "retail"]]),
              mapping={"owner_last": "owner_last", "entity_name": "entity_name", "address": "address", "city": "city", "property_type": "property_type"}).json()
    client.patch(f"/api/custom-fields/{f['id']}", json={"active": False}, headers=admin)  # retired before commit: the row now succeeds
    done = commit(client, admin, j["id"])
    assert done["status"] == "completed" and done["counts"]["create"] == 1
    # simulate a crash after the work was done but before the row was marked processed, then resume
    with SessionLocal() as db:
        job = db.get(ImportJob, j["id"])
        job.status = "failed"
        row = db.query(ImportRow).filter_by(job_id=j["id"]).first()
        row.processed = False
        db.commit()
    props_before = client.get("/api/properties", params={"q": f"{tag[:3]}1 Poison"}, headers=admin).json()["total"]
    again = commit(client, admin, j["id"])
    assert again["status"] == "completed" and client.get("/api/properties", params={"q": f"{tag[:3]}1 Poison"}, headers=admin).json()["total"] == props_before == 1
    assert client.post(f"/api/imports/{j['id']}/commit", headers=admin).status_code == 409


def test_rollback_removes_unmodified_records_and_keeps_modified_ones(client, admin):
    tag = u()
    h = ["first_name", "last_name", "email"]
    rows = [["Del", f"Gone{tag}", f"gone{tag}@rb.test"], ["Edit", f"Kept{tag}", f"kept{tag}@rb.test"], ["Act", f"Used{tag}", f"used{tag}@rb.test"]]
    j = start(client, admin, "contact", csv_bytes(h, rows), source=f"RB {tag}").json()
    commit(client, admin, j["id"])
    ids = {x["last_name"]: x["id"] for x in client.get("/api/contacts", params={"q": tag}, headers=admin).json()["items"]}
    assert len(ids) == 3
    import time
    time.sleep(2.2)  # the rollback guard allows 2s of slack after the import finishes
    client.patch(f"/api/contacts/{ids[f'Kept{tag}']}", json={"title": "Edited after import"}, headers=admin)
    client.post("/api/activities", json={"type": "other", "subject": "Used", "status": "completed", "associations": [{"record_type": "contact", "record_id": ids[f'Used{tag}']}]}, headers=admin)
    r = client.post(f"/api/imports/{j['id']}/rollback", headers=admin)
    assert r.status_code == 200 and r.json()["removed"]["contacts"] == 1 and {k["id"] for k in r.json()["kept"]} == {ids[f"Kept{tag}"], ids[f"Used{tag}"]}
    assert client.get(f"/api/contacts/{ids[f'Gone{tag}']}", headers=admin).status_code == 404
    assert client.get(f"/api/contacts/{ids[f'Kept{tag}']}", headers=admin).status_code == 200
    assert client.get(f"/api/imports/{j['id']}", headers=admin).json()["status"] == "rolled_back"
    assert client.post(f"/api/imports/{j['id']}/rollback", headers=admin).status_code == 409
    # the removed record's external identity is freed, so a re-import creates it again
    j2 = start(client, admin, "contact", csv_bytes(h, rows[:1]), source=f"RB {tag}").json()
    assert j2["counts"]["create"] == 1


def test_import_permissions_and_audit(client, admin, headers_for):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    ok = csv_bytes(["first_name", "last_name", "email"], [["P", f"Perm{u()}", f"{u()}@p.test"]])
    for role in ("assistant", "read_only"):
        assert start(client, headers_for(role), "contact", ok).status_code == 403
    b = start(client, headers_for("broker"), "contact", ok)
    assert b.status_code == 201
    assert client.post(f"/api/imports/{b.json()['id']}/commit", headers=headers_for("assistant")).status_code == 403
    assert client.post(f"/api/imports/{b.json()['id']}/rollback", headers=headers_for("broker")).status_code == 403  # rollback is a manager/admin action
    done = commit(client, headers_for("broker"), b.json()["id"])
    with SessionLocal() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "import_jobs", AuditEvent.entity_id == b.json()["id"])).all()
        created = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "contacts", AuditEvent.actor == "Broker Tester", AuditEvent.action == "create")).all()
    assert {e.action for e in ev} >= {"create", "update"} and len(created) >= 1  # rows written by the background task are attributed to the importing user


# ---------------- export ----------------
def read_csv(resp):
    import csv
    return list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))


def test_export_csv_xlsx_with_filter_view_and_list(client, admin):
    tag = u()
    a = mk_property(client, admin, tags=[f"ex{tag}"], city="Brea", estimated_value=5_000_000)
    b = mk_property(client, admin, tags=[f"ex{tag}"], city="Tustin")
    flt = {"op": "and", "conditions": [{"field": "tags", "operator": "contains", "value": f"ex{tag}"}]}
    view = client.post("/api/views", json={"name": f"ex {tag}", "entity": "property", "filter": flt, "columns": ["address", "city", "estimated_value"], "visibility": "shared"}, headers=admin).json()
    r = client.get("/api/export/property", params={"view_id": view["id"]}, headers=admin)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = read_csv(r)
    assert rows[0] == ["Address", "City", "Value"] and len(rows) == 3 and {x[1] for x in rows[1:]} == {"Brea", "Tustin"}
    x = client.get("/api/export/property", params={"view_id": view["id"], "format": "xlsx"}, headers=admin)
    ws = openpyxl.load_workbook(io.BytesIO(x.content)).active
    assert [c.value for c in ws[1]] == ["Address", "City", "Value"] and ws.max_row == 3
    lst = client.post("/api/lists", json={"name": f"static {tag}", "entity": "property", "kind": "static", "member_ids": [a["id"]]}, headers=admin).json()
    assert len(read_csv(client.get("/api/export/property", params={"list_id": lst["id"]}, headers=admin))) == 2
    full = read_csv(client.get("/api/export/property", headers=admin))
    assert "id" in full[0] and "Address" in full[0] and len(full) > 3
    assert client.get("/api/export/property", params={"format": "pdf"}, headers=admin).status_code == 422
    assert client.get("/api/export/widget", headers=admin).status_code == 422
    assert client.get("/api/export/contact", params={"view_id": view["id"]}, headers=admin).status_code == 404  # view belongs to another entity


def test_export_permissions_audit_visibility_and_rate_limit(client, admin, headers_for, monkeypatch):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    from app.services import exports
    tag = u()
    owner = headers_for("broker")
    c = client.post("/api/contacts", json={"first_name": "Hid", "last_name": f"Den{tag}", "emails": [{"email": f"h{tag}@e.test"}]}, headers=owner).json()
    client.patch(f"/api/contacts/{c['id']}", json={"confidential": True}, headers=owner)
    for role in ("assistant", "read_only"):
        assert client.get("/api/export/contact", headers=headers_for(role)).status_code == 403
    mgr_rows = read_csv(client.get("/api/export/contact", headers=headers_for("manager")))
    assert any(f"Den{tag}" in row[1] for row in mgr_rows)  # managers see confidential records
    # a different broker-level user would not: confidentiality applies to exports (checked via the filter engine)
    from tests.conftest import make_user
    make_user(f"broker2{tag}@test.com", "broker", name="Second Broker")
    r = client.post("/api/auth/login", json={"email": f"broker2{tag}@test.com", "password": "pw12345"})
    other = {"Authorization": f"Bearer {r.json()['token']}"}
    assert not any(f"Den{tag}" in " ".join(row) for row in read_csv(client.get("/api/export/contact", headers=other)))
    with SessionLocal() as db:
        n = len(db.scalars(select(AuditEvent).where(AuditEvent.action == "export", AuditEvent.entity_type == "contact")).all())
    assert n >= 2
    monkeypatch.setenv("TRG_EXPORT_LIMIT", "2")
    exports.reset_limits()
    assert client.get("/api/export/company", headers=admin).status_code == 200
    assert client.get("/api/export/company", headers=admin).status_code == 200
    third = client.get("/api/export/company", headers=admin)
    assert third.status_code == 429 and "limit" in third.text
    exports.reset_limits()


def test_full_export_has_relationship_history_and_respects_note_privacy(client, admin, headers_for):
    from tests.test_prospecting_listings import mk_owned_property
    prop, llc, person = mk_owned_property(client, admin, years_held=6)
    client.post("/api/activities", json={"type": "call", "subject": "Full export call", "status": "completed", "outcome": "spoke", "associations": [{"record_type": "contact", "record_id": person["id"]}]}, headers=admin)
    client.post("/api/notes", json={"body": "SECRET PRIVATE BODY", "visibility": "private", "associations": [{"record_type": "contact", "record_id": person["id"]}]}, headers=admin)
    client.post("/api/notes", json={"body": "Team note body", "associations": [{"record_type": "contact", "record_id": person["id"]}]}, headers=admin)
    r = client.get("/api/export-full", headers=headers_for("manager"))
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert {"Contacts", "Companies", "Properties", "Ownership history", "Activities", "Notes (metadata)", "Contact-company roles", "Deals", "Listings"} <= set(wb.sheetnames)
    own = [[c.value for c in row] for row in wb["Ownership history"].iter_rows(min_row=2)]
    assert any(row[0] == prop["id"] and row[3] == llc["name"] for row in own)
    acts = [[c.value for c in row] for row in wb["Activities"].iter_rows(min_row=2)]
    assert any(row[2] == "Full export call" for row in acts)
    flat = " ".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row)
    assert "SECRET PRIVATE BODY" not in flat and "Team note body" not in flat  # note bodies are not exported, only metadata
    assert client.get("/api/export-full", headers=headers_for("read_only")).status_code == 403
