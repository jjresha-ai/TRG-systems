"""Authentication (ADR 0025) and role permissions (ADR 0017). Enforced in the backend only."""
import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .audit import current_actor, current_actor_id
from .db import get_db
from .models.core_sys import User

ROLES = ["admin", "manager", "broker", "assistant", "read_only"]
# action permissions per role (ADR 0017). Entities share the table; restricted fields are handled separately.
ROLE_ACTIONS = {
    "admin": {"view", "create", "edit", "delete", "export", "import", "admin"},
    "manager": {"view", "create", "edit", "delete", "export", "import"},
    "broker": {"view", "create", "edit", "export", "import"},
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


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    bearer = authorization[7:].strip()
    user = None
    if bearer.startswith("trg_"):
        from .audit import log_event
        from .db import utcnow
        from .models.security import ApiToken
        tok = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_api_token(bearer)))
        if not tok or tok.revoked_at or (tok.expires_at and tok.expires_at < utcnow()):
            raise HTTPException(401, "Invalid, revoked or expired API token")
        user = db.get(User, tok.user_id)
        if not user or not user.active:
            raise HTTPException(401, "The token's user is inactive")
        user.token_scopes = set(tok.scopes) & ROLE_ACTIONS.get(user.role, set())  # a token can never exceed its user's role
        db.info["actor"], db.info["actor_id"] = f"{user.name} (API token '{tok.name}')", user.id
        tok.last_used_at = utcnow()
        log_event(db, "api_token_use", "api_tokens", tok.id, {"method": request.method, "path": request.url.path})  # every use is audited (ADR 0018)
        db.commit()
        current_actor.set(db.info["actor"])
        current_actor_id.set(user.id)
        return user
    uid = read_token(bearer)
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
        scopes = getattr(user, "token_scopes", None)
        if scopes is not None and action not in scopes:
            raise HTTPException(403, f"This API token is not scoped for '{action}'")
        return user
    return dep


def can_see_commission(user: User) -> bool:
    return user.role in COMMISSION_VIEW_ROLES
