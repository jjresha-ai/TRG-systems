"""Pipelines, deals, parties, stage history, commission splits (ADR 0010)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, Timestamped
from .core import Property, Provenance

DEAL_STATUSES = ["open", "won", "lost"]
PARTY_ROLES = ["seller", "buyer", "lender", "attorney", "title", "1031_party", "co_broker", "other"]


class Pipeline(Timestamped, Base):
    __tablename__ = "pipelines"
    key: Mapped[str] = mapped_column(String(30), unique=True)  # seller, buyer, capital, leasing
    name: Mapped[str] = mapped_column(String(80))
    deal_type: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    stages: Mapped[list["Stage"]] = relationship(order_by="Stage.position", lazy="selectin")


class Stage(Timestamped, Base):
    __tablename__ = "stages"
    __audited__ = True
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)
    probability: Mapped[int] = mapped_column(Integer, default=0)  # percent
    rotting_days: Mapped[int | None] = mapped_column(Integer)
    is_won: Mapped[bool] = mapped_column(Boolean, default=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, default=False)


class Deal(Timestamped, Provenance, Base):
    __tablename__ = "deals"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(200))
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"), index=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"), index=True)
    listing_id: Mapped[int | None] = mapped_column(Integer, index=True)
    deal_type: Mapped[str] = mapped_column(String(20), default="sale")
    price: Mapped[int | None] = mapped_column(Integer)
    gross_commission: Mapped[int | None] = mapped_column(Integer)
    commission_rate_bps: Mapped[int | None] = mapped_column(Integer)
    probability: Mapped[int | None] = mapped_column(Integer)  # override; None = stage default
    expected_close_date: Mapped[date | None] = mapped_column(Date, index=True)
    actual_close_date: Mapped[date | None] = mapped_column(Date)
    listing_expiration_date: Mapped[date | None] = mapped_column(Date)
    dd_expiry_date: Mapped[date | None] = mapped_column(Date)
    loan_contingency_date: Mapped[date | None] = mapped_column(Date)
    lost_reason: Mapped[str | None] = mapped_column(String(200))
    stage_entered_at: Mapped[datetime] = mapped_column(DateTime)
    pipeline: Mapped[Pipeline] = relationship(lazy="joined")
    stage: Mapped[Stage] = relationship(lazy="joined")
    property: Mapped[Property | None] = relationship(lazy="joined")
    parties: Mapped[list["DealParty"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    splits: Mapped[list["CommissionSplit"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class DealParty(Timestamped, Base):
    __tablename__ = "deal_parties"
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))


class DealStageHistory(Timestamped, Base):
    """Append-only (ADR 0010): never edited or deleted."""
    __tablename__ = "deal_stage_history"
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    from_stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"))
    to_stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id"))
    at: Mapped[datetime] = mapped_column(DateTime)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(200))


@event.listens_for(DealStageHistory, "before_update")
def _no_update(mapper, conn, target):
    raise ValueError("DealStageHistory is append-only")


@event.listens_for(DealStageHistory, "before_delete")
def _no_delete(mapper, conn, target):
    raise ValueError("DealStageHistory is append-only")


class CommissionSplit(Timestamped, Base):
    __tablename__ = "commission_splits"
    __audited__ = True
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    recipient_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    external_name: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="internal")  # internal, co_broker, referral
    split_type: Mapped[str] = mapped_column(String(10), default="percent")  # percent | amount
    pct: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[int | None] = mapped_column(Integer)


class PipelineSnapshot(Timestamped, Base):
    """Periodic pipeline totals so past forecasts can be compared with outcomes (ADR 0021)."""
    __tablename__ = "pipeline_snapshots"
    taken_on: Mapped[date] = mapped_column(Date, index=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"))
    open_deals: Mapped[int] = mapped_column(Integer)
    volume: Mapped[int] = mapped_column(Integer)
    weighted_volume: Mapped[int] = mapped_column(Integer)
    weighted_commission: Mapped[int] = mapped_column(Integer)
