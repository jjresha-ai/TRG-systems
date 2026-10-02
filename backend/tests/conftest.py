import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="trg-test-")
os.environ["TRG_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["TRG_SCHEDULER"] = "0"
os.environ["TRG_STORAGE_DIR"] = f"{_tmp}/storage"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.core_sys import User  # noqa: E402
from app.security import hash_password, new_salt  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def make_user(email, role="admin", name="Test User", password="pw12345"):
    db = SessionLocal()
    salt = new_salt()
    u = User(email=email, name=name, role=role, salt=salt, password_hash=hash_password(password, salt))
    db.add(u)
    db.commit()
    db.close()


@pytest.fixture(scope="session")
def users():
    for role in ["admin", "manager", "broker", "assistant", "read_only"]:
        make_user(f"{role}@test.com", role, name=f"{role.title()} Tester")
    return True


def auth_headers(client, role="admin"):
    r = client.post("/api/auth/login", json={"email": f"{role}@test.com", "password": "pw12345"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(client, users):
    return auth_headers(client, "admin")


@pytest.fixture(scope="session")
def headers_for(client, users):
    cache = {}

    def f(role):
        if role not in cache:
            cache[role] = auth_headers(client, role)
        return cache[role]
    return f
