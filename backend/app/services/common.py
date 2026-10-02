from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.core_sys import User


def user_names(db: Session) -> dict[int, str]:
    return {u.id: u.name for u in db.scalars(select(User))}


def paginate(db: Session, stmt, page: int, limit: int):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    items = db.scalars(stmt.offset((page - 1) * limit).limit(limit)).unique().all()
    return items, total


def years_between(d: date | None, today: date | None = None) -> float | None:
    if not d:
        return None
    today = today or date.today()
    return round((today - d).days / 365.25, 1)


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
