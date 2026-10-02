"""Import jobs and per-row results (ADR 0016)."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, Timestamped

IMPORT_ENTITIES = ["contact", "company", "property", "owner_properties"]
IMPORT_MODES = ["create", "update", "create_or_update"]


class ImportJob(Timestamped, Base):
    __tablename__ = "import_jobs"
    __audited__ = True
    file_name: Mapped[str] = mapped_column(String(250))
    file_path: Mapped[str] = mapped_column(String(300))
    entity: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(20), default="create")
    source_name: Mapped[str] = mapped_column(String(80))
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    headers: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(15), default="previewed", index=True)  # previewed, running, completed, failed, rolled_back
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime)


class ImportRow(Timestamped, Base):
    __tablename__ = "import_rows"
    job_id: Mapped[int] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    row_no: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    action: Mapped[str] = mapped_column(String(12), index=True)  # create, update, skip, duplicate, error
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_ids: Mapped[dict] = mapped_column(JSON, default=dict)  # {"contact": [], "company": [], "property": [], "ownership": [], "role": [], "external_id": []}
    updated_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    processed: Mapped[bool] = mapped_column(default=False)
