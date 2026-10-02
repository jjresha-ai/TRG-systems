from datetime import date, timedelta

from tests.test_core import mk_company, mk_contact, mk_property, u
from tests.test_prospecting_listings import ACTIVE, active_listing, mk_listing, mk_owned_property


def mk_deal(client, h, **kw):
    r = client.post("/api/deals", json={"name": f"Deal {u()}", **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def move(client, h, deal, stage, expect=200, **kw):
    r = client.post(f"/api/deals/{deal['id']}/stage", json={"stage": stage, **kw}, headers=h)
    assert r.status_code == expect, r.text
    return r.json()


def test_default_pipelines_and_stages(client, admin):
    pipes = {p["key"]: p for p in client.get("/api/pipelines", headers=admin).json()}
    assert set(pipes) == {"seller", "buyer", "capital", "leasing"}
    keys = [s["key"] for s in pipes["seller"]["stages"]]
    assert keys == ["prospect", "pitch", "listing_agreement", "marketing", "offers", "under_contract", "due_diligence", "closed", "lost"]
    assert pipes["seller"]["stages"][0]["probability"] == 10


def test_create_deal_records_initial_history(client, admin):
    d = mk_deal(client, admin, price=3_000_000, commission_rate_bps=300)
    assert d["stage"]["key"] == "prospect" and d["status"] == "open"
    assert d["gross_commission"] == 90_000 and d["probability"] == 10 and d["weighted_commission"] == 9_000
    assert len(d["history"]) == 1 and d["history"][0]["note"] == "Created"


def test_stage_history_is_appended_and_time_in_stage_derived(client, admin):
    d = mk_deal(client, admin, price=2_000_000)
    d = move(client, admin, d, "pitch")
    d = move(client, admin, d, "listing_agreement")
    assert [h["stage"] for h in d["history"]] == ["Prospect", "Pitch", "Listing agreement"]
    assert all("days" in h for h in d["history"])


def test_history_is_append_only_in_the_database(client, admin):
    import pytest
    from app.db import SessionLocal
    from app.models.deals import DealStageHistory
    d = mk_deal(client, admin)
    with SessionLocal() as db:
        h = db.query(DealStageHistory).filter_by(deal_id=d["id"]).first()
        h.note = "tampered"
        with pytest.raises(ValueError):
            db.flush()
        db.rollback()
        h = db.query(DealStageHistory).filter_by(deal_id=d["id"]).first()
        db.delete(h)
        with pytest.raises(ValueError):
            db.flush()
        db.rollback()


def test_lost_requires_reason_and_can_reopen(client, admin):
    d = mk_deal(client, admin)
    move(client, admin, d, "lost", expect=422)
    lost = move(client, admin, d, "lost", lost_reason="Owner decided to hold")
    assert lost["status"] == "lost" and lost["lost_reason"] == "Owner decided to hold"
    reopened = move(client, admin, d, "pitch")
    assert reopened["status"] == "open" and reopened["lost_reason"] is None


def test_closing_requires_price_and_locks_deal(client, admin):
    d = mk_deal(client, admin)
    move(client, admin, d, "closed", expect=422)
    closed = move(client, admin, d, "closed", price=4_000_000)
    assert closed["status"] == "won" and closed["actual_close_date"] == date.today().isoformat()
    move(client, admin, d, "pitch", expect=409)
    assert client.patch(f"/api/deals/{d['id']}", json={"price": 5}, headers=admin).status_code == 409


def test_under_contract_and_due_diligence_rules(client, admin):
    d = mk_deal(client, admin)
    move(client, admin, d, "under_contract", expect=422)  # price
    move(client, admin, d, "under_contract", price=1_000_000)
    move(client, admin, d, "due_diligence", expect=422)  # dd date
    ok = move(client, admin, d, "due_diligence", dd_expiry_date=(date.today() + timedelta(days=30)).isoformat())
    assert ok["stage"]["key"] == "due_diligence" and ok["dd_expiry_date"]


def test_stage_must_belong_to_pipeline(client, admin):
    d = mk_deal(client, admin, pipeline="capital")
    move(client, admin, d, "pitch", expect=422)
    assert move(client, admin, d, "materials")["stage"]["key"] == "materials"


def test_commission_splits_validation_and_amounts(client, admin):
    users = client.get("/api/auth/users", headers=admin).json()
    d = mk_deal(client, admin, price=5_000_000, commission_rate_bps=300)  # gross 150,000
    bad = client.put(f"/api/deals/{d['id']}/splits", json={"splits": [{"recipient_user_id": users[0]["id"], "pct": 70}, {"external_name": "CBRE", "pct": 40}]}, headers=admin)
    assert bad.status_code == 422 and "exceed 100" in bad.text
    ok = client.put(f"/api/deals/{d['id']}/splits", json={"splits": [{"recipient_user_id": users[0]["id"], "pct": 60}, {"external_name": "CBRE co-broker", "pct": 25}, {"external_name": "Referral", "split_type": "amount", "amount": 7_500}]}, headers=admin)
    assert ok.status_code == 200
    splits = ok.json()["splits"]
    assert [s["amount"] for s in splits] == [90_000, 37_500, 7_500]
    over = client.put(f"/api/deals/{d['id']}/splits", json={"splits": [{"recipient_user_id": users[0]["id"], "pct": 90}, {"external_name": "X", "split_type": "amount", "amount": 50_000}]}, headers=admin)
    assert over.status_code == 422 and "gross commission" in over.text


def test_commission_hidden_and_protected_for_restricted_roles(client, admin, headers_for):
    d = mk_deal(client, admin, price=1_000_000, commission_rate_bps=300)
    for role in ("assistant", "read_only"):
        got = client.get(f"/api/deals/{d['id']}", headers=headers_for(role)).json()
        assert "gross_commission" not in got and "splits" not in got and "weighted_commission" not in got
        fc = client.get("/api/deals/forecast", headers=headers_for(role)).json()
        assert fc["commission_visible"] is False and "weighted_commission" not in fc["totals"]
    assert client.patch(f"/api/deals/{d['id']}", json={"commission_rate_bps": 1}, headers=headers_for("assistant")).status_code == 403
    assert client.put(f"/api/deals/{d['id']}/splits", json={"splits": []}, headers=headers_for("assistant")).status_code == 403
    assert client.get("/api/deals/forecast", headers=admin).json()["totals"]["weighted_commission"] > 0


def test_forecast_weights_by_stage_probability_and_month(client, admin):
    month = (date.today() + timedelta(days=75)).replace(day=15)
    d = mk_deal(client, admin, pipeline="leasing", price=1_000_000, gross_commission=40_000, expected_close_date=month.isoformat())
    move(client, admin, d, "proposal")  # 45%
    fc = client.get("/api/deals/forecast", params={"pipeline": "leasing"}, headers=admin).json()
    m = [x for x in fc["by_month"] if x["month"] == month.strftime("%Y-%m")][0]
    assert m["weighted_commission"] >= 18_000 and m["commission"] >= 40_000
    assert any(s["stage"] == "Proposal / LOI" for s in fc["by_stage"])
    # per-deal probability override
    client.patch(f"/api/deals/{d['id']}", json={"probability": 100}, headers=admin)
    assert client.get(f"/api/deals/{d['id']}", headers=admin).json()["weighted_commission"] == 40_000


def test_rotting_and_stalled(client, admin):
    from app.db import SessionLocal
    from app.models.deals import Deal
    from datetime import datetime
    d = mk_deal(client, admin, price=1_000_000)
    with SessionLocal() as db:
        x = db.get(Deal, d["id"])
        x.stage_entered_at = datetime.utcnow() - timedelta(days=60)  # prospect rots at 30
        db.commit()
    got = client.get(f"/api/deals/{d['id']}", headers=admin).json()
    assert got["rotting"] is True and got["days_in_stage"] >= 60
    assert d["id"] in [r["id"] for r in client.get("/api/deals/stalled", headers=admin).json()["items"]]
    assert d["id"] in [r["id"] for r in client.get("/api/deals", params={"rotting": True}, headers=admin).json()["items"]]


def test_stage_config_is_admin_only_and_terminal_stages_fixed(client, admin, headers_for):
    seller = [p for p in client.get("/api/pipelines", headers=admin).json() if p["key"] == "seller"][0]
    s = seller["stages"][1]
    assert client.patch(f"/api/stages/{s['id']}", json={"rotting_days": 25}, headers=headers_for("manager")).status_code == 403
    assert client.patch(f"/api/stages/{s['id']}", json={"rotting_days": 25}, headers=admin).json()["rotting_days"] == 25
    assert client.patch(f"/api/stages/{seller['stages'][-2]['id']}", json={"probability": 50}, headers=admin).status_code == 409


def test_parties(client, admin):
    seller, buyer = mk_contact(client, admin), mk_company(client, admin)
    d = mk_deal(client, admin, parties=[{"role": "seller", "contact_id": seller["id"]}])
    r = client.post(f"/api/deals/{d['id']}/parties", json={"role": "buyer", "company_id": buyer["id"]}, headers=admin)
    assert r.status_code == 201 and {p["role"] for p in r.json()["parties"]} == {"seller", "buyer"}
    assert client.post(f"/api/deals/{d['id']}/parties", json={"role": "wizard", "company_id": buyer["id"]}, headers=admin).status_code == 422
    assert client.post(f"/api/deals/{d['id']}/parties", json={"role": "lender"}, headers=admin).status_code == 422


def test_listing_under_contract_creates_deal_inheriting_parties_and_dates(client, admin):
    prop, llc, person = mk_owned_property(client, admin, years_held=3)
    l = client.post("/api/listings", json={"property_id": prop["id"], "seller_company_id": llc["id"], "seller_contact_id": person["id"], "commission_rate_bps": 300}, headers=admin).json()
    client.post(f"/api/listings/{l['id']}/status", json={"status": "active", "list_price": 5_000_000, "agreement_date": date.today().isoformat(), "expiration_date": (date.today() + timedelta(days=200)).isoformat()}, headers=admin)
    buyer = mk_contact(client, admin, contact_types=["buyer"])
    i = client.post(f"/api/listings/{l['id']}/interest", json={"contact_id": buyer["id"]}, headers=admin).json()
    client.post(f"/api/interest/{i['id']}/events", json={"stage": "offer", "amount": 4_800_000}, headers=admin)
    r = client.post(f"/api/listings/{l['id']}/status", json={"status": "under_contract"}, headers=admin)
    assert r.status_code == 200 and r.json()["deal_id"]
    d = client.get(f"/api/deals/{r.json()['deal_id']}", headers=admin).json()
    assert d["stage"]["key"] == "under_contract" and d["price"] == 4_800_000 and d["listing_id"] == l["id"]
    assert d["listing_expiration_date"] == (date.today() + timedelta(days=200)).isoformat()
    roles = {(p["role"], p["contact_id"] or p["company_id"]) for p in d["parties"]}
    assert ("seller", person["id"]) in roles and ("buyer", buyer["id"]) in roles
    assert d["gross_commission"] == 144_000


def test_closing_deal_closes_listing_and_vice_versa(client, admin):
    prop, llc, person = mk_owned_property(client, admin, years_held=3)
    l = client.post("/api/listings", json={"property_id": prop["id"], "commission_rate_bps": 250}, headers=admin).json()
    client.post(f"/api/listings/{l['id']}/status", json={"status": "active", "list_price": 6_000_000, "agreement_date": date.today().isoformat(), "expiration_date": (date.today() + timedelta(days=100)).isoformat()}, headers=admin)
    did = client.post(f"/api/listings/{l['id']}/status", json={"status": "under_contract"}, headers=admin).json()["deal_id"]
    d = client.post(f"/api/deals/{did}/stage", json={"stage": "closed", "price": 5_800_000}, headers=admin).json()
    assert d["status"] == "won"
    got = client.get(f"/api/listings/{l['id']}", headers=admin).json()
    assert got["status"] == "closed" and got["sold_price"] == 5_800_000
    # other direction + falling out of contract
    prop2, *_ = mk_owned_property(client, admin, years_held=3)
    l2 = client.post("/api/listings", json={"property_id": prop2["id"], "commission_rate_bps": 250}, headers=admin).json()
    client.post(f"/api/listings/{l2['id']}/status", json={"status": "active", "list_price": 3_000_000, "agreement_date": date.today().isoformat(), "expiration_date": (date.today() + timedelta(days=100)).isoformat()}, headers=admin)
    did2 = client.post(f"/api/listings/{l2['id']}/status", json={"status": "under_contract"}, headers=admin).json()["deal_id"]
    client.post(f"/api/listings/{l2['id']}/status", json={"status": "active"}, headers=admin)
    d2 = client.get(f"/api/deals/{did2}", headers=admin).json()
    assert d2["status"] == "lost" and d2["lost_reason"] == "Contract terminated"


def test_lead_conversion_can_create_a_deal(client, admin):
    prop = mk_property(client, admin, estimated_value=7_000_000)
    lead = client.post("/api/leads", json={"name": "Dina Deal", "email": f"{u()}@deal.test", "company_name": f"Deal Co {u()} LLC", "property_id": prop["id"]}, headers=admin).json()
    r = client.post(f"/api/leads/{lead['id']}/convert", json={"create_deal": True}, headers=admin)
    assert r.status_code == 200 and r.json()["deal_id"]
    d = client.get(f"/api/deals/{r.json()['deal_id']}", headers=admin).json()
    assert d["property_id"] == prop["id"] and d["pipeline"]["key"] == "seller" and d["parties"][0]["role"] == "seller" and d["source"] == "lead conversion"
    assert client.get(f"/api/leads/{lead['id']}", headers=admin).json()["deal_id"] == d["id"]


def test_board_endpoint(client, admin):
    mk_deal(client, admin, price=1_500_000, commission_rate_bps=300)
    b = client.get("/api/deals/board", params={"pipeline": "seller"}, headers=admin).json()
    assert [c["stage"]["key"] for c in b["columns"]][0] == "prospect" and "lost" not in [c["stage"]["key"] for c in b["columns"]]
    assert b["columns"][0]["count"] >= 1 and b["columns"][0]["weighted_commission"] > 0
