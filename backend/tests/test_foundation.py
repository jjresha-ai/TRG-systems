from sqlalchemy import select

from app.db import SessionLocal
from app.models.core_sys import AuditEvent


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_progress_lists_all_stages(client):
    stages = client.get("/api/progress").json()["stages"]
    assert [s["id"] for s in stages] == list(range(9))


def test_login_success_and_me(client, users):
    r = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "pw12345"})
    assert r.status_code == 200
    token = r.json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "admin@test.com" and me.json()["role"] == "admin"


def test_login_failure_is_audited(client, users):
    r = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "wrong"})
    assert r.status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "login_failed")) is not None


def test_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_users_list(client, admin):
    r = client.get("/api/auth/users", headers=admin)
    assert r.status_code == 200 and len(r.json()) >= 5
