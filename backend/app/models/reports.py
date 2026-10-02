"""Goals for production reporting (ADR 0021). Snapshots live in models.deals.PipelineSnapshot."""
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, Timestamped

GOAL_METRICS = ["closed_volume", "gci", "listings_taken", "closed_deals"]
GOAL_PERIODS = ["year", "quarter", "month"]


class Goal(Timestamped, Base):
    __tablename__ = "goals"
    __audited__ = True
    __table_args__ = (UniqueConstraint("user_id", "metric", "period_type", "period_start"),)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)  # None = firm-wide
    metric: Mapped[str] = mapped_column(String(20))
    period_type: Mapped[str] = mapped_column(String(10))
    period_start: Mapped[date] = mapped_column(Date, index=True)
    target: Mapped[int] = mapped_column(Integer)
