from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import timedelta

from ..audit import log_event
from ..db import utcnow
from ..models.core_sys import AuditEvent
from ..db import get_db
from ..models.core_sys import User
from ..security import current_user, hash_password, make_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    title: str | None = None
    team: str | None = None
    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    token: str
    user: UserOut


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    recent = [e for e in db.scalars(select(AuditEvent).where(AuditEvent.action == "login_failed", AuditEvent.timestamp >= utcnow() - timedelta(minutes=15)).order_by(AuditEvent.id.desc()).limit(200))
              if (e.changes or {}).get("email", "").strip().lower() == email]
    if len(recent) >= 5:
        log_event(db, "login_locked", "users", None, {"email": email})
        db.commit()
        raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(User.email == email))
    ok = bool(user and user.active and hash_password(body.password, user.salt) == user.password_hash)
    log_event(db, "login" if ok else "login_failed", "users", user.id if user else None, {"email": body.email})
    db.commit()
    if not ok:
        raise HTTPException(401, "Invalid email or password")
    return TokenOut(token=make_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.get("/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
