"""Core entity model (ADR 0005, 0006)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, Timestamped

CONTACT_TYPES = ["owner", "buyer", "investor", "lender", "attorney", "tenant", "broker", "other"]
COMPANY_KINDS = ["llc", "trust", "fund", "family_office", "brokerage", "lender", "corporation", "other"]
ROLE_KINDS = ["principal", "manager", "asset_manager", "representative", "attorney", "employee"]
PROPERTY_TYPES = ["retail", "industrial"]
HOLD_INTENTS = ["unknown", "hold", "open_to_sell", "selling_soon"]
LIFECYCLE = ["prospect", "active_relationship", "client", "past_client", "inactive"]


class Provenance:
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str | None] = mapped_column(String(80))
    import_job_id: Mapped[int | None] = mapped_column(Integer, index=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    custom: Mapped[dict] = mapped_column(JSON, default=dict)  # ADR 0019 custom field values
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # ADR 0011 derived
    last_contact_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confidential: Mapped[bool] = mapped_column(Boolean, default=False)


class Contact(Timestamped, Provenance, Base):
    __tablename__ = "contacts"
    __audited__ = True
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80), index=True)
    full_name: Mapped[str] = mapped_column(String(180), index=True)
    title: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(2))
    zip: Mapped[str | None] = mapped_column(String(10))
    contact_types: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")
    lifecycle_stage: Mapped[str] = mapped_column(String(30), default="prospect")
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    do_not_contact_reason: Mapped[str | None] = mapped_column(String(200))
    emails: Mapped[list["ContactEmail"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="ContactEmail.id")
    phones: Mapped[list["ContactPhone"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="ContactPhone.id")


class ContactEmail(Timestamped, Base):
    __tablename__ = "contact_emails"
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    email: Mapped[str] = mapped_column(String(200))
    normalized: Mapped[str] = mapped_column(String(200), index=True)
    label: Mapped[str] = mapped_column(String(20), default="work")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class ContactPhone(Timestamped, Base):
    __tablename__ = "contact_phones"
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    phone: Mapped[str] = mapped_column(String(40))
    normalized: Mapped[str] = mapped_column(String(20), index=True)  # E.164
    label: Mapped[str] = mapped_column(String(20), default="mobile")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class Company(Timestamped, Provenance, Base):
    __tablename__ = "companies"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(200), index=True)
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="llc")
    website: Mapped[str | None] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(120), index=True)
    address: Mapped[str | None] = mapped_column(String(200))
    normalized_address: Mapped[str | None] = mapped_column(String(250), index=True)
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(2))
    zip: Mapped[str | None] = mapped_column(String(10))
    parent_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))


class ContactCompanyRole(Timestamped, Base):
    __tablename__ = "contact_company_roles"
    __audited__ = True
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    role: Mapped[str] = mapped_column(String(30), default="principal")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    contact: Mapped[Contact] = relationship(lazy="joined")
    company: Mapped[Company] = relationship(lazy="joined")


class Property(Timestamped, Provenance, Base):
    __tablename__ = "properties"
    __audited__ = True
    name: Mapped[str | None] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(200))
    normalized_address: Mapped[str] = mapped_column(String(250), index=True)
    city: Mapped[str] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(2), default="CA")
    zip: Mapped[str | None] = mapped_column(String(10))
    apn: Mapped[str | None] = mapped_column(String(40), index=True)
    apn_norm: Mapped[str | None] = mapped_column(String(40), index=True)
    county: Mapped[str] = mapped_column(String(60), default="Orange")
    property_type: Mapped[str] = mapped_column(String(20), index=True)
    subtype: Mapped[str | None] = mapped_column(String(60))
    market: Mapped[str | None] = mapped_column(String(60), index=True)
    submarket: Mapped[str | None] = mapped_column(String(60))
    building_sf: Mapped[int | None] = mapped_column(Integer)
    land_acres: Mapped[float | None] = mapped_column(Float)
    units: Mapped[int | None] = mapped_column(Integer)
    year_built: Mapped[int | None] = mapped_column(Integer)
    zoning: Mapped[str | None] = mapped_column(String(30))
    noi: Mapped[int | None] = mapped_column(Integer)
    cap_rate_bps: Mapped[int | None] = mapped_column(Integer)
    estimated_value: Mapped[int | None] = mapped_column(Integer)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    # Debt (ADR 0005): structured, drives hold/sell triggers
    lender: Mapped[str | None] = mapped_column(String(120))
    loan_original_amount: Mapped[int | None] = mapped_column(Integer)
    loan_rate_type: Mapped[str | None] = mapped_column(String(20))
    loan_maturity_date: Mapped[date | None] = mapped_column(Date, index=True)
    # Structured prospecting facts (ADR 0012): never buried in notes
    hold_intent: Mapped[str] = mapped_column(String(20), default="unknown")
    pricing_expectation: Mapped[int | None] = mapped_column(Integer)


class PropertyOwnership(Timestamped, Base):
    __tablename__ = "property_ownerships"
    __audited__ = True
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    ownership_pct: Mapped[float] = mapped_column(Float, default=100.0)
    acquired_date: Mapped[date | None] = mapped_column(Date, index=True)
    disposed_date: Mapped[date | None] = mapped_column(Date, index=True)
    acquisition_price: Mapped[int | None] = mapped_column(Integer)
    property: Mapped[Property] = relationship(lazy="joined")
    company: Mapped[Company | None] = relationship(lazy="joined")
    contact: Mapped[Contact | None] = relationship(lazy="joined")


class ExternalId(Timestamped, Base):
    __tablename__ = "external_ids"
    __table_args__ = (UniqueConstraint("system", "external_id", "entity"),)
    entity: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    system: Mapped[str] = mapped_column(String(60))
    external_id: Mapped[str] = mapped_column(String(120))


class DuplicateCandidate(Timestamped, Base):
    __tablename__ = "duplicate_candidates"
    entity: Mapped[str] = mapped_column(String(30), index=True)
    a_id: Mapped[int] = mapped_column(Integer)
    b_id: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, dismissed, merged


class MergeLog(Timestamped, Base):
    __tablename__ = "merge_logs"
    entity: Mapped[str] = mapped_column(String(30), index=True)
    survivor_id: Mapped[int] = mapped_column(Integer)
    absorbed_id: Mapped[int] = mapped_column(Integer)
    field_decisions: Mapped[dict] = mapped_column(JSON, default=dict)
    moved: Mapped[list] = mapped_column(JSON, default=list)  # [{table, id, column}]
    merged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime)
