from datetime import date, timedelta

from tests.test_core import mk_company, mk_contact, mk_property, u
from tests.test_deals import mk_deal
from tests.test_investors import active_listing_for, mk_fund, mk_investor
from tests.test_prospecting_listings import mk_listing


def users(client, h):
    return {x["name"]: x["id"] for x in client.get("/api/auth/users", headers=h).json()}


def close_deal(client, h, price, bps, on, owner=None, splits=None, **kw):
    prop = mk_property(client, h, property_type=kw.pop("property_type", "retail"))
    d = mk_deal(client, h, price=price, commission_rate_bps=bps, property_id=prop["id"], owner_user_id=owner, **kw)
    r = client.post(f"/api/deals/{d['id']}/stage", json={"stage": "closed", "price": price, "actual_close_date": on}, headers=h)
    assert r.status_code == 200, r.text
    if splits:
        assert client.put(f"/api/deals/{d['id']}/splits", json={"splits": splits}, headers=h).status_code == 200
    return d


P = {"start": "2019-03-01", "end": "2019-03-31"}


def test_production_totals_gci_allocation_and_grouping(client, admin):
    uid = users(client, admin)
    a, b = uid["Admin Tester"], uid["Manager Tester"]
    close_deal(client, admin, 10_000_000, 300, "2019-03-10", owner=a)  # GCI 300,000, no splits -> all to owner a
    close_deal(client, admin, 5_000_000, 200, "2019-03-20", owner=a, splits=[{"recipient_user_id": a, "pct": 60}, {"recipient_user_id": b, "pct": 40}], property_type="industrial")  # GCI 100,000: a 60k b 40k
    r = client.get("/api/reports/production", params={**P, "group_by": "broker"}, headers=admin).json()
    assert r["totals"] == {"listings_taken": 0, "closed_deals": 2, "closed_volume": 15_000_000, "gci": 400_000}
    by = {x["group"]: x for x in r["rows"]}
    assert by["Admin Tester"]["gci"] == 360_000 and by["Manager Tester"]["gci"] == 40_000
    assert by["Admin Tester"]["closed_volume"] + by["Manager Tester"]["closed_volume"] == 15_000_000
    m = client.get("/api/reports/production", params={**P, "group_by": "month"}, headers=admin).json()
    assert [x["group"] for x in m["rows"]] == ["2019-03"] and m["rows"][0]["closed_deals"] == 2
    t = client.get("/api/reports/production", params={**P, "group_by": "property_type"}, headers=admin).json()
    assert {x["group"]: x["closed_volume"] for x in t["rows"]} == {"retail": 10_000_000, "industrial": 5_000_000}
    only = client.get("/api/reports/production", params={**P, "property_type": "industrial"}, headers=admin).json()
    assert only["totals"]["closed_volume"] == 5_000_000
    assert client.get("/api/reports/production", params={**P, "group_by": "bogus"}, headers=admin).status_code == 422
    assert client.get("/api/reports/production", params={"start": "2019-04-01", "end": "2019-03-01"}, headers=admin).status_code == 422
    assert client.get("/api/reports/production", params={"period": "forever"}, headers=admin).status_code == 422


def test_listings_taken_counted_by_agreement_date(client, admin):
    l, prop = mk_listing(client, admin, agreement_date="2018-06-05", expiration_date="2019-06-05")
    r = client.get("/api/reports/production", params={"start": "2018-06-01", "end": "2018-06-30"}, headers=admin).json()
    assert r["totals"]["listings_taken"] >= 1


def test_goal_progress_in_production_and_goals_endpoint(client, admin, headers_for):
    g = client.post("/api/goals", json={"metric": "closed_volume", "period_type": "month", "period_start": "2019-03-01", "target": 30_000_000}, headers=admin)
    assert g.status_code == 201
    assert client.post("/api/goals", json={"metric": "closed_volume", "period_type": "month", "period_start": "2019-03-01", "target": 5}, headers=admin).status_code == 409
    assert client.post("/api/goals", json={"metric": "closed_volume", "period_type": "month", "period_start": "2019-03-15", "target": 5}, headers=admin).status_code == 422
    assert client.post("/api/goals", json={"metric": "nonsense", "period_type": "month", "period_start": "2019-03-01", "target": 5}, headers=admin).status_code == 422
    assert client.post("/api/goals", json={"metric": "gci", "period_type": "month", "period_start": "2019-03-01", "target": 5}, headers=headers_for("broker")).status_code == 403
    r = client.get("/api/reports/production", params=P, headers=admin).json()
    goal = [x for x in r["goals"] if x["metric"] == "closed_volume"][0]
    assert goal["target"] == 30_000_000 and goal["actual"] == r["totals"]["closed_volume"] and goal["pct"] == round(r["totals"]["closed_volume"] / 30_000_000 * 100, 1)
    ys = client.get("/api/goals", params={"year": 2019}, headers=admin).json()["items"]
    assert any(x["metric"] == "closed_volume" and x["actual"] == r["totals"]["closed_volume"] for x in ys)
    assert client.patch(f"/api/goals/{g.json()['id']}", json={"target": 40_000_000}, headers=admin).json()["target"] == 40_000_000


def test_commission_hidden_in_reports_for_restricted_roles(client, admin, headers_for):
    for role in ("assistant", "read_only"):
        h = headers_for(role)
        r = client.get("/api/reports/production", params=P, headers=h).json()
        assert "gci" not in r["totals"] and "gci" not in r["columns"] and all("gci" not in x for x in r["rows"]) and r["commission_visible"] is False
        assert all(g["metric"] != "gci" for g in r["goals"])
        p = client.get("/api/reports/pipeline", headers=h).json()
        assert "weighted_commission" not in p["totals"] and "weighted_commission" not in p["columns"]
        d = client.get("/api/dashboard", headers=h).json()
        assert "ytd_gci" not in d["kpis"] and "weighted_commission" not in d["kpis"]["open_pipeline"]
        assert all(x["metric"] != "gci" for x in client.get("/api/goals", headers=h).json()["items"])


def test_csv_export_permission_and_audit(client, admin, headers_for):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models.core_sys import AuditEvent
    r = client.get("/api/reports/production", params={**P, "format": "csv"}, headers=admin)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == "group,listings_taken,closed_deals,closed_volume,gci" and len(lines) >= 2
    assert client.get("/api/reports/production", params={**P, "format": "csv"}, headers=headers_for("assistant")).status_code == 403
    broker_csv = client.get("/api/reports/production", params={**P, "format": "csv"}, headers=headers_for("broker"))
    assert broker_csv.status_code == 200 and broker_csv.text.splitlines()[0].endswith("gci")
    with SessionLocal() as db:
        n = len(db.scalars(select(AuditEvent).where(AuditEvent.action == "export", AuditEvent.entity_type == "reports")).all())
    assert n >= 2
    assert client.get("/api/reports/production", params={**P, "format": "xml"}, headers=admin).status_code == 422


def test_pipeline_report_weights_and_grouping(client, admin):
    d = mk_deal(client, admin, pipeline="leasing", price=2_000_000, gross_commission=80_000, expected_close_date=(date.today() + timedelta(days=40)).isoformat())
    client.post(f"/api/deals/{d['id']}/stage", json={"stage": "proposal"}, headers=admin)  # 45%
    r = client.get("/api/reports/pipeline", params={"pipeline": "leasing", "group_by": "stage"}, headers=admin).json()
    row = [x for x in r["rows"] if x["group"] == "Proposal / LOI"][0]
    assert row["deals"] >= 1 and row["weighted_commission"] >= 36_000
    assert [x["group"] for x in r["rows"]] == sorted([x["group"] for x in r["rows"]], key=lambda g: ["Inquiry", "Tour", "Proposal / LOI", "Lease negotiation"].index(g))
    for gb in ("owner", "property_type", "market", "close_month"):
        assert client.get("/api/reports/pipeline", params={"group_by": gb}, headers=admin).status_code == 200
    assert client.get("/api/reports/pipeline", params={"group_by": "color"}, headers=admin).status_code == 422
    assert r["totals"]["weighted_commission"] == sum(x["weighted_commission"] for x in r["rows"])


def test_listing_report_status_counts_dom_and_expiring(client, admin):
    from tests.test_prospecting_listings import ACTIVE
    l, _ = mk_listing(client, admin)
    client.post(f"/api/listings/{l['id']}/status", json={"status": "active", "list_price": 2_000_000, "agreement_date": date.today().isoformat(), "expiration_date": (date.today() + timedelta(days=10)).isoformat()}, headers=admin)
    r = client.get("/api/reports/listings", params={"expiring_within_days": 30}, headers=admin).json()
    assert l["id"] in [x["listing_id"] for x in r["expiring"]] and any(x["status"] == "active" for x in r["rows"])
    assert all(x["days_left"] <= 30 for x in r["expiring"])


def test_buyer_interest_report_counts_stages_reached(client, admin):
    l = active_listing_for(client, admin)
    b1, b2 = mk_contact(client, admin), mk_contact(client, admin)
    i1 = client.post(f"/api/listings/{l['id']}/interest", json={"contact_id": b1["id"]}, headers=admin).json()
    i2 = client.post(f"/api/listings/{l['id']}/interest", json={"contact_id": b2["id"]}, headers=admin).json()
    for st in ("ca_sent", "ca_signed", "om_sent", "tour"):
        client.post(f"/api/interest/{i1['id']}/events", json={"stage": st}, headers=admin)
    client.post(f"/api/interest/{i1['id']}/events", json={"stage": "offer", "amount": 9_500_000}, headers=admin)
    client.post(f"/api/interest/{i2['id']}/events", json={"stage": "ca_sent"}, headers=admin)
    r = client.get("/api/reports/buyer-interest", headers=admin).json()
    row = [x for x in r["rows"] if x["listing_id"] == l["id"]][0]
    assert (row["inquiries"], row["ca_sent"], row["ca_signed"], row["om_sent"], row["tours"], row["offers"], row["best_offer"]) == (2, 2, 1, 1, 1, 1, 9_500_000)


def test_prospecting_report_source_conversion_and_activity_counts(client, admin):
    src = client.post("/api/lead-sources", json={"name": f"Src {u()}"}, headers=admin).json()
    ids = [client.post("/api/leads", json={"name": f"L{i} {u()}", "source_id": src["id"]}, headers=admin).json()["id"] for i in range(4)]
    client.post(f"/api/leads/{ids[0]}/convert", json={}, headers=admin)
    c = mk_contact(client, admin)
    a = client.post("/api/activities", json={"type": "call", "subject": "x", "status": "completed", "outcome": "spoke", "associations": [{"record_type": "contact", "record_id": c["id"]}]}, headers=admin)
    assert a.status_code == 201
    r = client.get("/api/reports/prospecting", params={"period": "month"}, headers=admin).json()
    row = [x for x in r["rows"] if x["source"] == src["name"]][0]
    assert row["leads"] == 4 and row["converted"] == 1 and row["conversion_rate"] == 25.0
    assert any(x["user"] == "Admin Tester" and x["calls"] >= 1 for x in r["activity_by_user"])


def test_owner_recency_lists_untouched_then_drops_after_contact(client, admin):
    c = mk_contact(client, admin, contact_types=["owner"], last=f"Recency{u()}")
    r = client.get("/api/reports/owner-recency", params={"days": 90, "limit": 1000} if False else {"days": 90}, headers=admin).json()
    assert r["threshold_days"] == 90 and r["total"] >= 1
    ids = [x["id"] for x in client.get("/api/reports/owner-recency", params={"days": 90}, headers=admin).json()["rows"]]
    assert c["id"] in ids or r["total"] > len(ids)  # list is capped; the total is exact
    client.post("/api/activities", json={"type": "meeting", "subject": "Lunch", "status": "completed", "associations": [{"record_type": "contact", "record_id": c["id"]}]}, headers=admin)
    after = client.get("/api/reports/owner-recency", params={"days": 90}, headers=admin).json()
    assert after["total"] == r["total"] - 1
    assert client.get("/api/reports/owner-recency", params={"entity": "wizard"}, headers=admin).status_code == 422


def test_time_in_stage_and_stalled(client, admin):
    from datetime import datetime
    from app.db import SessionLocal
    from app.models.deals import Deal
    d = mk_deal(client, admin, price=1_000_000)
    client.post(f"/api/deals/{d['id']}/stage", json={"stage": "pitch"}, headers=admin)
    with SessionLocal() as db:
        x = db.get(Deal, d["id"])
        x.stage_entered_at = datetime.utcnow() - timedelta(days=45)  # pitch rots at 21 (or the admin-edited value)
        db.commit()
    r = client.get("/api/reports/time-in-stage", params={"pipeline": "seller"}, headers=admin).json()
    assert [x["stage"] for x in r["rows"]][:3] == ["Prospect", "Pitch", "Listing agreement"]
    assert d["id"] in [x["deal_id"] for x in r["stalled"]]
    assert any(x["avg_days"] is not None for x in r["rows"])


def test_investor_capital_report_matches_fund_totals(client, admin):
    f = mk_fund(client, admin, target_raise=2_000_000)
    inv, _ = mk_investor(client, admin)
    client.post("/api/commitments", json={"investor_id": inv["id"], "fund_id": f["id"], "amount": 500_000, "status": "committed"}, headers=admin)
    r = client.get("/api/reports/investor-capital", headers=admin).json()
    row = [x for x in r["rows"] if x["fund"] == f["name"]][0]
    assert row["committed"] == 500_000 and row["committed_or_funded"] == 500_000 and row["pct_of_target"] == 25.0
    assert r["totals"]["committed_or_funded"] == sum(x["committed_or_funded"] for x in r["rows"])


def test_snapshot_job_is_idempotent_and_trend_compares_forecast_with_outcome(client, admin):
    mk_deal(client, admin, price=3_000_000, commission_rate_bps=300)
    first = client.post("/api/reports/snapshot", headers=admin).json()
    second = client.post("/api/reports/snapshot", headers=admin).json()
    assert second["snapshots_created"] == 0 and first["date"] == date.today().isoformat()
    t = client.get("/api/reports/pipeline-trend", params={"weeks": 4}, headers=admin).json()
    assert t["series"][-1]["date"] == date.today().isoformat() and t["series"][-1]["weighted_commission"] > 0
    assert "forecast_vs_outcome" in t
    run = client.post("/api/jobs/pipeline_snapshot/run", headers=admin).json()
    assert run["status"] == "ok"


def test_dashboard_kpis(client, admin):
    d = client.get("/api/dashboard", headers=admin).json()
    k = d["kpis"]
    for key in ("ytd_closed_volume", "ytd_closed_deals", "active_listings", "under_contract", "open_pipeline", "overdue_tasks", "new_leads", "hot_leads", "stalled_deals", "owners_untouched_90", "ytd_gci"):
        assert key in k
    assert k["open_pipeline"]["weighted_commission"] >= 0 and isinstance(d["production_by_month"], list) and isinstance(d["top_leads"], list)


def test_ytd_report_only_matches_the_year_goal_not_quarter_goals(client, admin):
    r = client.get("/api/reports/production", params={"period": "ytd"}, headers=admin).json()
    assert all(g["period_type"] == "year" for g in r["goals"])
    q = client.get("/api/reports/production", params={"period": "quarter"}, headers=admin).json()
    assert all(g["period_type"] == "quarter" for g in q["goals"])
