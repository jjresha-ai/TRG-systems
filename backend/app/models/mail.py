"""Email, calendar, templates, unsubscribes, mobile helpers (ADR 0014, 0022, 0029)."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, Timestamped

VISIBILITY = ["private", "team_metadata", "team_subject", "team_full"]


class EmailAccountConnection(Timestamped, Base):
    __tablename__ = "email_connections"
    __audited__ = True
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, unique=True)
    provider: Mapped[str] = mapped_column(String(20), default="capture")  # capture now; microsoft365 / google when chosen
    email_address: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(15), default="active")
    tokens_encrypted: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    sync_cursor: Mapped[str | None] = mapped_column(String(200))
    bcc_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)


class EmailMessage(Timestamped, Base):
    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("user_id", "message_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message_id: Mapped[str] = mapped_column(String(200))
    thread_id: Mapped[str | None] = mapped_column(String(200), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    direction: Mapped[str] = mapped_column(String(10))  # inbound | outbound
    from_addr: Mapped[str] = mapped_column(String(200))
    to_addrs: Mapped[list] = mapped_column(JSON, default=list)
    cc_addrs: Mapped[list] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(15), default="private")
    channel: Mapped[str] = mapped_column(String(10), default="api")  # api | bcc
    associations: Mapped[list["EmailAssociation"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class EmailAssociation(Timestamped, Base):
    __tablename__ = "email_associations"
    __table_args__ = (UniqueConstraint("email_id", "record_type", "record_id"),)
    email_id: Mapped[int] = mapped_column(ForeignKey("email_messages.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(20), index=True)
    record_id: Mapped[int] = mapped_column(Integer, index=True)
    auto: Mapped[bool] = mapped_column(Boolean, default=True)


class CalendarEvent(Timestamped, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("user_id", "external_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[str | None] = mapped_column(String(300))
    attendees: Mapped[list] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(15), default="private")
    associations: Mapped[list["CalendarAssociation"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class CalendarAssociation(Timestamped, Base):
    __tablename__ = "calendar_associations"
    __table_args__ = (UniqueConstraint("event_id", "record_type", "record_id"),)
    event_id: Mapped[int] = mapped_column(ForeignKey("calendar_events.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(20), index=True)
    record_id: Mapped[int] = mapped_column(Integer, index=True)


class ExclusionRule(Timestamped, Base):
    __tablename__ = "email_exclusions"
    __audited__ = True
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # domain | address | keyword
    value: Mapped[str] = mapped_column(String(200))


class EmailTemplate(Timestamped, Base):
    __tablename__ = "email_templates"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(160), unique=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class EmailContactShare(Timestamped, Base):
    __tablename__ = "email_contact_shares"
    __table_args__ = (UniqueConstraint("user_id", "contact_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    level: Mapped[str] = mapped_column(String(15), default="team_metadata")


class Unsubscribe(Timestamped, Base):
    __tablename__ = "unsubscribes"
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    source: Mapped[str | None] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(DateTime)


class BulkSend(Timestamped, Base):
    __tablename__ = "bulk_sends"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(160))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    template_id: Mapped[int] = mapped_column(ForeignKey("email_templates.id"))
    list_id: Mapped[int | None] = mapped_column(Integer)
    listing_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(15), default="prepared")  # prepared; sending needs a connected provider
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    recipients: Mapped[list] = mapped_column(JSON, default=list)
    tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class Star(Timestamped, Base):
    __tablename__ = "stars"
    __table_args__ = (UniqueConstraint("user_id", "record_type", "record_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(20))
    record_id: Mapped[int] = mapped_column(Integer)


class QuickAddLog(Timestamped, Base):
    __tablename__ = "quick_add_log"
    __table_args__ = (UniqueConstraint("user_id", "client_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[str] = mapped_column(String(80))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
