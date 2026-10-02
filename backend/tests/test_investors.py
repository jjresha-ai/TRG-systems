from datetime import date, timedelta

from tests.test_core import mk_company, mk_contact, mk_property, u
from tests.test_prospecting_listings import ACTIVE


def mk_investor(client, h, **kw):
    c = mk_contact(client, h, contact_types=["buyer"])
    body = {"contact_id": c["id"], "asset_classes": ["industrial"], "markets": ["Inland Empire"], "min_check": 1_000_000, "max_check": 5_000_000, "accreditation_status": "accredited",
            "accreditation_verified_on": date.today().isoformat(), **kw}
    r = client.post("/api/investors", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json(), c


def mk_fund(client, h, **kw):
    r = client.post("/api/funds", json={"name": f"Fund {u()}", "target_raise": 10_000_000, "minimum_investment": 100_000, "status": "raising", **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def active_listing_for(client, h, price=10_000_000, **prop_kw):
    prop = mk_property(client, h, estimated_value=price, noi=int(price * 0.055), **prop_kw)
    l = client.post("/api/listings", json={"property_id": prop["id"]}, headers=h).json()
    r = client.post(f"/api/listings/{l['id']}/status", json={"status": "active", "list_price": price, "agreement_date": date.today().isoformat(), "expiration_date": (date.today() + timedelta(days=180)).isoformat()}, headers=h)
    assert r.status_code == 200, r.text
    return l


def test_profile_requires_owner_and_is_unique(client, admin):
    assert client.post("/api/investors", json={"asset_classes": ["retail"]}, headers=admin).status_code == 422
    inv, c = mk_investor(client, admin)
    assert client.post("/api/investors", json={"contact_id": c["id"]}, headers=admin).status_code == 409
    assert "investor" in client.get(f"/api/contacts/{c['id']}", headers=admin).json()["contact_types"]
    co = mk_company(client, admin)
    assert client.post("/api/investors", json={"company_id": co["id"], "asset_classes": ["retail"]}, headers=admin).status_code == 201


def test_profile_validation(client, admin):
    c = mk_contact(client, admin)
    assert client.post("/api/investors", json={"contact_id": c["id"], "min_check": 5, "max_check": 1}, headers=admin).status_code == 422
    assert client.post("/api/investors", json={"contact_id": c["id"], "asset_classes": ["hotel"]}, headers=admin).status_code == 422
    assert client.post("/api/investors", json={"contact_id": c["id"], "accreditation_status": "maybe"}, headers=admin).status_code == 422
    assert client.post("/api/investors", json={"contact_id": c["id"], "preferred_channel": "fax"}, headers=admin).status_code == 422


def test_accreditation_hidden_from_restricted_roles_and_access_audited(client, admin, headers_for):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    inv, c = mk_investor(client, admin)
    for role in ("assistant", "read_only"):
        got = client.get(f"/api/investors/{inv['id']}", headers=headers_for(role)).json()
        assert "accreditation_status" not in got and "accreditation_verified_on" not in got
        listed = client.get("/api/investors", headers=headers_for(role)).json()["items"]
        assert all("accreditation_status" not in x for x in listed)
        assert client.get("/api/investors", params={"accreditation": "accredited"}, headers=headers_for(role)).status_code == 403
    assert client.patch(f"/api/investors/{inv['id']}", json={"accreditation_status": "pending"}, headers=headers_for("assistant")).status_code == 403
    assert client.get(f"/api/investors/{inv['id']}", headers=headers_for("broker")).json()["accreditation_status"] == "accredited"
    with SessionLocal() as db:
        views = db.scalars(select(AuditEvent).where(AuditEvent.action == "view_investor_profile", AuditEvent.entity_id == inv["id"])).all()
        changes = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "investor_profiles", AuditEvent.entity_id == inv["id"], AuditEvent.action == "create")).all()
    assert len(views) >= 1
    assert "accreditation_status" not in changes[0].changes  # sensitive value is never stored in the audit trail


def test_accreditation_change_is_audited_without_value(client, admin):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    inv, _ = mk_investor(client, admin)
    client.patch(f"/api/investors/{inv['id']}", json={"accreditation_status": "pending"}, headers=admin)
    with SessionLocal() as db:
        ev = [e for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "investor_profiles", AuditEvent.entity_id == inv["id"], AuditEvent.action == "update"))][0]
    assert ev.changes["accreditation_status"] == ["changed", "changed"]


def test_fund_create_and_validation(client, admin, headers_for):
    f = mk_fund(client, admin)
    assert f["pct_of_target"] == 0 and f["by_status"]["interested"]["count"] == 0
    assert client.post("/api/funds", json={"name": f["name"], "target_raise": 1}, headers=admin).status_code == 409
    assert client.post("/api/funds", json={"name": f"X{u()}", "target_raise": 1, "status": "weird"}, headers=admin).status_code == 422
    assert client.post("/api/funds", json={"name": f"Y{u()}", "target_raise": 0}, headers=admin).status_code == 422
    assert client.post("/api/funds", json={"name": f"Z{u()}", "target_raise": 5}, headers=headers_for("broker")).status_code == 403


def test_commitment_lifecycle_and_rules(client, admin):
    f = mk_fund(client, admin, target_raise=1_000_000, minimum_investment=100_000)
    a, _ = mk_investor(client, admin)
    r = client.post("/api/commitments", json={"investor_id": a["id"], "fund_id": f["id"], "amount": 50_000}, headers=admin)
    assert r.status_code == 201 and r.json()["status"] == "interested"
    cid = r.json()["id"]
    assert client.post("/api/commitments", json={"investor_id": a["id"], "fund_id": f["id"], "amount": 50_000}, headers=admin).status_code == 409  # one per investor per fund
    assert client.post(f"/api/commitments/{cid}/status", json={"status": "soft_circled"}, headers=admin).status_code == 422  # below minimum
    assert client.post(f"/api/commitments/{cid}/status", json={"status": "soft_circled", "amount": 400_000}, headers=admin).status_code == 200
    ok = client.post(f"/api/commitments/{cid}/status", json={"status": "committed"}, headers=admin)
    assert ok.status_code == 200
    assert client.post(f"/api/commitments/{cid}/status", json={"status": "interested"}, headers=admin).status_code == 409  # no regression
    funded = client.post(f"/api/commitments/{cid}/status", json={"status": "funded"}, headers=admin)
    assert funded.status_code == 200
    rows = client.get(f"/api/funds/{f['id']}/commitments", headers=admin).json()["items"]
    assert rows[0]["interested_on"] and rows[0]["soft_circled_on"] and rows[0]["committed_on"] and rows[0]["funded_on"]
    fund = client.get(f"/api/funds/{f['id']}", headers=admin).json()
    assert fund["committed_or_funded"] == 400_000 and fund["pct_of_target"] == 40.0 and fund["by_status"]["funded"]["count"] == 1
    assert client.delete(f"/api/commitments/{cid}", headers=admin).status_code == 409


def test_commitments_cannot_exceed_fund_target(client, admin):
    f = mk_fund(client, admin, target_raise=500_000, minimum_investment=100_000)
    a, _ = mk_investor(client, admin)
    b, _ = mk_investor(client, admin)
    ca = client.post("/api/commitments", json={"investor_id": a["id"], "fund_id": f["id"], "amount": 400_000, "status": "committed"}, headers=admin)
    assert ca.status_code == 201 and ca.json()["status"] == "committed"
    cb = client.post("/api/commitments", json={"investor_id": b["id"], "fund_id": f["id"], "amount": 200_000}, headers=admin).json()
    over = client.post(f"/api/commitments/{cb['id']}/status", json={"status": "committed"}, headers=admin)
    assert over.status_code == 409 and "exceed the fund target" in over.text
    assert client.post(f"/api/commitments/{cb['id']}/status", json={"status": "soft_circled"}, headers=admin).status_code == 200  # interest may exceed the target
    assert client.patch(f"/api/funds/{f['id']}", json={"target_raise": 300_000}, headers=admin).status_code == 409


def test_unverified_investor_cannot_commit(client, admin):
    f = mk_fund(client, admin)
    inv, _ = mk_investor(client, admin, accreditation_status="unknown", accreditation_verified_on=None)
    c = client.post("/api/commitments", json={"investor_id": inv["id"], "fund_id": f["id"], "amount": 200_000}, headers=admin).json()
    r = client.post(f"/api/commitments/{c['id']}/status", json={"status": "committed"}, headers=admin)
    assert r.status_code == 409 and "accredited" in r.text
    client.patch(f"/api/investors/{inv['id']}", json={"accreditation_status": "accredited", "accreditation_verified_on": date.today().isoformat()}, headers=admin)
    assert client.post(f"/api/commitments/{c['id']}/status", json={"status": "committed"}, headers=admin).status_code == 200


def test_closed_fund_blocks_changes(client, admin):
    f = mk_fund(client, admin)
    inv, _ = mk_investor(client, admin)
    c = client.post("/api/commitments", json={"investor_id": inv["id"], "fund_id": f["id"], "amount": 200_000, "status": "committed"}, headers=admin).json()
    client.patch(f"/api/funds/{f['id']}", json={"status": "closed"}, headers=admin)
    assert client.post(f"/api/commitments/{c['id']}/status", json={"status": "funded"}, headers=admin).status_code == 409
    other, _ = mk_investor(client, admin)
    assert client.post("/api/commitments", json={"investor_id": other["id"], "fund_id": f["id"], "amount": 200_000}, headers=admin).status_code == 409


def test_fund_links_to_properties_and_deals(client, admin):
    from tests.test_deals import mk_deal
    f = mk_fund(client, admin)
    p, d = mk_property(client, admin), mk_deal(client, admin, pipeline="capital")
    assert client.post(f"/api/funds/{f['id']}/properties/{p['id']}", headers=admin).status_code == 201
    r = client.post(f"/api/funds/{f['id']}/deals/{d['id']}", headers=admin)
    client.post(f"/api/funds/{f['id']}/deals/{d['id']}", headers=admin)  # idempotent
    detail = r.json()
    assert [x["id"] for x in detail["properties"]] == [p["id"]] and [x["id"] for x in detail["deals"]] == [d["id"]]
    assert client.post(f"/api/funds/{f['id']}/properties/99999999", headers=admin).status_code == 422


# ---------------- matching ----------------
def test_matching_ranks_with_reasons_and_gates(client, admin):
    l = active_listing_for(client, admin, price=10_000_000, property_type="industrial", market="Inland Empire", city="Ontario")  # equity at 60% LTV = 4M
    best, _ = mk_investor(client, admin, exchange_1031=True, exchange_deadline=(date.today() + timedelta(days=60)).isoformat(), min_cap_rate_bps=500)
    ok, _ = mk_investor(client, admin)
    wrong_class, _ = mk_investor(client, admin, asset_classes=["retail"])
    wrong_market, _ = mk_investor(client, admin, markets=["San Diego"])
    too_small, _ = mk_investor(client, admin, min_check=50_000, max_check=500_000)
    expired_1031, _ = mk_investor(client, admin, exchange_1031=True, exchange_deadline=(date.today() - timedelta(days=3)).isoformat())
    res = client.get(f"/api/listings/{l['id']}/matches", headers=admin).json()
    assert res["suggestion_only"] is True
    ids = [m["investor_id"] for m in res["items"]]
    assert ids.index(best["id"]) < ids.index(ok["id"])
    for excluded in (wrong_class, wrong_market, too_small, expired_1031):
        assert excluded["id"] not in ids
    top = [m for m in res["items"] if m["investor_id"] == best["id"]][0]
    text = " | ".join(top["reasons"])
    assert "Asset class" in text and "Market: Inland Empire" in text and "within check size" in text and "1031 buyer: 60 days" in text and "Cap rate" in text


def test_matching_ltv_changes_equity_fit(client, admin):
    l = active_listing_for(client, admin, price=10_000_000, property_type="industrial", market="Inland Empire", city="Fontana")
    inv, _ = mk_investor(client, admin, min_check=8_000_000, max_check=12_000_000)  # all-cash style buyer
    base = [m["investor_id"] for m in client.get(f"/api/listings/{l['id']}/matches", headers=admin).json()["items"]]
    cash = [m["investor_id"] for m in client.get(f"/api/listings/{l['id']}/matches", params={"ltv_pct": 0}, headers=admin).json()["items"]]
    assert inv["id"] not in base and inv["id"] in cash


def test_matching_flags_do_not_contact_and_hides_accreditation(client, admin, headers_for):
    l = active_listing_for(client, admin, price=10_000_000, property_type="industrial", market="Inland Empire", city="Chino")
    c = mk_contact(client, admin, do_not_contact=True, do_not_contact_reason="No calls")
    inv = client.post("/api/investors", json={"contact_id": c["id"], "asset_classes": ["industrial"], "markets": ["Inland Empire"], "min_check": 1_000_000, "max_check": 6_000_000}, headers=admin).json()
    items = client.get(f"/api/listings/{l['id']}/matches", headers=admin).json()["items"]
    assert [m for m in items if m["investor_id"] == inv["id"]][0]["blocked_do_not_contact"] is True
    ro = client.get(f"/api/listings/{l['id']}/matches", headers=headers_for("read_only")).json()["items"]
    assert ro and all("accreditation_status" not in m for m in ro)


def test_reverse_matching_for_an_investor(client, admin):
    l = active_listing_for(client, admin, price=6_000_000, property_type="retail", market="Orange County", city="Irvine")
    inv, _ = mk_investor(client, admin, asset_classes=["retail"], markets=["Orange County"], min_check=1_000_000, max_check=3_000_000)
    res = client.get(f"/api/investors/{inv['id']}/matches", headers=admin).json()["items"]
    assert l["id"] in [m["listing_id"] for m in res] and res[0]["reasons"]


def test_investor_merge_moves_profile(client, admin):
    keep = mk_contact(client, admin, last=f"Inv{u()}")
    inv, gone = mk_investor(client, admin)
    client.post("/api/merge", json={"entity": "contact", "survivor_id": keep["id"], "absorbed_id": gone["id"]}, headers=admin)
    got = client.get(f"/api/investors/{inv['id']}", headers=admin).json()
    assert got["contact_id"] == keep["id"]
