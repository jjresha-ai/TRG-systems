import io
from datetime import date, datetime, timedelta

from tests.test_core import mk_company, mk_contact, mk_property, u
from tests.test_deals import mk_deal


def act(client, h, record, **kw):
    body = {"type": "call", "subject": f"Call {u()}", "associations": [record], **kw}
    r = client.post("/api/activities", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def iso(days=0, hour=9):
    return (datetime.combine(date.today(), datetime.min.time()) + timedelta(days=days, hours=hour)).isoformat()


def test_planned_task_needs_due_date_and_association(client, admin):
    c = mk_contact(client, admin)
    rec = {"record_type": "contact", "record_id": c["id"]}
    assert client.post("/api/activities", json={"type": "call", "subject": "x", "associations": [rec]}, headers=admin).status_code == 422
    assert client.post("/api/activities", json={"type": "call", "subject": "x", "due_at": iso(1), "associations": []}, headers=admin).status_code == 422
    assert client.post("/api/activities", json={"type": "call", "subject": "x", "due_at": iso(1), "associations": [{"record_type": "contact", "record_id": 99999999}]}, headers=admin).status_code == 422
    assert client.post("/api/activities", json={"type": "fax", "subject": "x", "due_at": iso(1), "associations": [rec]}, headers=admin).status_code == 422


def test_task_completion_becomes_logged_activity_and_sets_last_contact(client, admin):
    c, prop = mk_contact(client, admin), mk_property(client, admin)
    a = act(client, admin, {"record_type": "contact", "record_id": c["id"]}, due_at=iso(0))
    a2 = client.patch(f"/api/activities/{a['id']}", json={"subject": a["subject"]}, headers=admin)
    assert a2.status_code == 200
    # association to several records at once
    r = client.post("/api/activities", json={"type": "meeting", "subject": "Site tour", "status": "completed", "associations": [{"record_type": "contact", "record_id": c["id"]}, {"record_type": "property", "record_id": prop["id"]}]}, headers=admin)
    assert r.status_code == 201 and r.json()["status"] == "completed" and len(r.json()["associations"]) == 2
    assert client.get(f"/api/contacts/{c['id']}", headers=admin).json()["last_contact_at"] is not None
    assert client.get(f"/api/properties/{prop['id']}", headers=admin).json()["last_contact_at"] is not None


def test_call_without_connection_is_not_a_touch(client, admin):
    c = mk_contact(client, admin)
    a = act(client, admin, {"record_type": "contact", "record_id": c["id"]}, due_at=iso(0))
    done = client.post(f"/api/activities/{a['id']}/complete", json={"outcome": "no_answer"}, headers=admin)
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert client.get(f"/api/contacts/{c['id']}", headers=admin).json()["last_contact_at"] is None
    b = act(client, admin, {"record_type": "contact", "record_id": c["id"]}, due_at=iso(0))
    client.post(f"/api/activities/{b['id']}/complete", json={"outcome": "spoke"}, headers=admin)
    assert client.get(f"/api/contacts/{c['id']}", headers=admin).json()["last_contact_at"] is not None
    assert client.post(f"/api/activities/{b['id']}/complete", json={}, headers=admin).status_code == 409
    assert client.post(f"/api/activities/{a['id']}/complete", json={"outcome": "bogus"}, headers=admin).status_code in (409, 422)


def test_recurrence_creates_next_instance_on_completion(client, admin):
    c = mk_contact(client, admin)
    a = act(client, admin, {"record_type": "contact", "record_id": c["id"]}, due_at=iso(0), recurrence_days=90, subject="90-day owner check-in")
    client.post(f"/api/activities/{a['id']}/complete", json={"outcome": "spoke"}, headers=admin)
    planned = client.get("/api/activities", params={"record_type": "contact", "record_id": c["id"], "status": "planned"}, headers=admin).json()["items"]
    assert len(planned) == 1 and planned[0]["subject"] == "90-day owner check-in" and planned[0]["recurrence_days"] == 90
    assert datetime.fromisoformat(planned[0]["due_at"]).date() == date.today() + timedelta(days=90)


def test_agenda_overdue_today_week(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()["id"]
    c = mk_contact(client, admin)
    rec = {"record_type": "contact", "record_id": c["id"]}
    o = act(client, admin, rec, due_at=iso(-3), assignee_user_id=me)
    t = act(client, admin, rec, due_at=iso(0, 15), assignee_user_id=me)
    w = act(client, admin, rec, due_at=iso(4), assignee_user_id=me)
    ag = client.get("/api/agenda", headers=admin).json()
    assert o["id"] in [x["id"] for x in ag["overdue"]] and t["id"] in [x["id"] for x in ag["today"]] and w["id"] in [x["id"] for x in ag["this_week"]]
    assert all(x["overdue"] for x in ag["overdue"])
    assert ag["counts"]["overdue"] >= 1
    b = client.get("/api/activities", params={"bucket": "overdue", "assignee_id": me}, headers=admin).json()["items"]
    assert o["id"] in [x["id"] for x in b]


def test_do_not_contact_blocks_outreach_activities(client, admin):
    c = mk_contact(client, admin, do_not_contact=True, do_not_contact_reason="Asked to stop")
    rec = {"record_type": "contact", "record_id": c["id"]}
    r = client.post("/api/activities", json={"type": "call", "subject": "x", "due_at": iso(1), "associations": [rec]}, headers=admin)
    assert r.status_code == 409 and "do-not-contact" in r.text
    assert client.post("/api/activities", json={"type": "other", "subject": "Internal review", "due_at": iso(1), "associations": [rec]}, headers=admin).status_code == 201


def test_cadence_apply_creates_ordinary_tasks_idempotently(client, admin):
    cad = client.post("/api/cadences", json={"name": f"Owner 90-day {u()}", "steps": [{"day_offset": 0, "type": "call", "subject": "Intro call"}, {"day_offset": 3, "type": "email", "subject": "Follow-up email"},
                                                                                       {"day_offset": 30, "type": "call", "subject": "30-day check", "priority": "high"}]}, headers=admin)
    assert cad.status_code == 201
    c = mk_contact(client, admin)
    start = date.today().isoformat()
    r = client.post(f"/api/cadences/{cad.json()['id']}/apply", json={"record_type": "contact", "record_id": c["id"], "start_date": start}, headers=admin)
    assert r.status_code == 201 and r.json()["created"] == 3
    dues = sorted(datetime.fromisoformat(t["due_at"]).date() for t in r.json()["tasks"])
    assert dues == [date.today(), date.today() + timedelta(days=3), date.today() + timedelta(days=30)]
    again = client.post(f"/api/cadences/{cad.json()['id']}/apply", json={"record_type": "contact", "record_id": c["id"], "start_date": start}, headers=admin)
    assert again.json()["created"] == 0
    assert client.post(f"/api/cadences/{cad.json()['id']}/apply", json={"record_type": "property", "record_id": mk_property(client, admin)["id"]}, headers=admin).status_code == 422


def test_deal_key_dates_create_and_update_tasks(client, admin):
    d = mk_deal(client, admin, listing_expiration_date=(date.today() + timedelta(days=60)).isoformat(), expected_close_date=(date.today() + timedelta(days=90)).isoformat(), price=2_000_000)
    tasks = client.get("/api/activities", params={"record_type": "deal", "record_id": d["id"]}, headers=admin).json()["items"]
    subjects = {t["subject"].split(":")[0] for t in tasks}
    assert {"Listing expires", "Closing"} <= subjects
    renewal = [t for t in tasks if t["subject"].startswith("Listing expires")][0]
    assert datetime.fromisoformat(renewal["due_at"]).date() == date.today() + timedelta(days=30)
    client.patch(f"/api/deals/{d['id']}", json={"listing_expiration_date": (date.today() + timedelta(days=100)).isoformat()}, headers=admin)
    tasks2 = client.get("/api/activities", params={"record_type": "deal", "record_id": d["id"]}, headers=admin).json()["items"]
    renewal2 = [t for t in tasks2 if t["subject"].startswith("Listing expires")]
    assert len(renewal2) == 1 and datetime.fromisoformat(renewal2[0]["due_at"]).date() == date.today() + timedelta(days=70)
    client.post(f"/api/deals/{d['id']}/stage", json={"stage": "lost", "lost_reason": "x"}, headers=admin)
    tasks3 = client.get("/api/activities", params={"record_type": "deal", "record_id": d["id"], "status": "planned"}, headers=admin).json()["items"]
    assert tasks3 == []  # losing the deal cancels its pending key-date tasks


# ---------------- notes ----------------
def note(client, h, record, body="Owner wants $5M, no rush", **kw):
    r = client.post("/api/notes", json={"body": body, "associations": [record], **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_note_sanitized_versioned_and_soft_deleted(client, admin):
    c = mk_contact(client, admin)
    rec = {"record_type": "contact", "record_id": c["id"]}
    n = note(client, admin, rec, body="Hello <script>alert(1)</script><b>world</b>")
    assert "<" not in n["body"] and n["version"] == 1
    e = client.patch(f"/api/notes/{n['id']}", json={"body": "Updated body"}, headers=admin).json()
    assert e["version"] == 2 and e["edited"] and [v["body"] for v in e["versions"]][-1] == "Updated body" and len(e["versions"]) == 2
    assert client.delete(f"/api/notes/{n['id']}", headers=admin).status_code == 204
    assert client.get(f"/api/notes/{n['id']}", headers=admin).status_code == 404
    assert client.get("/api/notes", params={"record_type": "contact", "record_id": c["id"]}, headers=admin).json()["total"] == 0


def test_notes_associate_to_many_records_and_pin_first(client, admin):
    c, p = mk_contact(client, admin), mk_property(client, admin)
    a = note(client, admin, {"record_type": "contact", "record_id": c["id"]}, body="first")
    r = client.post("/api/notes", json={"body": "both", "pinned": True, "associations": [{"record_type": "contact", "record_id": c["id"]}, {"record_type": "property", "record_id": p["id"]}]}, headers=admin)
    assert r.status_code == 201
    items = client.get("/api/notes", params={"record_type": "contact", "record_id": c["id"]}, headers=admin).json()["items"]
    assert [i["body"] for i in items] == ["both", "first"]
    assert client.get("/api/notes", params={"record_type": "property", "record_id": p["id"]}, headers=admin).json()["total"] == 1


def test_private_notes_hidden_from_others_and_from_search(client, admin, headers_for):
    c = mk_contact(client, admin)
    rec = {"record_type": "contact", "record_id": c["id"]}
    tag = f"secretzebra{u()}"
    n = note(client, admin, rec, body=f"Private thought {tag}", visibility="private")
    note(client, admin, rec, body=f"Team knowledge {tag}")
    mgr = headers_for("manager")
    assert client.get(f"/api/notes/{n['id']}", headers=mgr).status_code == 404
    bodies = [x["body"] for x in client.get("/api/notes", params={"record_type": "contact", "record_id": c["id"]}, headers=mgr).json()["items"]]
    assert all("Private" not in b for b in bodies) and any("Team knowledge" in b for b in bodies)
    res = client.get("/api/search", params={"q": tag}, headers=admin).json()["results"]
    assert sum(1 for r in res if r["type"] == "note") == 1  # private never indexed for search
    tl = client.get("/api/timeline", params={"record_type": "contact", "record_id": c["id"]}, headers=mgr).json()
    assert all("Private" not in (i["data"].get("body") or "") for i in tl["history"])
    assert client.patch(f"/api/notes/{n['id']}", json={"body": "hack"}, headers=mgr).status_code == 404


def test_mentions_create_notifications(client, admin, headers_for):
    c = mk_contact(client, admin)
    users = {x["name"]: x["id"] for x in client.get("/api/auth/users", headers=admin).json()}
    target = "Broker Tester"
    note(client, admin, {"record_type": "contact", "record_id": c["id"]}, body=f"@[{target}] please call this owner")
    broker = headers_for("broker")
    nots = client.get("/api/notifications", headers=broker).json()
    assert nots["unread"] >= 1 and "please call this owner" in nots["items"][0]["message"] and nots["items"][0]["record_id"] == c["id"]
    assert client.post("/api/notifications/read-all", headers=broker).status_code == 200
    assert client.get("/api/notifications", params={"unread": True}, headers=broker).json()["unread"] == 0


# ---------------- documents ----------------
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"


def upload(client, h, rec, name="OM.pdf", content=PDF, **form):
    return client.post("/api/documents", files={"file": (name, io.BytesIO(content), "application/pdf")}, data={"record_type": rec["record_type"], "record_id": rec["record_id"], **form}, headers=h)


def test_document_upload_versioning_and_signed_download(client, admin):
    p = mk_property(client, admin)
    rec = {"record_type": "property", "record_id": p["id"]}
    r1 = upload(client, admin, rec, doc_type="om")
    assert r1.status_code == 201 and r1.json()["version"] == 1
    r2 = upload(client, admin, rec, content=PDF + b"\n% revised")
    assert r2.json()["version"] == 2 and r2.json()["group_id"] == r1.json()["group_id"] and r2.json()["versions"] == 2
    latest = client.get("/api/documents", params={"record_type": "property", "record_id": p["id"]}, headers=admin).json()["items"]
    assert len(latest) == 1 and latest[0]["version"] == 2
    vs = client.get(f"/api/documents/{r2.json()['id']}/versions", headers=admin).json()["items"]
    assert [v["version"] for v in vs] == [2, 1]
    url = client.post(f"/api/documents/{r1.json()['id']}/url", headers=admin).json()["url"]
    got = client.get(url)  # no bearer: the short-lived signed URL is the credential
    assert got.status_code == 200 and got.content == PDF
    assert client.get(url.split("token=")[0] + "token=bad").status_code == 403
    assert client.get(f"/api/documents/{r1.json()['id']}/download?token=1.1.abc").status_code == 403


def test_document_validation(client, admin):
    p = mk_property(client, admin)
    rec = {"record_type": "property", "record_id": p["id"]}
    assert upload(client, admin, rec, name="evil.exe", content=b"MZ....").status_code == 415
    assert upload(client, admin, rec, name="fake.pdf", content=b"not a pdf").status_code == 415
    assert upload(client, admin, rec, content=b"").status_code == 422
    assert upload(client, admin, rec, content=PDF + b"x" * (10 * 1024 * 1024)).status_code == 413
    assert upload(client, admin, rec, doc_type="deed").status_code == 422
    assert upload(client, admin, {"record_type": "property", "record_id": 99999999}).status_code == 422


def test_confidential_documents_restricted_and_download_audited(client, admin, headers_for):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    p = mk_property(client, admin)
    d = upload(client, admin, {"record_type": "property", "record_id": p["id"]}, name="Rent Roll.pdf", visibility="confidential", doc_type="rent_roll").json()
    assert client.post(f"/api/documents/{d['id']}/url", headers=headers_for("assistant")).status_code == 403
    url = client.post(f"/api/documents/{d['id']}/url", headers=admin).json()["url"]
    assert client.get(url).status_code == 200
    with SessionLocal() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "document_download", AuditEvent.entity_id == d["id"])).all()
    assert len(ev) == 1 and ev[0].actor == "Admin Tester"


def test_merge_moves_activities_notes_and_documents(client, admin):
    keep, gone = mk_contact(client, admin, last=f"Mrg{u()}"), mk_contact(client, admin, last=f"Mrg{u()}")
    rec = {"record_type": "contact", "record_id": gone["id"]}
    act(client, admin, rec, due_at=iso(2))
    note(client, admin, rec)
    upload(client, admin, rec)
    client.post("/api/merge", json={"entity": "contact", "survivor_id": keep["id"], "absorbed_id": gone["id"]}, headers=admin)
    tl = client.get("/api/timeline", params={"record_type": "contact", "record_id": keep["id"]}, headers=admin).json()
    kinds = {i["kind"] for i in tl["upcoming"] + tl["history"]}
    assert kinds == {"activity", "note", "document"}


def test_timeline_orders_upcoming_and_history(client, admin):
    c = mk_contact(client, admin)
    rec = {"record_type": "contact", "record_id": c["id"]}
    act(client, admin, rec, due_at=iso(5), subject="Future call")
    done = act(client, admin, rec, due_at=iso(0), subject="Past call")
    client.post(f"/api/activities/{done['id']}/complete", json={"outcome": "spoke"}, headers=admin)
    note(client, admin, rec, body="Pinned fact", pinned=True)
    tl = client.get("/api/timeline", params={"record_type": "contact", "record_id": c["id"]}, headers=admin).json()
    assert [i["data"]["subject"] for i in tl["upcoming"]] == ["Future call"]
    assert {i["kind"] for i in tl["history"]} == {"activity", "note"} and len(tl["pinned"]) == 1


def test_timeline_shows_only_current_document_version(client, admin):
    p = mk_property(client, admin)
    rec = {"record_type": "property", "record_id": p["id"]}
    upload(client, admin, rec)
    upload(client, admin, rec, content=PDF + b"\n% v2")
    tl = client.get("/api/timeline", params={"record_type": "property", "record_id": p["id"]}, headers=admin).json()
    docs = [i for i in tl["history"] if i["kind"] == "document"]
    assert len(docs) == 1 and docs[0]["data"]["version"] == 2 and docs[0]["data"]["versions"] == 2
