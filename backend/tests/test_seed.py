"""The demo seed is real data in a real database: check volume and referential integrity (ADR 0024)."""
import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

BACKEND = os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(scope="module")
def seeded():
    path = os.path.join(tempfile.mkdtemp(prefix="trg-seed-"), "seed.db")
    env = {**os.environ, "TRG_DATABASE_URL": f"sqlite:///{path}"}
    r = subprocess.run([sys.executable, "-m", "app.seed"], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    yield con
    con.close()


def n(con, sql):
    return con.execute(sql).fetchone()[0]


def test_core_volumes(seeded):
    assert n(seeded, "select count(*) from contacts where deleted_at is null") >= 200
    assert n(seeded, "select count(*) from companies") >= 150
    assert n(seeded, "select count(*) from properties") >= 120
    assert n(seeded, "select count(*) from property_ownerships") >= 150


def test_every_property_has_exactly_one_current_controlling_owner_row(seeded):
    assert n(seeded, "select count(*) from properties p where not exists (select 1 from property_ownerships o where o.property_id=p.id and o.disposed_date is null)") == 0


def test_no_orphans(seeded):
    assert seeded.execute("PRAGMA foreign_key_check").fetchall() == []


def test_both_property_types_and_all_markets(seeded):
    assert {r[0] for r in seeded.execute("select distinct property_type from properties")} == {"retail", "industrial"}
    assert n(seeded, "select count(distinct market) from properties") >= 4


def test_duplicate_review_queue_has_items(seeded):
    assert n(seeded, "select count(*) from duplicate_candidates where status='pending'") >= 3


def test_pipeline_volumes(seeded):
    assert n(seeded, "select count(*) from leads") >= 100
    assert n(seeded, "select count(*) from listings") >= 50
    assert n(seeded, "select count(*) from buyer_interests") >= 200
    assert n(seeded, "select count(distinct status) from listings") == 6


def test_at_most_one_active_sale_listing_per_property(seeded):
    assert n(seeded, "select count(*) from (select property_id from listings where status in ('active','under_contract') and listing_type='sale' group by property_id having count(*)>1)") == 0


def test_listing_dates_are_coherent(seeded):
    assert n(seeded, "select count(*) from listings where expiration_date is not null and agreement_date is not null and expiration_date <= agreement_date") == 0
    assert n(seeded, "select count(*) from listings where status='closed' and (sold_price is null or closed_date is null)") == 0


def test_deals_volumes_and_every_pipeline_used(seeded):
    assert n(seeded, "select count(*) from deals") >= 80
    assert n(seeded, "select count(distinct pipeline_id) from deals") == 4
    assert n(seeded, "select count(*) from deal_stage_history") >= 300


def test_deal_rules_hold_in_seed(seeded):
    assert n(seeded, "select count(*) from deals d join stages s on s.id=d.stage_id where s.is_won=1 and (d.price is null or d.price<=0 or d.status!='won')") == 0
    assert n(seeded, "select count(*) from deals d join stages s on s.id=d.stage_id where s.is_lost=1 and (d.lost_reason is null or d.status!='lost')") == 0
    assert n(seeded, "select count(*) from deals d where not exists (select 1 from deal_stage_history h where h.deal_id=d.id)") == 0
    assert n(seeded, "select count(*) from (select deal_id from commission_splits where split_type='percent' group by deal_id having sum(pct) > 100.001)") == 0


def test_history_last_row_matches_current_stage(seeded):
    bad = n(seeded, "select count(*) from deals d where d.stage_id != (select to_stage_id from deal_stage_history h where h.deal_id=d.id order by h.at desc, h.id desc limit 1)")
    assert bad == 0


def test_snapshots_cover_a_year(seeded):
    assert n(seeded, "select count(distinct taken_on) from pipeline_snapshots") >= 50


def test_work_volumes(seeded):
    assert n(seeded, "select count(*) from activities") >= 200
    assert n(seeded, "select count(*) from notes where deleted_at is null") >= 100
    assert n(seeded, "select count(*) from documents") >= 100
    assert n(seeded, "select count(distinct type) from activities") >= 4


def test_activity_integrity(seeded):
    assert n(seeded, "select count(*) from activities a where not exists (select 1 from activity_associations x where x.activity_id=a.id)") == 0
    assert n(seeded, "select count(*) from activities where status='completed' and completed_at is null") == 0
    assert n(seeded, "select count(*) from activities where status='planned' and due_at is null") == 0
    assert n(seeded, "select count(*) from activities where status='planned' and due_at < datetime('now','start of day')") >= 5  # overdue tasks exist for the demo
    assert n(seeded, "select count(*) from activities where status='planned' and date(due_at)=date('now')") >= 3


def test_do_not_contact_respected_in_seed(seeded):
    assert n(seeded, """select count(*) from activities a join activity_associations x on x.activity_id=a.id and x.record_type='contact'
                        join contacts c on c.id=x.record_id where c.do_not_contact=1 and a.type in ('call','email','text')""") == 0


def test_documents_exist_on_disk_with_matching_hash(seeded):
    import hashlib
    for path, digest, size in seeded.execute("select storage_path, content_hash, size from documents limit 40"):
        data = open(path, "rb").read()
        assert len(data) == size and hashlib.sha256(data).hexdigest() == digest


def test_last_contact_is_derived(seeded):
    assert n(seeded, "select count(*) from contacts where last_contact_at is not null") >= 100
    assert n(seeded, "select count(*) from properties where last_contact_at is not null") >= 80


def test_investor_and_fund_volumes(seeded):
    assert n(seeded, "select count(*) from investor_profiles") >= 50
    assert n(seeded, "select count(*) from funds") >= 4
    assert n(seeded, "select count(*) from commitments") >= 60


def test_fund_rules_hold_in_seed(seeded):
    assert n(seeded, "select count(*) from (select f.id from funds f join commitments c on c.fund_id=f.id where c.status in ('committed','funded') group by f.id having sum(c.amount) > f.target_raise)") == 0
    assert n(seeded, "select count(*) from commitments c join investor_profiles p on p.id=c.investor_id where c.status in ('committed','funded') and p.accreditation_status != 'accredited'") == 0
    assert n(seeded, "select count(*) from commitments c join funds f on f.id=c.fund_id where c.status != 'interested' and c.amount < f.minimum_investment") == 0
    assert n(seeded, "select count(*) from commitments where status='funded' and funded_on is null") == 0


def test_goals_seeded_and_reports_have_substance(seeded):
    assert n(seeded, "select count(*) from goals") >= 10
    assert n(seeded, "select count(*) from goals where user_id is null and period_type='year'") == 4


def test_year_of_closed_production_exists(seeded):
    assert n(seeded, "select count(*) from deals d join stages s on s.id=d.stage_id where s.is_won=1 and d.actual_close_date >= date('now','-365 days')") >= 15
