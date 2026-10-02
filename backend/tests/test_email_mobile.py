from datetime import datetime, timedelta

from tests.conftest import make_user
from tests.test_core import mk_company, mk_contact, mk_property, u
from tests.test_deals import mk_deal
from tests.test_prospecting_listings import mk_owned_property
from tests.test_security_rules import hdr, mk_user


def cap(client, h, **kw):
    body = {"from_addr": kw.pop("from_addr", "someone@ext.test"), "to_addrs": kw.pop("to_addrs", ["me@trg.test"]), "subject": kw.pop("subject", f"Subject {u()}"), "body": kw.pop("body", "Hello"), **kw}
    return client.post("/api/email/capture", json=body, headers=h)


def now_iso(minutes=0):
    return (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()


def fresh_user(client, admin, role="broker"):
    user, body = mk_user(client, admin, role)
    return user, hdr(client, body["email"], "longpass1"), body["email"]


# ---------------- connection and provider interface ----------------
def test_connection_defaults_to_capture_and_encrypts_tokens(client, admin):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.mail import EmailAccountConnection
    user, h, email = fresh_user(client, admin)
    c = client.get("/api/email/connection", headers=h).json()
    assert c["provider"] == "capture" and c["can_send"] is False and c["bcc_token"] and c["planned_providers"] == ["microsoft365", "google"] and c["email_address"] == email
    r = client.put("/api/email/connection", json={"tokens": {"access_token": "SECRET-ACCESS", "refresh_token": "SECRET-REFRESH"}}, headers=h)
    assert r.status_code == 200 and r.json()["has_tokens"] is True and "SECRET" not in r.text
    with SessionLocal() as db:
        conn = db.scalar(select(EmailAccountConnection).where(EmailAccountConnection.user_id == user["id"]))
        assert "SECRET" not in conn.tokens_encrypted
        from app.services.mail import decrypt_tokens
        assert decrypt_tokens(conn.tokens_encrypted)["access_token"] == "SECRET-ACCESS"
    assert client.put("/api/email/connection", json={"email_address": "nope"}, headers=h).status_code == 422


# ---------------- capture and association ----------------
def test_capture_auto_associates_contacts_and_updates_last_contact(client, admin):
    user, h, email = fresh_user(client, admin)
    c = mk_contact(client, admin, email=f"owner{u()}@assoc.test")
    addr = c["emails"][0]["email"]
    r = cap(client, h, from_addr=addr.upper(), to_addrs=[email], sent_at=now_iso(-5), subject="Thinking about selling")
    assert r.status_code == 201 and r.json()["stored"] and r.json()["direction"] == "inbound" and r.json()["associated"]["contacts"] == [c["id"]]
    assert client.get(f"/api/contacts/{c['id']}", headers=admin).json()["last_contact_at"] is not None
    out = cap(client, h, from_addr=email, to_addrs=[addr, f"x{u()}@nobody.test"], subject="Re: Thinking about selling").json()
    assert out["direction"] == "outbound" and out["associated"]["contacts"] == [c["id"]]  # unknown recipients are simply not linked


def test_capture_is_idempotent_by_message_id(client, admin):
    user, h, email = fresh_user(client, admin)
    mid = f"<{u()}@mail>"
    a = cap(client, h, message_id=mid).json()
    b = cap(client, h, message_id=mid).json()
    assert b["duplicate"] is True and b["id"] == a["id"]
    assert client.get("/api/email/messages", params={"mine": True}, headers=h).json()["total"] == 1


def test_related_deal_and_property_linked_only_when_unambiguous(client, admin):
    user, h, email = fresh_user(client, admin)
    prop, llc, person = mk_owned_property(client, admin, years_held=4)
    addr = f"o{u()}@own.test"
    client.patch(f"/api/contacts/{person['id']}", json={"emails": [{"email": addr}]}, headers=admin)
    out = cap(client, h, from_addr=addr, to_addrs=[email]).json()
    assert {"type": "property", "id": prop["id"]} in out["associated"]["related"]  # exactly one holding
    deal = mk_deal(client, admin, property_id=prop["id"], parties=[{"role": "seller", "contact_id": person["id"]}])
    out2 = cap(client, h, from_addr=addr, to_addrs=[email]).json()
    assert {"type": "deal", "id": deal["id"]} in out2["associated"]["related"] and {"type": "property", "id": prop["id"]} in out2["associated"]["related"]
    deal2 = mk_deal(client, admin, parties=[{"role": "seller", "contact_id": person["id"]}])  # a second open deal: ambiguous
    out3 = cap(client, h, from_addr=addr, to_addrs=[email]).json()
    assert all(r["type"] != "deal" for r in out3["associated"]["related"])


def test_exclusion_rules_prevent_storage(client, admin):
    user, h, email = fresh_user(client, admin)
    for kind, value in (("domain", "family.test"), ("address", f"spouse{u()}@gmail.test"), ("keyword", "divorce")):
        r = client.post("/api/email/exclusions", json={"kind": kind, "value": value}, headers=h)
        assert r.status_code == 201
        if kind == "address":
            spouse = value
    assert client.post("/api/email/exclusions", json={"kind": "regex", "value": "x"}, headers=h).status_code == 422
    for kw in ({"from_addr": "mom@family.test"}, {"from_addr": spouse}, {"from_addr": "lawyer@x.test", "subject": "Re: DIVORCE settlement"}, {"from_addr": "ok@x.test", "body": "about the divorce"}):
        r = cap(client, h, **kw).json()
        assert r["stored"] is False and "excluded" in r["reason"]
    assert client.get("/api/email/messages", params={"mine": True}, headers=h).json()["total"] == 0  # never stored
    assert cap(client, h, from_addr="client@work.test").json()["stored"] is True
    ex = client.get("/api/email/exclusions", headers=h).json()["items"]
    assert len(ex) == 3
    assert client.delete(f"/api/email/exclusions/{ex[0]['id']}", headers=h).status_code == 204
    assert client.get("/api/email/exclusions", headers=client_other(client, admin)).json()["items"] == []  # exclusions are per user


def client_other(client, admin):
    _, h, _ = fresh_user(client, admin)
    return h


def test_capture_validation(client, admin):
    user, h, email = fresh_user(client, admin)
    assert client.post("/api/email/capture", json={"from_addr": "", "to_addrs": ["a@b.c"]}, headers=h).status_code == 422
    assert client.post("/api/email/capture", json={"from_addr": "a@b.c", "to_addrs": []}, headers=h).status_code == 422
    assert cap(client, h, direction="sideways").status_code == 422
    assert cap(client, h, visibility="everyone").status_code == 422
    assert client.post("/api/email/capture", json={"from_addr": "a@b.c", "to_addrs": ["d@e.f"]}).status_code == 401


def test_bcc_capture_uses_the_user_secret(client, admin):
    user, h, email = fresh_user(client, admin)
    token = client.get("/api/email/connection", headers=h).json()["bcc_token"]
    c = mk_contact(client, admin, email=f"bcc{u()}@lead.test")
    r = client.post(f"/api/public/email/bcc/{token}", json={"from_addr": email, "to_addrs": [c["emails"][0]["email"]], "subject": "Sent via BCC", "body": "hi"})
    assert r.status_code == 201 and r.json()["stored"] and r.json()["associated"]["contacts"] == [c["id"]]
    msgs = client.get("/api/email/messages", params={"mine": True}, headers=h).json()["items"]
    assert msgs[0]["channel"] == "bcc" and msgs[0]["visibility"] == "private"
    assert client.post("/api/public/email/bcc/not-a-token", json={"from_addr": "a@b.c", "to_addrs": ["d@e.f"]}).status_code == 404


# ---------------- privacy ----------------
def test_messages_are_private_by_default_and_sharing_reveals_only_what_is_allowed(client, admin, headers_for):
    user, h, email = fresh_user(client, admin)
    c = mk_contact(client, admin, email=f"priv{u()}@p.test")
    m = cap(client, h, from_addr=c["emails"][0]["email"], to_addrs=[email], subject="Confidential pricing", body="We want 5.2M").json()
    other = headers_for("manager")
    tl = lambda: client.get("/api/email/messages", params={"record_type": "contact", "record_id": c["id"]}, headers=other).json()["items"]  # noqa: E731
    assert tl() == []  # private to the connecting user
    assert client.get("/api/email/messages", params={"record_type": "contact", "record_id": c["id"]}, headers=h).json()["items"][0]["body"] == "We want 5.2M"
    for level, subj, body in (("team_metadata", False, False), ("team_subject", True, False), ("team_full", True, True)):
        assert client.post(f"/api/email/messages/{m['id']}/share", json={"level": level}, headers=h).status_code == 200
        seen = tl()[0]
        assert seen["from_addr"] == c["emails"][0]["email"] and seen["sent_at"]
        assert ("subject" in seen and seen["subject"] == "Confidential pricing") == subj and ("body" in seen) == body
        assert seen["mine"] is False and seen["owner_user_id"] == user["id"]
    client.post(f"/api/email/messages/{m['id']}/share", json={"level": "team_metadata"}, headers=h)
    assert tl()[0]["subject"] is None and tl()[0]["subject_hidden"] is True and "body" not in tl()[0]
    assert client.post(f"/api/email/messages/{m['id']}/share", json={"level": "bogus"}, headers=h).status_code == 422
    assert client.post(f"/api/email/messages/{m['id']}/share", json={"level": "team_full"}, headers=other).status_code == 404  # only the owner shares
    tlr = client.get("/api/timeline", params={"record_type": "contact", "record_id": c["id"]}, headers=other).json()
    assert [i for i in tlr["history"] if i["kind"] == "email"][0]["data"]["subject"] is None  # the timeline honors the same rules
    assert client.get("/api/email/messages", params={"q": "pricing"}, headers=other).json()["items"] == []  # others' mail is never searchable


def test_per_contact_sharing_applies_to_existing_and_future_messages(client, admin, headers_for):
    user, h, email = fresh_user(client, admin)
    c = mk_contact(client, admin, email=f"share{u()}@p.test")
    a = cap(client, h, from_addr=c["emails"][0]["email"], to_addrs=[email], subject="first").json()
    r = client.put("/api/email/shares", json={"contact_id": c["id"], "level": "team_subject"}, headers=h)
    assert r.status_code == 200 and r.json()["messages_updated"] == 1
    b = cap(client, h, from_addr=c["emails"][0]["email"], to_addrs=[email], subject="second").json()
    assert b["visibility"] == "team_subject"  # future messages inherit the contact-level setting
    seen = client.get("/api/email/messages", params={"record_type": "contact", "record_id": c["id"]}, headers=headers_for("manager")).json()["items"]
    assert sorted(x["subject"] for x in seen) == ["first", "second"]
    assert client.delete(f"/api/email/shares/{c['id']}", headers=h).status_code == 204
    assert client.get("/api/email/messages", params={"record_type": "contact", "record_id": c["id"]}, headers=headers_for("manager")).json()["items"] == []
    assert client.put("/api/email/shares", json={"contact_id": 99999999, "level": "team_full"}, headers=h).status_code == 422


def test_unlinked_messages_can_be_associated_manually(client, admin):
    user, h, email = fresh_user(client, admin)
    m = cap(client, h, from_addr=f"stranger{u()}@new.test", to_addrs=[email]).json()
    assert client.get("/api/email/messages", params={"unlinked": True}, headers=h).json()["total"] == 1
    c = mk_contact(client, admin)
    r = client.post(f"/api/email/messages/{m['id']}/associate", json={"record_type": "contact", "record_id": c["id"]}, headers=h)
    assert r.status_code == 201 and client.get("/api/email/messages", params={"unlinked": True}, headers=h).json()["total"] == 0
    assert client.get(f"/api/contacts/{c['id']}", headers=admin).json()["last_contact_at"] is not None
    assert client.post(f"/api/email/messages/{m['id']}/associate", json={"record_type": "contact", "record_id": 99999999}, headers=h).status_code == 422


def test_do_not_contact_warning_on_outbound_mail(client, admin):
    user, h, email = fresh_user(client, admin)
    c = mk_contact(client, admin, email=f"dnc{u()}@x.test", do_not_contact=True, do_not_contact_reason="No")
    out = cap(client, h, from_addr=email, to_addrs=[c["emails"][0]["email"]]).json()
    assert out["stored"] and "do-not-contact" in out["outreach_warning"]


# ---------------- templates, bulk, unsubscribe ----------------
def test_templates_merge_fields_and_dnc_block(client, admin):
    from tests.test_investors import active_listing_for
    assert client.post("/api/email/templates", json={"name": f"Bad {u()}", "subject": "Hi {{nickname}}", "body": "x"}, headers=admin).status_code == 422
    t = client.post("/api/email/templates", json={"name": f"New listing {u()}", "subject": "New: {{property_address}} in {{property_city}}", "body": "Hi {{first_name}}, {{broker_name}} here about {{property_address}} at {{list_price}} for {{company}}."}, headers=admin)
    assert t.status_code == 201
    assert client.post("/api/email/templates", json={"name": "dup", "subject": "s", "body": "b"}, headers=admin).status_code in (201, 409)
    l = active_listing_for(client, admin, price=7_500_000, city="Irvine")
    co = mk_company(client, admin, f"Acme {u()} LLC")
    c = mk_contact(client, admin, first="Pat", last=f"Merge{u()}")
    client.post(f"/api/contacts/{c['id']}/companies", json={"company_id": co["id"]}, headers=admin)
    r = client.post(f"/api/email/templates/{t.json()['id']}/render", json={"contact_id": c["id"], "listing_id": l["id"]}, headers=admin).json()
    assert r["subject"] == f"New: {l['address']} in Irvine" and r["body"] == f"Hi Pat, Admin Tester here about {l['address']} at $7,500,000 for {co['name']}."
    dnc = mk_contact(client, admin, do_not_contact=True, do_not_contact_reason="No")
    blocked = client.post(f"/api/email/templates/{t.json()['id']}/render", json={"contact_id": dnc["id"]}, headers=admin)
    assert blocked.status_code == 409 and "do-not-contact" in blocked.text
    assert client.post("/api/email/templates/99999999/render", json={"contact_id": c["id"]}, headers=admin).status_code == 404


def test_bulk_prepare_excludes_dnc_unsubscribed_and_missing_email_and_cannot_send(client, admin):
    t = client.post("/api/email/templates", json={"name": f"Blast {u()}", "subject": "Hello {{first_name}}", "body": "Body"}, headers=admin).json()
    tag = f"bk{u()}"
    ok = [mk_contact(client, admin, tags=[tag]) for _ in range(3)]
    dnc = mk_contact(client, admin, tags=[tag], do_not_contact=True, do_not_contact_reason="No")
    unsub = mk_contact(client, admin, tags=[tag])
    noemail = client.post("/api/contacts", json={"first_name": "No", "last_name": f"Mail{u()}", "tags": [tag]}, headers=admin).json()
    lst = client.post("/api/lists", json={"name": f"Blast list {tag}", "entity": "contact", "kind": "dynamic", "filter": {"op": "and", "conditions": [{"field": "tags", "operator": "contains", "value": tag}]}}, headers=admin).json()
    r = client.post("/api/email/bulk", json={"name": "Listing blast", "template_id": t["id"], "list_id": lst["id"]}, headers=admin)
    assert r.status_code == 201
    first = client.get(f"/api/email/bulk/{r.json()['id']}", headers=admin).json()
    token = [x for x in first["recipients"] if x["contact_id"] == unsub["id"]][0]["unsubscribe_token"]
    assert client.get("/api/public/unsubscribe", params={"token": "garbage"}).status_code == 400
    assert client.get("/api/public/unsubscribe", params={"token": token}).json()["unsubscribed"] == unsub["emails"][0]["email"].lower()
    assert client.post("/api/public/unsubscribe", params={"token": token}).status_code == 200  # idempotent
    r2 = client.post("/api/email/bulk", json={"name": "Second blast", "template_id": t["id"], "list_id": lst["id"]}, headers=admin).json()
    assert r2["counts"] == {"eligible": 3, "excluded_dnc": 1, "excluded_unsubscribed": 1, "no_email": 1} and r2["provider_connected"] is False and r2["tracking_enabled"] is False
    full = client.get(f"/api/email/bulk/{r2['id']}", headers=admin).json()["recipients"]
    assert all("unsubscribe_token" in x for x in full if x["status"] == "eligible") and all(x["subject"].startswith("Hello ") for x in full if x["status"] == "eligible")
    sent = client.post(f"/api/email/bulk/{r2['id']}/send", headers=admin)
    assert sent.status_code == 501 and "No mail provider" in sent.text
    assert client.post("/api/email/bulk", json={"name": "x", "template_id": t["id"]}, headers=admin).status_code == 422
    assert client.post("/api/email/bulk", json={"name": "x", "template_id": t["id"], "list_id": 99999999}, headers=admin).status_code == 404
    assert client.get("/api/email/summary", headers=admin).json()["unsubscribed"] >= 1


# ---------------- calendar ----------------
def test_calendar_capture_updates_last_contact_and_respects_privacy(client, admin, headers_for):
    user, h, email = fresh_user(client, admin)
    c = mk_contact(client, admin, email=f"cal{u()}@c.test")
    past = {"external_id": f"evt-{u()}", "title": "Property tour with owner", "start": now_iso(-300), "end": now_iso(-240), "location": "123 Main St", "attendees": [{"email": c["emails"][0]["email"], "name": "Owner"}, {"email": email}]}
    r = client.post("/api/calendar/events", json=past, headers=h)
    assert r.status_code == 201 and r.json()["created"] is True and r.json()["associated"]["contacts"] == [c["id"]]
    assert client.get(f"/api/contacts/{c['id']}", headers=admin).json()["last_contact_at"] is not None  # a meeting that happened counts
    again = client.post("/api/calendar/events", json={**past, "title": "Property tour (moved)"}, headers=h).json()
    assert again["created"] is False
    future = client.post("/api/calendar/events", json={"external_id": f"evt-{u()}", "title": "Lunch next week", "start": now_iso(60 * 24 * 5), "end": now_iso(60 * 24 * 5 + 60), "attendees": [{"email": c["emails"][0]["email"]}]}, headers=h)
    mine = client.get("/api/calendar/events", params={"mine": True, "start": now_iso(-1000), "end": now_iso(60 * 24 * 10)}, headers=h).json()["items"]
    assert [e["title"] for e in mine] == ["Property tour (moved)", "Lunch next week"]
    assert client.get("/api/calendar/events", params={"start": now_iso(-1000), "end": now_iso(60 * 24 * 10), "record_type": "contact", "record_id": c["id"]}, headers=headers_for("manager")).json()["items"] == []  # private
    client.post("/api/calendar/events", json={**past, "visibility": "team_metadata"}, headers=h)
    seen = client.get("/api/calendar/events", params={"start": now_iso(-1000), "end": now_iso(60 * 24 * 10), "record_type": "contact", "record_id": c["id"]}, headers=headers_for("manager")).json()["items"]
    assert len(seen) == 1 and seen[0]["title"] == "Meeting" and seen[0]["location"] is None and seen[0]["attendees"] == [{"email": c["emails"][0]["email"]}, {"email": email}]
    assert any(i["kind"] == "event" for i in client.get("/api/timeline", params={"record_type": "contact", "record_id": c["id"]}, headers=h).json()["history"])
    assert client.post("/api/calendar/events", json={**past, "external_id": "x", "end": now_iso(-400)}, headers=h).status_code == 422
    client.post("/api/email/exclusions", json={"kind": "keyword", "value": "therapy"}, headers=h)
    assert client.post("/api/calendar/events", json={**past, "external_id": "t1", "title": "Therapy session"}, headers=h).json()["stored"] is False


# ---------------- mobile ----------------
def test_quick_add_note_task_call_log_and_idempotent_retry(client, admin):
    c = mk_contact(client, admin)
    rec = {"record_type": "contact", "record_id": c["id"]}
    n = client.post("/api/quick-add", json={"kind": "note", "text": "Met at the site: wants 5.4M", **rec}, headers=admin)
    assert n.status_code == 201 and n.json()["kind"] == "note"
    t = client.post("/api/quick-add", json={"kind": "task", "subject": "Send comps", **rec}, headers=admin).json()
    assert datetime.fromisoformat(t["due_at"]).date() == (datetime.utcnow() + timedelta(days=1)).date()
    cid = f"offline-{u()}"
    first = client.post("/api/quick-add", json={"kind": "call_log", "subject": "Quick call", "outcome": "left_voicemail", "client_id": cid, **rec}, headers=admin)
    retry = client.post("/api/quick-add", json={"kind": "call_log", "subject": "Quick call", "outcome": "left_voicemail", "client_id": cid, **rec}, headers=admin)
    assert first.status_code == 201 and retry.json()["duplicate"] is True and retry.json()["id"] == first.json()["id"]
    tl = client.get("/api/timeline", params={"record_type": "contact", "record_id": c["id"]}, headers=admin).json()
    assert len([i for i in tl["history"] if i["kind"] == "activity" and i["data"]["subject"] == "Quick call"]) == 1 and any(i["kind"] == "note" for i in tl["history"]) and len(tl["upcoming"]) == 1
    for bad in ({"kind": "note", **rec}, {"kind": "task", **rec}, {"kind": "poem", "text": "x", **rec}, {"kind": "call_log", "record_type": "listing", "record_id": 1}, {"kind": "note", "text": "x", "record_type": "contact", "record_id": 99999999}):
        assert client.post("/api/quick-add", json=bad, headers=admin).status_code in (404, 422)


def test_quick_add_permissions_and_dnc(client, admin, headers_for):
    c = mk_contact(client, admin, do_not_contact=True, do_not_contact_reason="No")
    rec = {"record_type": "contact", "record_id": c["id"]}
    assert client.post("/api/quick-add", json={"kind": "note", "text": "x", **rec}, headers=headers_for("read_only")).status_code == 403
    assert client.post("/api/quick-add", json={"kind": "note", "text": "x", **rec}, headers=headers_for("assistant")).status_code == 201
    r = client.post("/api/quick-add", json={"kind": "call_log", "subject": "Call", **rec}, headers=admin)
    assert r.status_code == 409 and "do-not-contact" in r.text


def test_lookup_by_address_and_by_gps(client, admin):
    prop, llc, person = mk_owned_property(client, admin, years_held=6, maturity_months=8)
    client.patch(f"/api/properties/{prop['id']}", json={"lat": 33.6846, "lng": -117.8265}, headers=admin)
    far = mk_property(client, admin, lat=34.2, lng=-118.0)
    r = client.get("/api/lookup/address", params={"q": prop["address"]}, headers=admin).json()["items"]
    assert r[0]["id"] == prop["id"] and r[0]["owners"][0]["company"] == llc["name"] and r[0]["owners"][0]["principals"][0]["name"] == person["full_name"] and r[0]["loan_maturity_date"]
    near = client.get("/api/lookup/address", params={"lat": 33.6847, "lng": -117.8266, "radius_m": 150}, headers=admin).json()["items"]
    assert [x["id"] for x in near][0] == prop["id"] and near[0]["distance_m"] < 50 and far["id"] not in [x["id"] for x in near]
    assert client.get("/api/lookup/address", headers=admin).status_code == 422
    assert client.get("/api/lookup/address", params={"q": "x"}, headers=admin).status_code == 422


def test_caller_lookup_returns_contact_history_and_dnc(client, admin):
    prop, llc, person = mk_owned_property(client, admin, years_held=3)
    phone = f"(949) 555-{int(u()[:3], 16) % 9000 + 1000}"
    client.patch(f"/api/contacts/{person['id']}", json={"phones": [{"phone": phone}], "title": "Principal"}, headers=admin)
    client.post("/api/activities", json={"type": "call", "subject": "Discussed pricing", "status": "completed", "outcome": "spoke", "associations": [{"record_type": "contact", "record_id": person["id"]}]}, headers=admin)
    client.post("/api/notes", json={"body": "Wants a BOV before year end", "associations": [{"record_type": "contact", "record_id": person["id"]}]}, headers=admin)
    client.post("/api/notes", json={"body": "PRIVATE ADMIN THOUGHT", "visibility": "private", "associations": [{"record_type": "contact", "record_id": person["id"]}]}, headers=admin)
    r = client.get("/api/lookup/caller", params={"phone": "+1 949 " + phone.split(") ")[1].replace("-", " ")}, headers=admin).json()
    m = r["matches"][0]
    assert r["match"] and m["contact"]["id"] == person["id"] and m["contact"]["company"] == llc["name"] and m["holdings"][0]["property_id"] == prop["id"]
    assert m["recent_activity"][0]["subject"] == "Discussed pricing" and any("BOV" in n["body"] for n in m["recent_notes"])
    from tests.conftest import make_user as mu
    unknown = client.get("/api/lookup/caller", params={"phone": "(310) 555-0000"}, headers=admin).json()
    assert unknown["match"] is False and unknown["matches"] == []
    assert client.get("/api/lookup/caller", params={"phone": "12"}, headers=admin).status_code == 422


def test_caller_lookup_hides_private_notes_from_others(client, admin, headers_for):
    c = mk_contact(client, admin, phone="(714) 555-0188")
    client.post("/api/notes", json={"body": "ADMIN PRIVATE", "visibility": "private", "associations": [{"record_type": "contact", "record_id": c["id"]}]}, headers=admin)
    r = client.get("/api/lookup/caller", params={"phone": "7145550188"}, headers=headers_for("manager")).json()
    assert r["match"] and all("ADMIN PRIVATE" not in n["body"] for n in r["matches"][0]["recent_notes"])


def test_stars_for_offline_reading(client, admin):
    c, p = mk_contact(client, admin), mk_property(client, admin)
    for rt, rid in (("contact", c["id"]), ("property", p["id"])):
        assert client.post("/api/stars", json={"record_type": rt, "record_id": rid}, headers=admin).status_code == 201
    client.post("/api/stars", json={"record_type": "contact", "record_id": c["id"]}, headers=admin)  # idempotent
    items = client.get("/api/stars", headers=admin).json()["items"]
    assert [x["label"] for x in items[:2]] == [p["address"], c["full_name"]]
    assert client.delete(f"/api/stars/contact/{c['id']}", headers=admin).status_code == 204
    assert c["id"] not in [x["record_id"] for x in client.get("/api/stars", headers=admin).json()["items"] if x["record_type"] == "contact"]
    assert client.post("/api/stars", json={"record_type": "contact", "record_id": 99999999}, headers=admin).status_code == 422
