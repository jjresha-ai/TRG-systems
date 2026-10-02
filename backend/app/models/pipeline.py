"""Leads, prospecting triggers, listings, buyer interest (ADR 0007, 0008)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, Timestamped
from .core import Property, Provenance

LEAD_STATUSES = ["new", "contacted", "qualified", "converted", "disqualified"]
LISTING_STATUSES = ["prospect", "active", "under_contract", "closed", "expired", "withdrawn"]
INTEREST_STAGES = ["inquiry", "ca_sent", "ca_signed", "om_sent", "tour", "offer", "declined"]
TRIGGER_KINDS = ["hold_years", "loan_maturity", "ownership_change"]


class LeadSource(Timestamped, Base):
    __tablename__ = "lead_sources"
    name: Mapped[str] = mapped_column(String(80), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Campaign(Timestamped, Base):
    __tablename__ = "campaigns"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("lead_sources.id"))
    started_on: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(300))


class Lead(Timestamped, Base):
    __tablename__ = "leads"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(180))
    company_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    stream: Mapped[str] = mapped_column(String(10), default="seller")
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("lead_sources.id"))
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"))
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_components: Mapped[dict] = mapped_column(JSON, default=dict)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    deal_id: Mapped[int | None] = mapped_column(Integer)
    trigger_key: Mapped[str | None] = mapped_column(String(60), unique=True)
    trigger_reason: Mapped[dict | None] = mapped_column(JSON)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime)
    conversion_outcome: Mapped[str | None] = mapped_column(String(40))
    disqualify_reason: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime)
    property: Mapped[Property | None] = relationship(lazy="joined")
    source: Mapped[LeadSource | None] = relationship(lazy="joined")


class TriggerRule(Timestamped, Base):
    __tablename__ = "trigger_rules"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    threshold: Mapped[int] = mapped_column(Integer)  # years, months or months (by kind)
    property_type: Mapped[str | None] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AssignmentRule(Timestamped, Base):
    __tablename__ = "assignment_rules"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(120))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    property_type: Mapped[str | None] = mapped_column(String(20))
    market: Mapped[str | None] = mapped_column(String(60))
    strategy: Mapped[str] = mapped_column(String(20), default="fixed")  # fixed | round_robin
    user_ids: Mapped[list] = mapped_column(JSON, default=list)
    counter: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Listing(Timestamped, Provenance, Base):
    __tablename__ = "listings"
    __audited__ = True
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    seller_contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    seller_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    listing_type: Mapped[str] = mapped_column(String(10), default="sale")
    status: Mapped[str] = mapped_column(String(20), default="prospect", index=True)
    list_price: Mapped[int | None] = mapped_column(Integer)
    sold_price: Mapped[int | None] = mapped_column(Integer)
    commission_rate_bps: Mapped[int | None] = mapped_column(Integer)
    commission_terms: Mapped[str | None] = mapped_column(String(300))
    agreement_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date, index=True)
    active_date: Mapped[date | None] = mapped_column(Date)
    closed_date: Mapped[date | None] = mapped_column(Date)
    deal_id: Mapped[int | None] = mapped_column(Integer)
    property: Mapped[Property] = relationship(lazy="joined")
    brokers: Mapped[list["ListingBroker"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class ListingBroker(Timestamped, Base):
    __tablename__ = "listing_brokers"
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(20), default="lead")
    split_pct: Mapped[float] = mapped_column(Float, default=100.0)


class BuyerInterest(Timestamped, Base):
    __tablename__ = "buyer_interests"
    __audited__ = True
    __table_args__ = (UniqueConstraint("listing_id", "contact_id"),)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    stage: Mapped[str] = mapped_column(String(20), default="inquiry", index=True)
    offer_amount: Mapped[int | None] = mapped_column(Integer)
    offer_terms: Mapped[str | None] = mapped_column(String(300))
    declined_reason: Mapped[str | None] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(20), default="manual")
    events: Mapped[list["BuyerInterestEvent"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="BuyerInterestEvent.at, BuyerInterestEvent.id")


class BuyerInterestEvent(Timestamped, Base):
    __tablename__ = "buyer_interest_events"
    interest_id: Mapped[int] = mapped_column(ForeignKey("buyer_interests.id"), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(300))
