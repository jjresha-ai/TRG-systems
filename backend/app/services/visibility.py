"""Record visibility (ADR 0017): firm-open by default, team-scoped supported without schema change, confidential by exception."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.core_sys import User
from ..models.platform import AppSetting


def visibility_mode(db: Session) -> str:
    s = db.get(AppSetting, "visibility")
    return (s.value or {}).get("mode", "firm_open") if s else "firm_open"


class Visibility:
    """Per-request helper: resolves the mode and owners' teams once."""

    def __init__(self, db: Session, user: User):
        self.user, self.mode = user, visibility_mode(db)
        self.teams = {u.id: u.team for u in db.scalars(select(User))} if self.mode == "team_scoped" else {}

    def can_see(self, obj) -> bool:
        if getattr(obj, "deleted_at", None):
            return False
        u = self.user
        if u.role in ("admin", "manager"):
            return True
        owner = getattr(obj, "owner_user_id", None)
        # a confidential *listing* stays visible: its confidentiality masks buyer identities instead (ADR 0008/0017)
        if getattr(obj, "confidential", False) and owner != u.id and obj.__tablename__ != "listings":
            return False
        if self.mode == "team_scoped" and owner is not None and owner != u.id and self.teams.get(owner) != u.team:
            return False
        return True


def sql_clause(db: Session, user: User, model):
    """The same rule as Visibility.can_see, as a WHERE clause for paginated list endpoints (None = no restriction)."""
    from sqlalchemy import and_, or_
    if user.role in ("admin", "manager"):
        return None
    conds = [] if model.__tablename__ == "listings" else [or_(model.confidential.is_(False), model.owner_user_id == user.id)]
    if visibility_mode(db) == "team_scoped":
        mine = [u.id for u in db.scalars(select(User).where(User.team == user.team))]
        conds.append(or_(model.owner_user_id.is_(None), model.owner_user_id.in_(mine)))
    return and_(*conds) if conds else None


def assert_can_set_confidential(obj, user: User):
    from fastapi import HTTPException
    if user.role not in ("admin", "manager") and obj.owner_user_id != user.id:
        raise HTTPException(403, "Only the owner, a manager or an admin can change confidentiality")
