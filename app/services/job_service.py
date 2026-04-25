"""Job CRUD and state transition helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
import re
from urllib.parse import parse_qs, unquote_plus, urlparse

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.enums import JobState, TERMINAL_STATES
from app.models.job import Job, JobEvent
from app.services.state_machine import can_transition


logger = logging.getLogger(__name__)


def derive_info_hash(magnet: str | None, fallback: str) -> str:
    """Produce stable pseudo hash for non-native provider IDs."""

    base = magnet or fallback
    return hashlib.sha1(base.encode("utf-8"), usedforsecurity=False).hexdigest()


def derive_display_name(magnet_uri: str | None, fallback: str) -> str:
    """Extract a human-friendly title from a magnet URI when available."""

    if magnet_uri:
        parsed = urlparse(magnet_uri)
        dn_values = parse_qs(parsed.query).get("dn") or []
        for value in dn_values:
            title = unquote_plus(value).strip()
            if title:
                return title

        # Fallback for magnet strings that arrive in formats parse_qs/urlparse does not preserve well.
        match = re.search(r"(?:^|[?&])dn=([^&]+)", magnet_uri, flags=re.IGNORECASE)
        if match:
            title = unquote_plus(match.group(1)).strip()
            if title:
                return title
    return fallback


def _looks_like_magnet_name(value: str) -> bool:
    text = value.strip().lower()
    return text.startswith("magnet:?") or "&xt=urn:btih:" in text


class JobService:
    """Persistence service for queue jobs and transition events."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _commit_with_retry(self, *, context: str, attempts: int = 3) -> None:
        for attempt in range(1, attempts + 1):
            try:
                self.db.commit()
                return
            except OperationalError as exc:
                self.db.rollback()
                text = str(exc).lower()
                is_transient_lock = "database is locked" in text or "database is busy" in text
                if is_transient_lock and attempt < attempts:
                    time.sleep(0.1 * attempt)
                    continue
                raise

        raise RuntimeError(f"commit failed in {context}")

    def create_received_job(
        self,
        *,
        magnet_uri: str | None,
        name: str,
        category: str,
        save_path: str,
        torrent_file_path: str | None = None,
    ) -> Job:
        normalized_name = derive_display_name(magnet_uri, name)
        info_hash = derive_info_hash(magnet_uri, torrent_file_path or name)
        existing = self.db.scalar(select(Job).where(Job.info_hash == info_hash))
        if existing:
            better_name = normalized_name
            changed = False
            if better_name and (_looks_like_magnet_name(existing.torrent_name) or not existing.torrent_name.strip()):
                existing.torrent_name = better_name
                changed = True
            if better_name and (_looks_like_magnet_name(existing.sonarr_title) or not existing.sonarr_title.strip()):
                existing.sonarr_title = better_name
                changed = True
            if changed:
                self.db.add(existing)
                self._commit_with_retry(context="update_existing_received_job")
                self.db.refresh(existing)
            return existing

        job = Job(
            info_hash=info_hash,
            magnet_uri=magnet_uri,
            torrent_file_path=torrent_file_path,
            sonarr_title=normalized_name,
            torrent_name=normalized_name,
            category=category,
            save_path=save_path,
            state=JobState.RECEIVED_FROM_SONARR.value,
            progress=0.0,
        )
        self.db.add(job)
        self._commit_with_retry(context="create_received_job")
        self.db.refresh(job)
        self.add_event(job.id, JobState.RECEIVED_FROM_SONARR, "received from sonarr")
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self.db.get(Job, job_id)

    def get_by_hash(self, info_hash: str) -> Job | None:
        return self.db.scalar(select(Job).where(Job.info_hash == info_hash))

    def list_jobs(self) -> list[Job]:
        return list(self.db.scalars(select(Job).order_by(Job.created_at.desc())).all())

    def list_active_jobs(self) -> list[Job]:
        rows = self.db.scalars(select(Job).order_by(Job.created_at.asc())).all()
        return [row for row in rows if JobState(row.state) not in TERMINAL_STATES]

    def add_event(self, job_id: str, state: JobState, message: str, payload: dict[str, str] | None = None) -> None:
        event = JobEvent(job_id=job_id, state=state.value, message=message, payload_json=json.dumps(payload or {}))
        self.db.add(event)
        self._commit_with_retry(context="add_event")

    def transition(
        self,
        job: Job,
        new_state: JobState,
        *,
        message: str,
        payload: dict[str, str] | None = None,
        error: str | None = None,
    ) -> Job:
        current = JobState(job.state)
        if current != new_state and not can_transition(current, new_state):
            raise ValueError(f"Invalid transition {current} -> {new_state}")

        job.state = new_state.value
        if error:
            job.error_message = error
        if new_state in TERMINAL_STATES:
            job.completed_at = dt.datetime.utcnow()
            if new_state == JobState.READY_FOR_IMPORT:
                job.progress = 1.0

        self.db.add(job)
        self._commit_with_retry(context="transition")
        self.db.refresh(job)
        try:
            self.add_event(job.id, new_state, message, payload=payload)
        except Exception:  # noqa: BLE001
            logger.exception("job_event_write_failed", extra={"job_id": job.id, "state": new_state.value})
        return job
