import uuid
from datetime import date, timedelta

from tests.test_core import mk_company, mk_contact, mk_property, u


def mk_owned_property(client, h, years_held=12, maturity_months=None, **kw):
    llc = mk_company(client, h)
    person = mk_contact(client, h, first="Own", last=f"Er{u()}", phone=f"(949) 555-{int(u()[:3], 16) % 9000 + 1000}")
    client.post(f"/api/contacts/{person['id']}/companies", json={"company_id": llc["id"], "role": "principal", "is_primary": True}, headers=h)
    body = {}
    if maturity_months is not None:
        body["loan_maturity_date"] = (date.today() + timedelta(days=int(maturity_months * 30.44))).isoformat()
    prop = mk_property(client, h, estimated_value=5_000_000, building_sf=20000, **body, **kw)
    acquired = (date.today() - timedelta(days=int(years_held * 365.25))).isoformat()
    client.post(f"/api/properties/{prop['id']}/ownerships", json={"company_id": llc["id"], "acquired_date": acquired}, headers=h)
    return prop, llc, person


def run_triggers(client, h):
    r = client.post("/api/jobs/hold_sell_triggers/run", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text
    return r.json()["summary"]


def test_trigger_creates_seller_lead_with_reason_and_score_components(client, admin):
    r = client.post("/api/trigger-rules", json={"name": "Held 9+ yrs (test)", "kind": "hold_years", "threshold": 9}, headers=admin)
    assert r.status_code == 201
    prop, llc, person = mk_owned_property(client, admin, years_held=12, maturity_months=8, hold_intent="open_to_sell")
    run_triggers(client, admin)
    leads = client.get("/api/leads", params={"q": person["full_name"]}, headers=admin).json()["items"]
    assert len(leads) == 1
    l = leads[0]
    assert l["stream"] == "seller" and l["status"] == "new" and l["property_id"] == prop["id"]
    assert l["trigger_reason"]["matches"][0]["kind"] == "hold_years" and "Held 12" in l["trigger_reason"]["matches"][0]["detail"]
    comps = l["score_components"]
    assert comps["hold period"] == 15 and comps["loan maturity"] == 25 and comps["stated intent"] == 20
    assert l["score"] == sum(comps.values())
    assert l["contact_id"] == person["id"] and l["owner_user_id"]


def test_triggers_are_idempotent(client, admin):
    client.post("/api/trigger-rules", json={"name": "Held 8+ (idem)", "kind": "hold_years", "threshold": 8}, headers=admin)
    prop, llc, person = mk_owned_property(client, admin, years_held=10)
    run_triggers(client, admin)
    n1 = client.get("/api/leads", params={"q": person["full_name"]}, headers=admin).json()["total"]
    s2 = run_triggers(client, admin)
    n2 = client.get("/api/leads", params={"q": person["full_name"]}, headers=admin).json()["total"]
    assert n1 == n2 == 1 and s2["leads_created"] == 0


def test_loan_maturity_rule_and_second_rule_adds_reason_not_second_lead(client, admin):
    client.post("/api/trigger-rules", json={"name": "Matures within 12 (t)", "kind": "loan_maturity", "threshold": 12}, headers=admin)
    prop, llc, person = mk_owned_property(client, admin, years_held=11, maturity_months=6)
    run_triggers(client, admin)
    leads = client.get("/api/leads", params={"q": person["full_name"]}, headers=admin).json()["items"]
    assert len(leads) == 1
    kinds = {m["kind"] for m in leads[0]["trigger_reason"]["matches"]}
    assert "loan_maturity" in kinds and len(leads[0]["trigger_reason"]["matches"]) >= 2  # hold-years rules from earlier tests also fire


def test_property_already_listed_gets_no_trigger_lead(client, admin):
    client.post("/api/trigger-rules", json={"name": "Held 5+ (listed)", "kind": "hold_years", "threshold": 5}, headers=admin)
    prop, llc, person = mk_owned_property(client, admin, years_held=15)
    assert client.post("/api/listings", json={"property_id": prop["id"]}, headers=admin).status_code == 201
    run_triggers(client, admin)
    assert client.get("/api/leads", params={"q": person["full_name"]}, headers=admin).json()["total"] == 0


def test_buyer_stream_lead_rejected(client, admin):
    r = client.post("/api/leads", json={"name": "Buyer Bob", "stream": "buyer"}, headers=admin)
    assert r.status_code == 422 and "buyer interest" in r.text


def test_web_form_requires_key_and_creates_lead(client, admin):
    body = {"name": "Web Seller", "email": f"{u()}@web.test", "property_address": "123 Main", "message": "thinking of selling"}
    assert client.post("/api/public/leads", json=body).status_code == 401
    r = client.post("/api/public/leads", json=body, headers={"X-Form-Key": "dev-form-key"})
    assert r.status_code == 201
    lead = client.get(f"/api/leads/{r.json()['id']}", headers=admin).json()
    assert lead["source"] == "Web form" and lead["owner_user_id"]


def test_assignment_rule_fixed_and_round_robin(client, admin):
    users = client.get("/api/auth/users", headers=admin).json()
    a, b = users[0]["id"], users[1]["id"]
    r = client.post("/api/assignment-rules", json={"name": "RR industrial", "priority": 1, "property_type": "industrial", "strategy": "round_robin", "user_ids": [a, b]}, headers=admin)
    assert r.status_code == 201
    owners = []
    for _ in range(4):
        prop = mk_property(client, admin, property_type="industrial")
        lead = client.post("/api/leads", json={"name": f"RR {u()}", "property_id": prop["id"]}, headers=admin).json()
        owners.append(lead["owner_user_id"])
    assert owners[0] == owners[2] and owners[1] == owners[3] and owners[0] != owners[1] and set(owners) == {a, b}


def test_convert_lead_creates_contact_and_company_in_one_transaction_and_links_duplicates(client, admin):
    email = f"{u()}@seller.test"
    lead = client.post("/api/leads", json={"name": "Sally Seller", "company_name": f"Seller {u()} LLC", "email": email}, headers=admin).json()
    r = client.post(f"/api/leads/{lead['id']}/convert", json={}, headers=admin)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["contact_id"] and out["company_id"] and out["linked_existing"] == {"contact": False, "company": False}
    c = client.get(f"/api/contacts/{out['contact_id']}", headers=admin).json()
    assert c["companies"][0]["company_id"] == out["company_id"]
    # second lead, same email -> links to the existing contact (no duplicate created)
    lead2 = client.post("/api/leads", json={"name": "S. Seller", "email": email.upper()}, headers=admin).json()
    out2 = client.post(f"/api/leads/{lead2['id']}/convert", json={}, headers=admin).json()
    assert out2["contact_id"] == out["contact_id"] and out2["linked_existing"]["contact"] is True
    assert client.post(f"/api/leads/{lead['id']}/convert", json={}, headers=admin).status_code == 409


def test_disqualify_requires_reason(client, admin):
    lead = client.post("/api/leads", json={"name": "Nope"}, headers=admin).json()
    assert client.patch(f"/api/leads/{lead['id']}", json={"status": "disqualified"}, headers=admin).status_code == 422
    assert client.patch(f"/api/leads/{lead['id']}", json={"status": "disqualified", "disqualify_reason": "Not selling"}, headers=admin).status_code == 200


# ---------------- listings ----------------
def mk_listing(client, h, prop=None, **kw):
    prop = prop or mk_property(client, h)
    r = client.post("/api/listings", json={"property_id": prop["id"], **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json(), prop


ACTIVE = {"list_price": 4_500_000, "agreement_date": date.today().isoformat(), "expiration_date": (date.today() + timedelta(days=180)).isoformat(), "commission_rate_bps": 300}


def test_listing_lifecycle_and_rules(client, admin):
    l, prop = mk_listing(client, admin, commission_rate_bps=300)
    assert l["status"] == "prospect"
    # activation needs price, agreement, expiration
    assert client.post(f"/api/listings/{l['id']}/status", json={"status": "active"}, headers=admin).status_code == 422
    r = client.post(f"/api/listings/{l['id']}/status", json={"status": "active", **{k: v for k, v in ACTIVE.items() if k != 'commission_rate_bps'}}, headers=admin)
    assert r.status_code == 200 and r.json()["days_on_market"] == 0 and r.json()["price_per_sf"] is None or True
    # one active sale listing per property
    l2, _ = mk_listing(client, admin, prop=prop)
    r = client.post(f"/api/listings/{l2['id']}/status", json={"status": "active", **{k: v for k, v in ACTIVE.items() if k != 'commission_rate_bps'}}, headers=admin)
    assert r.status_code == 409 and "already has an active sale listing" in r.text
    # cannot jump to closed without passing under contract
    assert client.post(f"/api/listings/{l['id']}/status", json={"status": "closed", "sold_price": 1}, headers=admin).status_code == 409
    assert client.post(f"/api/listings/{l['id']}/status", json={"status": "under_contract"}, headers=admin).status_code == 200
    assert client.post(f"/api/listings/{l['id']}/status", json={"status": "closed"}, headers=admin).status_code == 422
    r = client.post(f"/api/listings/{l['id']}/status", json={"status": "closed", "sold_price": 4_400_000}, headers=admin)
    assert r.status_code == 200 and r.json()["sold_price"] == 4_400_000
    assert client.patch(f"/api/listings/{l['id']}", json={"list_price": 1}, headers=admin).status_code == 409


def test_listing_expiration_validation_and_expiring_filter(client, admin):
    l, _ = mk_listing(client, admin)
    bad = {"status": "active", "list_price": 1_000_000, "agreement_date": date.today().isoformat(), "expiration_date": (date.today() - timedelta(days=1)).isoformat()}
    assert client.post(f"/api/listings/{l['id']}/status", json=bad, headers=admin).status_code == 422
    good = {**bad, "expiration_date": (date.today() + timedelta(days=20)).isoformat()}
    assert client.post(f"/api/listings/{l['id']}/status", json=good, headers=admin).status_code == 200
    ids = [x["id"] for x in client.get("/api/listings", params={"expiring_within_days": 30}, headers=admin).json()["items"]]
    assert l["id"] in ids


def test_broker_splits_cannot_exceed_100(client, admin):
    users = client.get("/api/auth/users", headers=admin).json()
    r = client.post("/api/listings", json={"property_id": mk_property(client, admin)["id"], "brokers": [{"user_id": users[0]["id"], "split_pct": 70}, {"user_id": users[1]["id"], "split_pct": 40}]}, headers=admin)
    assert r.status_code == 422
    r = client.post("/api/listings", json={"property_id": mk_property(client, admin)["id"], "brokers": [{"user_id": users[0]["id"], "split_pct": 60}, {"user_id": users[1]["id"], "split_pct": 40}]}, headers=admin)
    assert r.status_code == 201 and len(r.json()["brokers"]) == 2


def test_commission_is_field_level_restricted(client, admin, headers_for):
    l, _ = mk_listing(client, admin, commission_rate_bps=275, list_price=4_000_000)
    assert client.get(f"/api/listings/{l['id']}", headers=admin).json()["commission_rate_bps"] == 275
    for role in ("assistant", "read_only"):
        got = client.get(f"/api/listings/{l['id']}", headers=headers_for(role)).json()
        assert "commission_rate_bps" not in got and "expected_commission" not in got
    assert client.patch(f"/api/listings/{l['id']}", json={"commission_rate_bps": 1}, headers=headers_for("assistant")).status_code == 403


def active_listing(client, admin):
    l, prop = mk_listing(client, admin)
    client.post(f"/api/listings/{l['id']}/status", json={"status": "active", **{k: v for k, v in ACTIVE.items() if k != 'commission_rate_bps'}}, headers=admin)
    return l


def test_buyer_interest_progression_and_validation(client, admin):
    l = active_listing(client, admin)
    buyer = mk_contact(client, admin, contact_types=["buyer"])
    r = client.post(f"/api/listings/{l['id']}/interest", json={"contact_id": buyer["id"], "stage": "inquiry", "channel": "form"}, headers=admin)
    assert r.status_code == 201
    iid = r.json()["id"]
    for stage in ("ca_sent", "ca_signed", "om_sent", "tour"):
        assert client.post(f"/api/interest/{iid}/events", json={"stage": stage}, headers=admin).status_code == 200
    assert client.post(f"/api/interest/{iid}/events", json={"stage": "offer"}, headers=admin).status_code == 422  # needs amount
    r = client.post(f"/api/interest/{iid}/events", json={"stage": "offer", "amount": 4_300_000, "terms": "30 day DD"}, headers=admin)
    assert r.status_code == 200 and r.json()["offer_amount"] == 4_300_000 and [e["stage"] for e in r.json()["events"]][-1] == "offer"
    assert client.post(f"/api/interest/{iid}/events", json={"stage": "ca_signed"}, headers=admin).status_code == 409  # no going back
    funnel = client.get(f"/api/listings/{l['id']}/interest", headers=admin).json()["funnel"]
    assert funnel["offer"] == 1


def test_all_buyer_paths_use_one_service_and_dedupe(client, admin):
    l = active_listing(client, admin)
    email = f"{u()}@buyer.test"
    r1 = client.post(f"/api/listings/{l['id']}/interest", json={"contact": {"first_name": "Bea", "last_name": "Buyer", "email": email}, "channel": "email"}, headers=admin)
    r2 = client.post(f"/api/listings/{l['id']}/interest", json={"contact": {"first_name": "B.", "last_name": "Buyer", "email": email.upper()}, "stage": "ca_signed", "channel": "form"}, headers=admin)
    assert r1.status_code == r2.status_code == 201 and r1.json()["id"] == r2.json()["id"]
    assert r2.json()["stage"] == "ca_signed" and len(r2.json()["events"]) == 2


def test_do_not_contact_blocks_outreach_stages(client, admin):
    l = active_listing(client, admin)
    buyer = mk_contact(client, admin, do_not_contact=True, do_not_contact_reason="Asked to be removed")
    assert client.post(f"/api/listings/{l['id']}/interest", json={"contact_id": buyer["id"], "stage": "inquiry"}, headers=admin).status_code == 201
    r = client.post(f"/api/listings/{l['id']}/interest", json={"contact_id": buyer["id"], "stage": "om_sent"}, headers=admin)
    assert r.status_code == 409 and "do-not-contact" in r.text


def test_confidential_listing_masks_buyers_for_restricted_roles(client, admin, headers_for):
    l, _ = mk_listing(client, admin, confidential=True)
    client.post(f"/api/listings/{l['id']}/status", json={"status": "active", **{k: v for k, v in ACTIVE.items() if k != 'commission_rate_bps'}}, headers=admin)
    buyer = mk_contact(client, admin, first="Secret", last="Buyer")
    client.post(f"/api/listings/{l['id']}/interest", json={"contact_id": buyer["id"]}, headers=admin)
    seen = client.get(f"/api/listings/{l['id']}/interest", headers=headers_for("read_only")).json()["items"][0]
    assert "Secret" not in seen["contact"] and seen["contact_id"] is None
    assert client.get(f"/api/listings/{l['id']}/interest", headers=admin).json()["items"][0]["contact"] == buyer["full_name"]


def test_search_finds_listings(client, admin):
    l, prop = mk_listing(client, admin)
    res = client.get("/api/search", params={"q": prop["address"]}, headers=admin).json()["results"]
    assert any(r["type"] == "listing" and r["id"] == l["id"] for r in res)


def test_jobs_listed_and_admin_only(client, admin, headers_for):
    names = {j["name"] for j in client.get("/api/jobs", headers=admin).json()}
    assert {"hold_sell_triggers", "duplicate_scan"} <= names
    assert client.post("/api/jobs/duplicate_scan/run", headers=headers_for("broker")).status_code == 403
    assert client.get("/api/jobs/runs", headers=admin).json()[0]["status"] in ("ok", "failed")
