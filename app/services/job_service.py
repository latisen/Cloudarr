"""Job CRUD and state transition helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import JobState, TERMINAL_STATES
from app.models.job import Job, JobEvent
from app.services.state_machine import can_transition


def derive_info_hash(magnet: str | None, fallback: str) -> str:
    """Produce stable pseudo hash for non-native provider IDs."""

    base = magnet or fallback
    return hashlib.sha1(base.encode("utf-8"), usedforsecurity=False).hexdigest()


class JobService:
    """Persistence service for queue jobs and transition events."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_received_job(
        self,
        *,
        magnet_uri: str | None,
        name: str,
        category: str,
        save_path: str,
        torrent_file_path: str | None = None,
    ) -> Job:
        info_hash = derive_info_hash(magnet_uri, torrent_file_path or name)
        existing = self.db.scalar(select(Job).where(Job.info_hash == info_hash))
        if existing:
            return existing

        job = Job(
            info_hash=info_hash,
            magnet_uri=magnet_uri,
            torrent_file_path=torrent_file_path,
            sonarr_title=name,
            torrent_name=name,
            category=category,
            save_path=save_path,
            state=JobState.RECEIVED_FROM_SONARR.value,
            progress=0.0,
        )
        self.db.add(job)
        self.db.commit()
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
        self.db.commit()

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
        self.db.commit()
        self.db.refresh(job)
        self.add_event(job.id, new_state, message, payload=payload)
        return job
