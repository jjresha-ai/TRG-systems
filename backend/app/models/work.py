"""Activities/tasks, cadences, notes, documents, notifications (ADR 0011, 0012, 0013)."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, Timestamped

RECORD_TYPES = ["contact", "company", "property", "listing", "deal", "lead"]
ACTIVITY_TYPES = ["call", "email", "meeting", "site_visit", "text", "other"]
OUTCOMES = ["spoke", "left_voicemail", "no_answer", "not_interested", "meeting_set"]
PRIORITIES = ["low", "normal", "high"]
DOC_TYPES = ["om", "ca", "loi", "psa", "rent_roll", "flyer", "photo", "other"]


class Activity(Timestamped, Base):
    __tablename__ = "activities"
    __audited__ = True
    type: Mapped[str] = mapped_column(String(20), index=True)
    subject: Mapped[str] = mapped_column(String(250))
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="planned", index=True)  # planned | completed | cancelled
    due_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    outcome: Mapped[str | None] = mapped_column(String(20))
    recurrence_days: Mapped[int | None] = mapped_column(Integer)
    recurrence_parent_id: Mapped[int | None] = mapped_column(Integer)
    cadence_id: Mapped[int | None] = mapped_column(ForeignKey("cadence_templates.id"))
    source_key: Mapped[str | None] = mapped_column(String(80), index=True)  # idempotency for generated tasks
    associations: Mapped[list["ActivityAssociation"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class ActivityAssociation(Timestamped, Base):
    __tablename__ = "activity_associations"
    __table_args__ = (UniqueConstraint("activity_id", "record_type", "record_id"),)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(20), index=True)
    record_id: Mapped[int] = mapped_column(Integer, index=True)


class CadenceTemplate(Timestamped, Base):
    __tablename__ = "cadence_templates"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(String(300))
    record_type: Mapped[str] = mapped_column(String(20), default="contact")
    steps: Mapped[list] = mapped_column(JSON, default=list)  # [{day_offset, type, subject, priority}]


class Note(Timestamped, Base):
    __tablename__ = "notes"
    __audited__ = True
    body: Mapped[str] = mapped_column(Text)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(String(10), default="team")  # team | private
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    associations: Mapped[list["NoteAssociation"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    versions: Mapped[list["NoteVersion"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="NoteVersion.version")


class NoteAssociation(Timestamped, Base):
    __tablename__ = "note_associations"
    __table_args__ = (UniqueConstraint("note_id", "record_type", "record_id"),)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(20), index=True)
    record_id: Mapped[int] = mapped_column(Integer, index=True)


class NoteVersion(Timestamped, Base):
    __tablename__ = "note_versions"
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    edited_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    edited_at: Mapped[datetime] = mapped_column(DateTime)


class Document(Timestamped, Base):
    __tablename__ = "documents"
    __audited__ = True
    file_name: Mapped[str] = mapped_column(String(250), index=True)
    doc_type: Mapped[str] = mapped_column(String(20), default="other")
    content_type: Mapped[str | None] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(300))
    uploader_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    visibility: Mapped[str] = mapped_column(String(15), default="team")  # team | confidential
    version: Mapped[int] = mapped_column(Integer, default=1)
    group_id: Mapped[int | None] = mapped_column(Integer, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    associations: Mapped[list["DocumentAssociation"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class DocumentAssociation(Timestamped, Base):
    __tablename__ = "document_associations"
    __table_args__ = (UniqueConstraint("document_id", "record_type", "record_id"),)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    record_type: Mapped[str] = mapped_column(String(20), index=True)
    record_id: Mapped[int] = mapped_column(Integer, index=True)


class Notification(Timestamped, Base):
    __tablename__ = "notifications"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # mention, task, rule, system
    message: Mapped[str] = mapped_column(String(300))
    record_type: Mapped[str | None] = mapped_column(String(20))
    record_id: Mapped[int | None] = mapped_column(Integer)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    key: Mapped[str | None] = mapped_column(String(80), index=True)  # idempotency
