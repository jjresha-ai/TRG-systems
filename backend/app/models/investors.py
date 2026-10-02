"""Investor profiles, funds, commitments (ADR 0009). Accreditation data is sensitive (ADR 0017, 0018)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, Timestamped
from .core import Company, Contact, Provenance

ACCREDITATION = ["unknown", "pending", "accredited", "not_accredited"]
FUND_STATUSES = ["planning", "raising", "closed", "deployed"]
COMMITMENT_STATUSES = ["interested", "soft_circled", "committed", "funded"]
CHANNELS = ["email", "phone", "text", "in_person"]


class InvestorProfile(Timestamped, Base):
    __tablename__ = "investor_profiles"
    __audited__ = True
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), index=True, unique=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True, unique=True)
    asset_classes: Mapped[list] = mapped_column(JSON, default=list)  # retail, industrial
    markets: Mapped[list] = mapped_column(JSON, default=list)
    min_check: Mapped[int | None] = mapped_column(Integer)
    max_check: Mapped[int | None] = mapped_column(Integer)
    min_cap_rate_bps: Mapped[int | None] = mapped_column(Integer)
    target_return_notes: Mapped[str | None] = mapped_column(String(300))
    exchange_1031: Mapped[bool] = mapped_column(Boolean, default=False)
    exchange_deadline: Mapped[date | None] = mapped_column(Date)
    accreditation_status: Mapped[str] = mapped_column(String(20), default="unknown")
    accreditation_verified_on: Mapped[date | None] = mapped_column(Date)
    preferred_channel: Mapped[str] = mapped_column(String(15), default="email")
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    custom: Mapped[dict] = mapped_column(JSON, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    contact: Mapped[Contact | None] = relationship(lazy="joined")
    company: Mapped[Company | None] = relationship(lazy="joined")


class Fund(Timestamped, Base):
    __tablename__ = "funds"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(160), unique=True)
    sponsor_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    status: Mapped[str] = mapped_column(String(15), default="planning", index=True)
    target_raise: Mapped[int] = mapped_column(Integer)
    minimum_investment: Mapped[int] = mapped_column(Integer, default=50000)
    strategy: Mapped[str | None] = mapped_column(String(300))
    target_return_notes: Mapped[str | None] = mapped_column(String(200))
    opened_on: Mapped[date | None] = mapped_column(Date)
    closing_date: Mapped[date | None] = mapped_column(Date)
    custom: Mapped[dict] = mapped_column(JSON, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    properties: Mapped[list["FundProperty"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    deals: Mapped[list["FundDeal"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class FundProperty(Timestamped, Base):
    __tablename__ = "fund_properties"
    __table_args__ = (UniqueConstraint("fund_id", "property_id"),)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"), index=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)


class FundDeal(Timestamped, Base):
    __tablename__ = "fund_deals"
    __table_args__ = (UniqueConstraint("fund_id", "deal_id"),)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"), index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)


class Commitment(Timestamped, Base):
    __tablename__ = "commitments"
    __audited__ = True
    investor_id: Mapped[int] = mapped_column(ForeignKey("investor_profiles.id"), index=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(15), default="interested", index=True)
    interested_on: Mapped[date | None] = mapped_column(Date)
    soft_circled_on: Mapped[date | None] = mapped_column(Date)
    committed_on: Mapped[date | None] = mapped_column(Date)
    funded_on: Mapped[date | None] = mapped_column(Date)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    investor: Mapped[InvestorProfile] = relationship(lazy="joined")
    fund: Mapped[Fund] = relationship(lazy="joined")
