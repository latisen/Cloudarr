"""Job and job event models."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Job(Base):
    """Represents a Sonarr-submitted download item managed through TorBox."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    info_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    sonarr_title: Mapped[str] = mapped_column(String(512), default="")
    magnet_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    torrent_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    torrent_name: Mapped[str] = mapped_column(String(512), default="")
    category: Mapped[str] = mapped_column(String(128), default="sonarr")
    state: Mapped[str] = mapped_column(String(64), index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    save_path: Mapped[str] = mapped_column(String(1024), default="")
    torbox_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    torbox_remote_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    exported_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list[JobEvent]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobEvent(Base):
    """State transition and operational events for a job."""

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(String(1024), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)

    job: Mapped[Job] = relationship(back_populates="events")
