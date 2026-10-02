from datetime import date, datetime, timedelta

import pytest

from tests.conftest import make_user
from tests.test_core import mk_company, mk_contact, mk_property, u
from tests.test_deals import mk_deal


def login(client, email, password="pw12345"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r


def hdr(client, email, password="pw12345"):
    r = login(client, email, password)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def mk_user(client, admin, role="broker", team=None, **kw):
    body = {"email": f"{role}{u()}@sec.test", "name": f"Sec {role.title()} {u()}", "role": role, "team": team, "password": "longpass1", **kw}
    r = client.post("/api/admin/users", json=body, headers=admin)
    assert r.status_code == 201, r.text
    return r.json(), body


# ---------------- users and roles ----------------
def test_user_admin_is_admin_only_and_validated(client, admin, headers_for):
    for role in ("manager", "broker", "assistant", "read_only"):
        assert client.get("/api/admin/users", headers=headers_for(role)).status_code == 403
        assert client.post("/api/admin/users", json={"email": "a@b.com", "name": "x", "password": "longpass1"}, headers=headers_for(role)).status_code == 403
    base = {"email": f"v{u()}@sec.test", "name": "V", "password": "longpass1"}
    assert client.post("/api/admin/users", json={**base, "password": "short"}, headers=admin).status_code == 422
    assert client.post("/api/admin/users", json={**base, "role": "emperor"}, headers=admin).status_code == 422
    assert client.post("/api/admin/users", json={**base, "email": "not-an-email"}, headers=admin).status_code == 422
    assert client.post("/api/admin/users", json=base, headers=admin).status_code == 201
    assert client.post("/api/admin/users", json=base, headers=admin).status_code == 409
    listing = client.get("/api/admin/users", headers=admin).json()
    assert "view" in listing["role_actions"]["read_only"] and "export" not in listing["role_actions"]["assistant"]


def test_role_change_is_audited_and_takes_effect(client, admin):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    user, body = mk_user(client, admin, "read_only")
    h = hdr(client, body["email"], "longpass1")
    assert client.post("/api/contacts", json={"first_name": "A", "last_name": "B"}, headers=h).status_code == 403
    assert client.patch(f"/api/admin/users/{user['id']}", json={"role": "broker"}, headers=admin).json()["role"] == "broker"
    assert client.post("/api/contacts", json={"first_name": "A", "last_name": f"B{u()}"}, headers=h).status_code == 201
    with SessionLocal() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "role_change", AuditEvent.entity_id == user["id"])).all()
    assert ev and ev[0].changes["from"] == "read_only" and ev[0].changes["to"] == "broker"


def test_cannot_remove_the_last_admin(client, admin):
    from app.db import SessionLocal
    from app.models.core_sys import User
    from sqlalchemy import select
    me = client.get("/api/auth/me", headers=admin).json()
    with SessionLocal() as db:
        others = db.scalars(select(User).where(User.role == "admin", User.active.is_(True), User.id != me["id"])).all()
        for o in others:
            o.active = False
        db.commit()
    try:
        assert client.patch(f"/api/admin/users/{me['id']}", json={"role": "manager"}, headers=admin).status_code == 409
        assert client.post(f"/api/admin/users/{me['id']}/deactivate", json={}, headers=admin).status_code == 409
    finally:
        with SessionLocal() as db:
            for o in others:
                db.get(User, o.id).active = True
            db.commit()


def test_password_reset_change_and_login_lockout(client, admin):
    user, body = mk_user(client, admin)
    assert login(client, body["email"], "longpass1").status_code == 200
    assert client.post(f"/api/admin/users/{user['id']}/reset-password", json={"password": "short"}, headers=admin).status_code == 422
    assert client.post(f"/api/admin/users/{user['id']}/reset-password", json={"password": "brandnew99"}, headers=admin).status_code == 200
    assert login(client, body["email"], "longpass1").status_code == 401
    h = hdr(client, body["email"], "brandnew99")
    assert client.post("/api/auth/change-password", json={"current_password": "wrong", "new_password": "another123"}, headers=h).status_code == 403
    assert client.post("/api/auth/change-password", json={"current_password": "brandnew99", "new_password": "another123"}, headers=h).status_code == 200
    assert login(client, body["email"], "another123").status_code == 200
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    # lockout: five failures within 15 minutes block even the right password
    victim, vb = mk_user(client, admin)
    for _ in range(5):
        assert login(client, vb["email"], "nope").status_code == 401
    locked = login(client, vb["email"], "longpass1")
    assert locked.status_code == 429 and "Too many" in locked.text
    with SessionLocal() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "login_locked")) is not None
        assert {e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "users", AuditEvent.entity_id == user["id"]))} >= {"password_reset", "password_change"}


def test_deactivation_requires_reassignment_and_offboards(client, admin):
    leaver, lb = mk_user(client, admin)
    stayer, sb = mk_user(client, admin)
    h = hdr(client, lb["email"], "longpass1")
    c = client.post("/api/contacts", json={"first_name": "Own", "last_name": f"Ed{u()}"}, headers=h).json()
    p = client.post("/api/properties", json={"address": f"{u()} Leaver Ln", "city": "Irvine", "property_type": "retail"}, headers=h).json()
    client.post("/api/activities", json={"type": "other", "subject": "Open task", "due_at": (datetime.now() + timedelta(days=3)).isoformat(), "associations": [{"record_type": "contact", "record_id": c["id"]}]}, headers=h)
    tok = client.post("/api/tokens", json={"name": "script", "scopes": ["view"]}, headers=h).json()["token"]
    assert client.get("/api/contacts", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    r = client.post(f"/api/admin/users/{leaver['id']}/deactivate", json={}, headers=admin)
    assert r.status_code == 409 and r.json()["detail"]["owned"]["contact"] >= 1 and r.json()["detail"]["open_tasks"] >= 1
    assert client.post(f"/api/admin/users/{leaver['id']}/deactivate", json={"reassign_to": leaver["id"]}, headers=admin).status_code == 422
    done = client.post(f"/api/admin/users/{leaver['id']}/deactivate", json={"reassign_to": stayer["id"]}, headers=admin)
    assert done.status_code == 200 and done.json()["reassigned"]["contact"] >= 1 and done.json()["user"]["active"] is False
    assert client.get(f"/api/contacts/{c['id']}", headers=admin).json()["owner_user_id"] == stayer["id"]
    assert client.get(f"/api/properties/{p['id']}", headers=admin).json()["owner_user_id"] == stayer["id"]
    assert login(client, lb["email"], "longpass1").status_code == 401  # cannot sign in
    assert client.get("/api/contacts", headers={"Authorization": f"Bearer {tok}"}).status_code == 401  # API tokens revoked
    tasks = client.get("/api/activities", params={"assignee_id": stayer["id"], "status": "planned"}, headers=admin).json()["items"]
    assert any(t["subject"] == "Open task" for t in tasks)
    assert client.post(f"/api/admin/users/{leaver['id']}/reactivate", headers=admin).json()["active"] is True


def test_ownership_transfer_single_bulk_and_limits(client, admin, headers_for):
    a, ab = mk_user(client, admin)
    b, bb = mk_user(client, admin)
    ha, hb = hdr(client, ab["email"], "longpass1"), hdr(client, bb["email"], "longpass1")
    cs = [client.post("/api/contacts", json={"first_name": "T", "last_name": f"R{u()}"}, headers=ha).json() for _ in range(3)]
    mine, theirs = [c["id"] for c in cs[:2]], cs[2]["id"]
    assert client.post("/api/ownership/transfer", json={"entity": "contact", "ids": [theirs], "to_user_id": b["id"]}, headers=hb).status_code == 403  # b does not own it
    r = client.post("/api/ownership/transfer", json={"entity": "contact", "ids": mine, "to_user_id": b["id"]}, headers=ha)
    assert r.status_code == 200 and r.json()["transferred"] == 2
    assert all(client.get(f"/api/contacts/{i}", headers=admin).json()["owner_user_id"] == b["id"] for i in mine)
    assert client.post("/api/ownership/transfer", json={"entity": "contact", "ids": [theirs], "to_user_id": b["id"]}, headers=headers_for("manager")).status_code == 200
    assert client.post("/api/ownership/transfer", json={"entity": "contact", "ids": [theirs], "to_user_id": 99999999}, headers=admin).status_code == 422
    assert client.post("/api/ownership/transfer", json={"entity": "wizard", "ids": [1], "to_user_id": b["id"]}, headers=admin).status_code == 422
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    with SessionLocal() as db:
        n = len(db.scalars(select(AuditEvent).where(AuditEvent.action == "ownership_transfer", AuditEvent.entity_type == "contacts")).all())
    assert n >= 3


# ---------------- API tokens ----------------
def test_api_token_lifecycle_scopes_and_audit(client, admin, headers_for):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    from app.models.security import ApiToken
    user, body = mk_user(client, admin, "broker")
    h = hdr(client, body["email"], "longpass1")
    assert client.post("/api/tokens", json={"name": "x", "scopes": ["admin"]}, headers=h).status_code == 422  # a broker cannot mint admin power
    assert client.post("/api/tokens", json={"name": "x", "scopes": []}, headers=h).status_code == 422
    t = client.post("/api/tokens", json={"name": "CI script", "scopes": ["view", "create"], "expires_days": 30}, headers=h)
    assert t.status_code == 201 and t.json()["token"].startswith("trg_") and "shown only once" in t.json()["note"]
    token, tid = t.json()["token"], t.json()["id"]
    tok = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/contacts", headers=tok).status_code == 200
    created = client.post("/api/contacts", json={"first_name": "Api", "last_name": f"Made{u()}"}, headers=tok)
    assert created.status_code == 201
    assert client.patch(f"/api/contacts/{created.json()['id']}", json={"title": "x"}, headers=tok).status_code == 403  # edit is not in the token's scope
    assert "not scoped" in client.patch(f"/api/contacts/{created.json()['id']}", json={"title": "x"}, headers=tok).text
    assert client.post("/api/tokens", json={"name": "child", "scopes": ["view"]}, headers=tok).status_code == 403  # tokens cannot mint tokens
    assert client.post("/api/auth/change-password", json={"current_password": "longpass1", "new_password": "x" * 9}, headers=tok).status_code == 403
    listed = client.get("/api/tokens", headers=h).json()["items"]
    assert [x["id"] for x in listed] == [tid] and listed[0]["last_used_at"] and "token" not in listed[0] and listed[0]["active"]
    assert client.get("/api/tokens", headers=headers_for("manager")).json()["items"] == []  # others cannot see mine
    assert tid in [x["id"] for x in client.get("/api/tokens", params={"all": True}, headers=admin).json()["items"]]
    with SessionLocal() as db:
        uses = db.scalars(select(AuditEvent).where(AuditEvent.action == "api_token_use", AuditEvent.entity_id == tid)).all()
        stored = db.get(ApiToken, tid)
        assert stored.token_hash != token and token not in str(stored.__dict__)  # only a hash is stored
        assert created.json()["id"] and "API token 'CI script'" in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "contacts", AuditEvent.entity_id == created.json()["id"], AuditEvent.action == "create")).first().actor
    assert len(uses) >= 4 and {"method", "path"} <= set(uses[0].changes)
    assert client.delete(f"/api/tokens/{tid}", headers=headers_for("assistant")).status_code == 404
    assert client.delete(f"/api/tokens/{tid}", headers=h).status_code == 204
    assert client.get("/api/contacts", headers=tok).status_code == 401
    assert client.get("/api/contacts", headers={"Authorization": "Bearer trg_deadbeef_nonsense"}).status_code == 401


def test_expired_token_and_role_ceiling(client, admin):
    from app.db import SessionLocal
    from app.models.security import ApiToken
    user, body = mk_user(client, admin, "broker")
    h = hdr(client, body["email"], "longpass1")
    t = client.post("/api/tokens", json={"name": "short", "scopes": ["view", "delete"]}, headers=h)
    assert t.status_code == 422  # delete is not a broker action
    t = client.post("/api/tokens", json={"name": "short", "scopes": ["view", "export"]}, headers=h).json()
    client.patch(f"/api/admin/users/{user['id']}", json={"role": "read_only"}, headers=admin)  # demote after minting: the token cannot keep export
    tok = {"Authorization": f"Bearer {t['token']}"}
    assert client.get("/api/contacts", headers=tok).status_code == 200
    assert client.get("/api/export/contact", headers=tok).status_code == 403
    with SessionLocal() as db:
        db.get(ApiToken, t["id"]).expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    assert client.get("/api/contacts", headers=tok).status_code == 401


# ---------------- audit ----------------
def test_audit_is_append_only_and_admin_only(client, admin, headers_for):
    import pytest as pt
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    mk_contact(client, admin)
    with SessionLocal() as db:
        ev = db.scalars(select(AuditEvent).limit(1)).first()
        ev.action = "tampered"
        with pt.raises(ValueError):
            db.flush()
        db.rollback()
        db.delete(db.scalars(select(AuditEvent).limit(1)).first())
        with pt.raises(ValueError):
            db.flush()
        db.rollback()
    for role in ("manager", "broker", "assistant", "read_only"):
        assert client.get("/api/audit", headers=headers_for(role)).status_code == 403
    assert client.get("/api/audit", headers=admin).status_code == 200


def test_audit_filters_and_field_history(client, admin):
    users = {x["name"]: x["id"] for x in client.get("/api/auth/users", headers=admin).json()}
    d = mk_deal(client, admin, price=1_000_000, commission_rate_bps=300)
    client.patch(f"/api/deals/{d['id']}", json={"price": 1_200_000}, headers=admin)
    client.post(f"/api/deals/{d['id']}/stage", json={"stage": "pitch"}, headers=admin)
    client.patch(f"/api/deals/{d['id']}", json={"price": 1_500_000, "owner_user_id": users["Manager Tester"]}, headers=admin)
    h = client.get("/api/audit/field-history", params={"entity_type": "deals", "entity_id": d["id"], "field": "price"}, headers=admin).json()["items"]
    assert [(x["from"], x["to"]) for x in h] == [(None, 1_000_000), (1_000_000, 1_200_000), (1_200_000, 1_500_000)] and h[0]["actor"] == "Admin Tester"
    st = client.get("/api/audit/field-history", params={"entity_type": "deals", "entity_id": d["id"], "field": "stage_id"}, headers=admin).json()["items"]
    assert [x["to"] for x in st][-1] == "Pitch"
    ow = client.get("/api/audit/field-history", params={"entity_type": "deals", "entity_id": d["id"], "field": "owner_user_id"}, headers=admin).json()["items"]
    assert ow[-1]["to"] == "Manager Tester"
    comm = client.get("/api/audit/field-history", params={"entity_type": "deals", "entity_id": d["id"], "field": "gross_commission"}, headers=admin).json()["items"]
    assert comm == [] or all(x["to"] == "changed" for x in comm)  # sensitive values are never stored
    assert client.get("/api/audit/field-history", params={"entity_type": "deals", "entity_id": d["id"], "field": "name"}, headers=admin).status_code == 422
    ev = client.get("/api/audit", params={"entity_type": "deals", "entity_id": d["id"], "action": "update"}, headers=admin).json()
    assert ev["total"] >= 3 and all(e["entity_id"] == d["id"] and e["action"] == "update" for e in ev["items"])
    assert ev["items"][0]["id"] > ev["items"][-1]["id"]
    by_user = client.get("/api/audit", params={"user_id": users["Admin Tester"], "entity_type": "deals"}, headers=admin).json()
    assert by_user["total"] >= 3
    assert "login" in client.get("/api/audit/facets", headers=admin).json()["actions"]
    future = (datetime.utcnow() + timedelta(days=1)).isoformat()
    assert client.get("/api/audit", params={"start": future}, headers=admin).json()["total"] == 0


def test_merges_and_exports_leave_audit_events(client, admin):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    a, b = mk_contact(client, admin, last=f"Au{u()}"), mk_contact(client, admin, last=f"Au{u()}")
    mid = client.post("/api/merge", json={"entity": "contact", "survivor_id": a["id"], "absorbed_id": b["id"]}, headers=admin).json()["merge_id"]
    client.post(f"/api/merges/{mid}/undo", headers=admin)
    with SessionLocal() as db:
        acts = {e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "merge_logs", AuditEvent.entity_id == mid))}
    assert {"merge", "merge_undo"} <= acts


# ---------------- visibility setting ----------------
def test_team_scoped_visibility_setting(client, admin, headers_for):
    ua, ba = mk_user(client, admin, "broker", team="Team Alpha")
    ub, bb = mk_user(client, admin, "broker", team="Team Beta")
    uc, bc = mk_user(client, admin, "broker", team="Team Alpha")
    ha, hb, hc = hdr(client, ba["email"], "longpass1"), hdr(client, bb["email"], "longpass1"), hdr(client, bc["email"], "longpass1")
    c = client.post("/api/contacts", json={"first_name": "Team", "last_name": f"Scoped{u()}"}, headers=ha).json()
    assert client.get(f"/api/contacts/{c['id']}", headers=hb).status_code == 200  # firm-open by default
    assert client.put("/api/settings/visibility", json={"mode": "team_scoped"}, headers=headers_for("manager")).status_code == 403
    assert client.put("/api/settings/visibility", json={"mode": "everybody"}, headers=admin).status_code == 422
    try:
        assert client.put("/api/settings/visibility", json={"mode": "team_scoped"}, headers=admin).json()["visibility_mode"] == "team_scoped"
        assert client.get(f"/api/contacts/{c['id']}", headers=hb).status_code == 404
        assert c["id"] not in [x["id"] for x in client.get("/api/contacts", params={"q": c["last_name"]}, headers=hb).json()["items"]]
        assert c["id"] not in [x["id"] for x in client.get("/api/search", params={"q": c["last_name"]}, headers=hb).json()["results"]]
        assert client.get(f"/api/contacts/{c['id']}", headers=hc).status_code == 200  # same team
        assert client.get(f"/api/contacts/{c['id']}", headers=ha).status_code == 200  # owner
        assert client.get(f"/api/contacts/{c['id']}", headers=headers_for("manager")).status_code == 200  # managers see the firm
        assert client.get("/api/settings", headers=hb).json()["visibility_mode"] == "team_scoped"
    finally:
        client.put("/api/settings/visibility", json={"mode": "firm_open"}, headers=admin)
    assert client.get(f"/api/contacts/{c['id']}", headers=hb).status_code == 200


# ---------------- workflow rules ----------------
def rule_body(name=None, **kw):
    base = {"name": name or f"Rule {u()}", "entity": "contact", "trigger_type": "record_created", "actions": [{"type": "create_task", "params": {"subject": "Welcome call for {name}", "days_due": 1, "type": "call"}}]}
    base.update(kw)
    return base


def mk_rule(client, h, **kw):
    r = client.post("/api/rules", json=rule_body(**kw), headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def tasks_for(client, h, rtype, rid):
    return client.get("/api/activities", params={"record_type": rtype, "record_id": rid}, headers=h).json()["items"]


def test_rule_validation(client, admin, headers_for):
    assert client.post("/api/rules", json=rule_body(), headers=headers_for("broker")).status_code == 403
    assert client.get("/api/rules", headers=headers_for("read_only")).status_code == 200
    bad = lambda **kw: client.post("/api/rules", json=rule_body(**kw), headers=admin)  # noqa: E731
    assert bad(entity="widget").status_code == 422
    assert bad(trigger_type="telepathy").status_code == 422
    assert bad(actions=[]).status_code == 422
    r = bad(actions=[{"type": "send_email", "params": {}}])
    assert r.status_code == 422 and "cannot send email" in r.text
    assert bad(actions=[{"type": "assign_owner", "params": {"user_id": 99999999}}]).status_code == 422
    assert bad(actions=[{"type": "create_task", "params": {}}]).status_code == 422
    assert bad(actions=[{"type": "create_task", "params": {"subject": "x", "days_due": -1}}]).status_code == 422
    assert bad(actions=[{"type": "create_lead", "params": {}}]).status_code == 422  # contacts cannot create property leads
    assert bad(actions=[{"type": "set_field", "params": {"field": "last_name", "value": "x"}}]).status_code == 422
    assert bad(actions=[{"type": "set_field", "params": {"field": "lifecycle_stage", "value": "wizard"}}]).status_code == 422
    assert bad(trigger_type="field_changed", trigger_config={}).status_code == 422
    assert bad(trigger_type="field_changed", trigger_config={"field": "nonexistent"}).status_code == 422
    assert bad(trigger_type="stage_changed").status_code == 422  # deals only
    assert bad(trigger_type="date_reached", trigger_config={"date_field": "nope"}).status_code == 422
    assert bad(conditions={"op": "and", "conditions": [{"field": "zzz", "operator": "eq", "value": 1}]}).status_code == 422
    assert bad(actions=[{"type": "apply_cadence", "params": {"cadence_id": 99999999}}]).status_code == 422


def test_record_created_rule_is_idempotent_and_attributed_to_the_rule(client, admin):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    t = f"zz{u()}"
    rule = mk_rule(client, admin, name=f"Welcome {t}", conditions={"op": "and", "conditions": [{"field": "tags", "operator": "contains", "value": t}]})
    hit = client.post("/api/contacts", json={"first_name": "Hit", "last_name": f"Me{t}", "tags": [t]}, headers=admin).json()
    miss = client.post("/api/contacts", json={"first_name": "Miss", "last_name": f"Me{u()}"}, headers=admin).json()
    r = client.post(f"/api/rules/{rule['id']}/run", headers=admin).json()
    assert r["matched"] == 1 and r["actions"] == 1
    t1 = tasks_for(client, admin, "contact", hit["id"])
    assert len(t1) == 1 and t1[0]["subject"] == f"Welcome call for {hit['full_name']}" and t1[0]["type"] == "call"
    assert datetime.fromisoformat(t1[0]["due_at"]).date() == date.today() + timedelta(days=1)
    assert tasks_for(client, admin, "contact", miss["id"]) == []
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    client.post("/api/jobs/rules_events/run", headers=admin)
    assert len(tasks_for(client, admin, "contact", hit["id"])) == 1  # re-running never duplicates
    log = client.get(f"/api/rules/{rule['id']}/log", headers=admin).json()["items"]
    assert len(log) == 1 and log[0]["entity_id"] == hit["id"] and log[0]["action"] == "create_task"
    with SessionLocal() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "activities", AuditEvent.actor == f"rule:Welcome {t}")).all()
    assert len(ev) == 1  # every action is audited with the rule as the actor
    runs = client.get(f"/api/rules/{rule['id']}/runs", headers=admin).json()["items"]
    assert runs[-1]["matched"] == 1 and runs[0]["status"] == "ok"


def test_rules_only_react_to_changes_after_they_exist(client, admin):
    t = f"zz{u()}"
    old = client.post("/api/contacts", json={"first_name": "Old", "last_name": f"Rec{t}", "tags": [t]}, headers=admin).json()
    rule = mk_rule(client, admin, conditions={"op": "and", "conditions": [{"field": "tags", "operator": "contains", "value": t}]})
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    assert tasks_for(client, admin, "contact", old["id"]) == []


def test_field_changed_rule_with_value_filter_notify_and_set_field(client, admin):
    users = {x["name"]: x["id"] for x in client.get("/api/auth/users", headers=admin).json()}
    rule = mk_rule(client, admin, entity="property", trigger_type="field_changed", trigger_config={"field": "hold_intent", "to": "selling_soon"},
                   actions=[{"type": "create_task", "params": {"subject": "Call owner of {name} now", "days_due": 0, "type": "call", "priority": "high"}},
                            {"type": "notify", "params": {"message": "{name} just became a hot seller"}}])
    p1, p2 = mk_property(client, admin, owner_user_id=users["Broker Tester"]), mk_property(client, admin)
    client.patch(f"/api/properties/{p1['id']}", json={"hold_intent": "selling_soon"}, headers=admin)
    client.patch(f"/api/properties/{p2['id']}", json={"hold_intent": "hold"}, headers=admin)  # different value: no match
    out = client.post(f"/api/rules/{rule['id']}/run", headers=admin).json()
    assert out["matched"] == 1
    task = tasks_for(client, admin, "property", p1["id"])[0]
    assert task["priority"] == "high" and task["subject"] == f"Call owner of {p1['address']} now" and task["assignee_user_id"] == users["Broker Tester"]
    assert tasks_for(client, admin, "property", p2["id"]) == []


def test_notify_reaches_the_record_owner(client, admin, headers_for):
    users = {x["name"]: x["id"] for x in client.get("/api/auth/users", headers=admin).json()}
    rule = mk_rule(client, admin, entity="property", trigger_type="field_changed", trigger_config={"field": "hold_intent", "to": "open_to_sell"}, actions=[{"type": "notify", "params": {"message": f"Heads up {u()}: {{name}}"}}])
    p = mk_property(client, admin, owner_user_id=users["Broker Tester"])
    client.patch(f"/api/properties/{p['id']}", json={"hold_intent": "open_to_sell"}, headers=admin)
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    msgs = [n["message"] for n in client.get("/api/notifications", headers=headers_for("broker")).json()["items"]]
    assert any(p["address"] in m and m.startswith("Heads up") for m in msgs)


def test_stage_changed_rule_on_deals(client, admin):
    rule = mk_rule(client, admin, entity="deal", trigger_type="stage_changed", trigger_config={"to_stage": "under_contract"}, actions=[{"type": "create_task", "params": {"subject": "Order title and escrow for {name}", "days_due": 2}}])
    d1, d2 = mk_deal(client, admin, price=1_000_000), mk_deal(client, admin, price=1_000_000)
    client.post(f"/api/deals/{d1['id']}/stage", json={"stage": "under_contract"}, headers=admin)
    client.post(f"/api/deals/{d2['id']}/stage", json={"stage": "pitch"}, headers=admin)
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    assert any(t["subject"].startswith("Order title and escrow") for t in tasks_for(client, admin, "deal", d1["id"]))
    assert not any(t["subject"].startswith("Order title") for t in tasks_for(client, admin, "deal", d2["id"]))


def test_date_reached_rule_offsets_and_idempotency(client, admin):
    soon = (date.today() + timedelta(days=150)).isoformat()
    far = (date.today() + timedelta(days=400)).isoformat()
    a, b = mk_property(client, admin, loan_maturity_date=soon), mk_property(client, admin, loan_maturity_date=far)
    rule = mk_rule(client, admin, entity="property", trigger_type="date_reached", trigger_config={"date_field": "loan_maturity_date", "offset_days": -180},
                   actions=[{"type": "create_task", "params": {"subject": "Loan matures in ~6 months: open the refi-or-sell conversation", "days_due": 0}}],
                   conditions={"op": "and", "conditions": [{"field": "tags", "operator": "is_empty"}]})
    run = client.post(f"/api/rules/{rule['id']}/run", headers=admin).json()
    assert run["matched"] >= 1 and a["id"] in [x["entity_id"] for x in client.get(f"/api/rules/{rule['id']}/log", headers=admin).json()["items"]]
    assert len(tasks_for(client, admin, "property", a["id"])) == 1 and tasks_for(client, admin, "property", b["id"]) == []
    again = client.post(f"/api/rules/{rule['id']}/run", headers=admin).json()
    assert again["actions_taken"] == 0 and len(tasks_for(client, admin, "property", a["id"])) == 1
    # the date moved: a new trigger instance, a new task
    client.patch(f"/api/properties/{a['id']}", json={"loan_maturity_date": (date.today() + timedelta(days=170)).isoformat()}, headers=admin)  # still inside the 30-day grace window after (date - 180)
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    assert len(tasks_for(client, admin, "property", a["id"])) == 2


def test_scheduled_rule_with_cooldown_assign_owner_set_field_and_cadence(client, admin):
    users = {x["name"]: x["id"] for x in client.get("/api/auth/users", headers=admin).json()}
    cad = client.post("/api/cadences", json={"name": f"Rule cad {u()}", "record_type": "contact", "steps": [{"day_offset": 0, "type": "other", "subject": "Step zero"}, {"day_offset": 5, "type": "other", "subject": "Step five"}]}, headers=admin).json()
    t = f"zz{u()}"
    rule = mk_rule(client, admin, trigger_type="scheduled", trigger_config={"cooldown_days": 30}, conditions={"op": "and", "conditions": [{"field": "tags", "operator": "contains", "value": t}]},
                   actions=[{"type": "assign_owner", "params": {"user_id": users["Manager Tester"]}}, {"type": "set_field", "params": {"field": "lifecycle_stage", "value": "active_relationship"}}, {"type": "apply_cadence", "params": {"cadence_id": cad["id"]}}])
    c = client.post("/api/contacts", json={"first_name": "Sched", "last_name": f"Rule{t}", "tags": [t]}, headers=admin).json()
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    got = client.get(f"/api/contacts/{c['id']}", headers=admin).json()
    assert got["owner_user_id"] == users["Manager Tester"] and got["lifecycle_stage"] == "active_relationship"
    assert sorted(x["subject"] for x in tasks_for(client, admin, "contact", c["id"])) == ["Step five", "Step zero"]
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    assert len(tasks_for(client, admin, "contact", c["id"])) == 2  # inside the cooldown nothing repeats


def test_do_not_contact_is_respected_by_outreach_actions(client, admin):
    t = f"zz{u()}"
    rule = mk_rule(client, admin, trigger_type="scheduled", conditions={"op": "and", "conditions": [{"field": "tags", "operator": "contains", "value": t}]},
                   actions=[{"type": "create_task", "params": {"subject": "Call", "type": "call", "days_due": 0}}, {"type": "create_task", "params": {"subject": "Internal review", "type": "other", "days_due": 0}}])
    c = client.post("/api/contacts", json={"first_name": "No", "last_name": f"Calls{t}", "tags": [t], "do_not_contact": True, "do_not_contact_reason": "Asked"}, headers=admin).json()
    out = client.post(f"/api/rules/{rule['id']}/run", headers=admin).json()
    subjects = [x["subject"] for x in tasks_for(client, admin, "contact", c["id"])]
    assert subjects == ["Internal review"]
    results = [x["result"] for x in client.get(f"/api/rules/{rule['id']}/log", headers=admin).json()["items"]]
    assert "skipped: do-not-contact" in results


def test_create_lead_action_and_open_lead_guard(client, admin):
    from tests.test_prospecting_listings import mk_owned_property
    prop, llc, person = mk_owned_property(client, admin, years_held=3)
    rule = mk_rule(client, admin, entity="property", trigger_type="field_changed", trigger_config={"field": "hold_intent", "to": "selling_soon"}, actions=[{"type": "create_lead", "params": {}}])
    client.patch(f"/api/properties/{prop['id']}", json={"hold_intent": "selling_soon"}, headers=admin)
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    leads = client.get("/api/leads", params={"q": person["full_name"]}, headers=admin).json()["items"]
    assert len(leads) == 1 and leads[0]["property_id"] == prop["id"] and leads[0]["source"] == "Workflow rule" and leads[0]["trigger_reason"]["matches"][0]["kind"] == "workflow"
    client.patch(f"/api/properties/{prop['id']}", json={"hold_intent": "hold"}, headers=admin)
    client.patch(f"/api/properties/{prop['id']}", json={"hold_intent": "selling_soon"}, headers=admin)
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    assert len(client.get("/api/leads", params={"q": person["full_name"]}, headers=admin).json()["items"]) == 1  # an open lead already exists


def test_preview_writes_nothing_and_disabled_rules_do_not_fire(client, admin):
    t = f"zz{u()}"
    rule = mk_rule(client, admin, trigger_type="scheduled", conditions={"op": "and", "conditions": [{"field": "tags", "operator": "contains", "value": t}]})
    c = client.post("/api/contacts", json={"first_name": "Pre", "last_name": f"View{t}", "tags": [t]}, headers=admin).json()
    pv = client.post(f"/api/rules/{rule['id']}/preview", headers=admin).json()
    assert pv["matched"] == 1 and pv["sample"][0]["entity_id"] == c["id"]
    assert tasks_for(client, admin, "contact", c["id"]) == [] and client.get(f"/api/rules/{rule['id']}/log", headers=admin).json()["items"] == []
    assert client.patch(f"/api/rules/{rule['id']}", json={"enabled": False}, headers=admin).json()["enabled"] is False
    client.post("/api/jobs/rules_scheduled/run", headers=admin)
    assert tasks_for(client, admin, "contact", c["id"]) == []
    client.patch(f"/api/rules/{rule['id']}", json={"enabled": True}, headers=admin)
    client.post("/api/jobs/rules_scheduled/run", headers=admin)
    assert len(tasks_for(client, admin, "contact", c["id"])) == 1


def test_rule_with_history_is_disabled_not_deleted_and_run_is_admin_only(client, admin, headers_for):
    t = f"zz{u()}"
    rule = mk_rule(client, admin, trigger_type="scheduled", conditions={"op": "and", "conditions": [{"field": "tags", "operator": "contains", "value": t}]})
    client.post("/api/contacts", json={"first_name": "H", "last_name": f"Ist{t}", "tags": [t]}, headers=admin)
    assert client.post(f"/api/rules/{rule['id']}/run", headers=headers_for("manager")).status_code == 403
    client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    assert client.delete(f"/api/rules/{rule['id']}", headers=admin).status_code == 204
    kept = [r for r in client.get("/api/rules", headers=admin).json()["items"] if r["id"] == rule["id"]]
    assert kept and kept[0]["enabled"] is False  # history stays attributable
    fresh = mk_rule(client, admin)
    assert client.delete(f"/api/rules/{fresh['id']}", headers=admin).status_code == 204
    assert fresh["id"] not in [r["id"] for r in client.get("/api/rules", headers=admin).json()["items"]]


def test_a_rules_own_writes_do_not_retrigger_rules(client, admin):
    """A field_changed rule that sets the field it watches must not loop."""
    t = f"zz{u()}"
    rule = mk_rule(client, admin, entity="contact", trigger_type="field_changed", trigger_config={"field": "lifecycle_stage"},
                   actions=[{"type": "create_task", "params": {"subject": "Stage changed", "days_due": 1}}, {"type": "set_field", "params": {"field": "status", "value": "active"}}])
    c = mk_contact(client, admin)
    client.patch(f"/api/contacts/{c['id']}", json={"lifecycle_stage": "client"}, headers=admin)
    for _ in range(3):
        client.post(f"/api/rules/{rule['id']}/run", headers=admin)
    assert len([x for x in tasks_for(client, admin, "contact", c["id"]) if x["subject"] == "Stage changed"]) == 1
