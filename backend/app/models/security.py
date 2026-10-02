"""API tokens (ADR 0017) and workflow rules (ADR 0020)."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, Timestamped

RULE_ENTITIES = ["contact", "company", "property", "listing", "deal", "lead"]
TRIGGER_TYPES = ["record_created", "field_changed", "stage_changed", "date_reached", "scheduled"]
ACTION_TYPES = ["assign_owner", "create_task", "apply_cadence", "create_lead", "notify", "set_field"]


class ApiToken(Timestamped, Base):
    __tablename__ = "api_tokens"
    __audited__ = True
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class Rule(Timestamped, Base):
    __tablename__ = "rules"
    __audited__ = True
    name: Mapped[str] = mapped_column(String(160))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    entity: Mapped[str] = mapped_column(String(20), index=True)
    trigger_type: Mapped[str] = mapped_column(String(20), index=True)
    trigger_config: Mapped[dict] = mapped_column(JSON, default=dict)
    conditions: Mapped[dict | None] = mapped_column(JSON)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(String(300))


class RuleRun(Timestamped, Base):
    __tablename__ = "rule_runs"
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(12), default="ok")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    evaluated: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer, default=0)
    actions_taken: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))


class RuleActionLog(Timestamped, Base):
    __tablename__ = "rule_action_log"
    __table_args__ = (UniqueConstraint("key"),)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"), index=True)
    key: Mapped[str] = mapped_column(String(160))
    entity: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    action_type: Mapped[str] = mapped_column(String(20))
    result: Mapped[str] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(DateTime)
