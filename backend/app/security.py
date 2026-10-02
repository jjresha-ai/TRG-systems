"""Authentication (ADR 0025) and role permissions (ADR 0017). Enforced in the backend only."""
import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import config
from .audit import current_actor, current_actor_id
from .db import get_db
from .models.core_sys import User

ROLES = ["admin", "manager", "broker", "assistant", "read_only"]
# action permissions per role (ADR 0017). Entities share the table; restricted fields are handled separately.
ROLE_ACTIONS = {
    "admin": {"view", "create", "edit", "delete", "export", "admin"},
    "manager": {"view", "create", "edit", "delete", "export"},
    "broker": {"view", "create", "edit", "export"},
    "assistant": {"view", "create", "edit"},
    "read_only": {"view"},
}
COMMISSION_VIEW_ROLES = {"admin", "manager", "broker"}
ACCREDITATION_VIEW_ROLES = {"admin", "manager", "broker"}


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


def new_salt() -> str:
    return secrets.token_hex(16)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user: User) -> str:
    payload = _b64(json.dumps({"uid": user.id, "exp": int(time.time()) + config.TOKEN_TTL_SECONDS}).encode())
    sig = _b64(hmac.new(config.SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> int | None:
    try:
        payload, sig = token.split(".")
        good = _b64(hmac.new(config.SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(payload))
        if data["exp"] < time.time():
            return None
        return int(data["uid"])
    except Exception:
        return None


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    uid = read_token(authorization[7:])
    user = db.get(User, uid) if uid else None
    if not user or not user.active:
        raise HTTPException(401, "Invalid or expired token")
    current_actor.set(user.name)
    current_actor_id.set(user.id)
    db.info["actor"], db.info["actor_id"] = user.name, user.id  # sync deps run in worker threads; the session carries the actor
    return user


def require(action: str):
    def dep(user: User = Depends(current_user)) -> User:
        if action not in ROLE_ACTIONS.get(user.role, set()):
            raise HTTPException(403, f"Role '{user.role}' may not {action}")
        return user
    return dep


def can_see_commission(user: User) -> bool:
    return user.role in COMMISSION_VIEW_ROLES
