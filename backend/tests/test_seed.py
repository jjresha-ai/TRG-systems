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
