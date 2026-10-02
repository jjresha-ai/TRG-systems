"""Saved views, lists, custom field definitions, settings (ADR 0015, 0019)."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, Timestamped

FILTER_ENTITIES = ["contact", "company", "property", "listing", "deal", "lead"]
FIELD_TYPES = ["text", "long_text", "number", "currency", "date", "checkbox", "single_select", "multi_select", "lookup_user", "lookup_record"]


class SavedView(Timestamped, Base):
    __tablename__ = "saved_views"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(120))
    entity: Mapped[str] = mapped_column(String(20), index=True)
    filter: Mapped[dict] = mapped_column(JSON, default=dict)
    columns: Mapped[list] = mapped_column(JSON, default=list)
    sort_field: Mapped[str | None] = mapped_column(String(60))
    sort_dir: Mapped[str] = mapped_column(String(4), default="asc")
    visibility: Mapped[str] = mapped_column(String(10), default="private")  # private | shared
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class ListDef(Timestamped, Base):
    __tablename__ = "lists"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(120))
    entity: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # dynamic | static
    filter: Mapped[dict | None] = mapped_column(JSON)
    members: Mapped[list | None] = mapped_column(JSON)  # static membership snapshot (ids)
    description: Mapped[str | None] = mapped_column(String(300))
    visibility: Mapped[str] = mapped_column(String(10), default="shared")
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime)


class FieldDefinition(Timestamped, Base):
    __tablename__ = "field_definitions"
    __audited__ = True
    __table_args__ = (UniqueConstraint("entity", "key"),)
    entity: Mapped[str] = mapped_column(String(20), index=True)
    key: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(20))
    options: Mapped[list] = mapped_column(JSON, default=list)  # for selects; record_type for lookup_record in options[0]
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    required_when: Mapped[dict | None] = mapped_column(JSON)  # e.g. {"property_type": "retail"} or {"pipeline": "seller"}
    show_when: Mapped[dict | None] = mapped_column(JSON)
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
