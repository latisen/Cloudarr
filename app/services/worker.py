"""Background worker for TorBox orchestration lifecycle."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.enums import JobState
from app.models.job import Job, JobEvent
from app.services.job_service import JobService
from app.services.mount_manager import WebDavMountManager
from app.services.provider.base import DebridProvider
from app.services.state_machine import can_transition
from app.services.symlink_manager import SymlinkManager

logger = logging.getLogger(__name__)


class JobWorker:
    """Polls active jobs and drives state transitions."""

    def __init__(
        self,
        *,
        db_factory: Callable[[], Session],
        settings: Settings,
        provider: DebridProvider,
        mount_manager: WebDavMountManager,
        symlink_manager: SymlinkManager,
    ) -> None:
        self._db_factory = db_factory
        self._settings = settings
        self._provider = provider
        self._mount_manager = mount_manager
        self._symlink_manager = symlink_manager
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def run_forever(self) -> None:
        self._running = True
        logger.info("worker_started")
        while self._running:
            db: Session = self._db_factory()
            try:
                await self._tick(db)
            except Exception:  # noqa: BLE001
                logger.exception("worker_tick_failed")
            finally:
                db.close()
            await asyncio.sleep(self._settings.poll_interval_seconds)

    async def _tick(self, db: Session) -> None:
        service = JobService(db)
        active = service.list_active_jobs()
        for job in active:
            try:
                await self._process_job(db, service, job)
            except Exception as exc:  # noqa: BLE001
                logger.exception("job_process_failed", extra={"job_id": job.id, "state": job.state})
                detailed_error = f"{type(exc).__name__}: {exc}"
                try:
                    db.rollback()
                    self._transition_or_log(
                        db,
                        service,
                        job,
                        JobState.FAILED,
                        message=f"Unhandled worker exception: {detailed_error}",
                        error=detailed_error,
                        payload={"exception_type": type(exc).__name__, "exception": str(exc)},
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("job_recovery_failed", extra={"job_id": job.id, "state": job.state})

    def _transition_or_log(
        self,
        db: Session,
        service: JobService,
        job: Job,
        new_state: JobState,
        *,
        message: str,
        payload: dict[str, str] | None = None,
        error: str | None = None,
    ) -> bool:
        db.refresh(job)
        current = JobState(job.state)
        if current != new_state and not can_transition(current, new_state):
            logger.warning(
                "job_transition_skipped",
                extra={"job_id": job.id, "state": job.state, "target_state": new_state.value},
            )
            return False

        service.transition(job, new_state, message=message, payload=payload, error=error)
        return True

    def _state_entered_at(self, db: Session, job_id: str, state: JobState) -> dt.datetime | None:
        return db.scalar(
            select(JobEvent.created_at)
            .where(JobEvent.job_id == job_id, JobEvent.state == state.value)
            .order_by(desc(JobEvent.created_at))
            .limit(1)
        )

    async def _process_job(self, db: Session, service: JobService, job: Job) -> None:
        state = JobState(job.state)

        if state == JobState.RECEIVED_FROM_SONARR:
            self._transition_or_log(db, service, job, JobState.VALIDATING, message="Validating job")
            return

        if state == JobState.VALIDATING:
            try:
                if job.magnet_uri:
                    submission = await self._provider.submit_magnet(job.magnet_uri)
                elif job.torrent_file_path:
                    payload_path = Path(job.torrent_file_path)
                    if not payload_path.exists():
                        self._transition_or_log(
                            db,
                            service,
                            job,
                            JobState.FAILED,
                            message="Missing torrent payload",
                            error=f"Not found: {payload_path}",
                        )
                        return
                    data = payload_path.read_bytes()
                    submission = await self._provider.submit_torrent_bytes(payload_path.name, data)
                else:
                    self._transition_or_log(
                        db,
                        service,
                        job,
                        JobState.FAILED,
                        message="Missing input",
                        error="No magnet or torrent file",
                    )
                    return
            except RuntimeError as exc:
                detail = str(exc)
                transient = any(token in detail for token in ("429", "too_many_requests", "parameter_missing"))
                if transient and job.retries < self._settings.max_submit_retries:
                    job.retries += 1
                    db.add(job)
                    db.commit()
                    db.refresh(job)
                    self._transition_or_log(
                        db,
                        service,
                        job,
                        JobState.VALIDATING,
                        message=(
                            "Transient provider error while submitting; will retry "
                            f"({job.retries}/{self._settings.max_submit_retries})"
                        ),
                        error=detail,
                    )
                    return
                raise

            db.refresh(job)
            if JobState(job.state) != JobState.VALIDATING:
                logger.info(
                    "job_state_changed_during_submission",
                    extra={"job_id": job.id, "state": job.state},
                )
                return

            job.torbox_job_id = submission.provider_job_id
            job.torrent_name = submission.display_name or job.torrent_name
            db.add(job)
            db.commit()
            db.refresh(job)
            self._transition_or_log(db, service, job, JobState.SUBMITTED_TO_TORBOX, message="Submitted to provider")
            return

        if state == JobState.SUBMITTED_TO_TORBOX:
            self._transition_or_log(db, service, job, JobState.WAITING_FOR_TORBOX, message="Waiting for provider readiness")
            return

        if state == JobState.WAITING_FOR_TORBOX:
            if not job.torbox_job_id:
                self._transition_or_log(
                    db,
                    service,
                    job,
                    JobState.FAILED,
                    message="Missing provider job id",
                    error="No provider ID",
                )
                return
            status = await self._provider.get_status(job.torbox_job_id)
            db.refresh(job)
            if JobState(job.state) != JobState.WAITING_FOR_TORBOX:
                logger.info(
                    "job_state_changed_during_provider_poll",
                    extra={"job_id": job.id, "state": job.state},
                )
                return

            waiting_since = self._state_entered_at(db, job.id, JobState.WAITING_FOR_TORBOX) or job.updated_at
            age_seconds = (dt.datetime.utcnow() - waiting_since).total_seconds()
            if age_seconds >= self._settings.provider_wait_timeout_seconds:
                self._transition_or_log(
                    db,
                    service,
                    job,
                    JobState.NEEDS_ATTENTION,
                    message="Provider wait timeout",
                    error=(
                        "Provider not ready within timeout; "
                        f"status={status.status}; progress={status.progress:.3f}"
                    ),
                )
                return

            job.progress = status.progress
            if status.is_failed:
                self._transition_or_log(
                    db,
                    service,
                    job,
                    JobState.FAILED,
                    message="Provider failed",
                    error=status.error or "unknown",
                )
                return
            if status.is_ready:
                if not status.remote_path:
                    self._transition_or_log(
                        db,
                        service,
                        job,
                        JobState.FAILED,
                        message="Provider reported ready but no mountable path is available",
                        error=status.error or "remote_path missing",
                    )
                    return
                job.torbox_remote_path = status.remote_path
                db.add(job)
                db.commit()
                db.refresh(job)
                self._transition_or_log(db, service, job, JobState.TORBOX_READY, message="Provider marked content ready")
            else:
                db.add(job)
                db.commit()
            return

        if state == JobState.TORBOX_READY:
            self._transition_or_log(db, service, job, JobState.REFRESHING_WEBDAV, message="Refreshing WebDAV view")
            return

        if state == JobState.REFRESHING_WEBDAV:
            if not job.torbox_remote_path:
                self._transition_or_log(
                    db,
                    service,
                    job,
                    JobState.FAILED,
                    message="No remote path",
                    error="torbox_remote_path missing",
                )
                return
            visible, msg = await self._mount_manager.ensure_remote_path_visible(job.torbox_remote_path)
            db.refresh(job)
            if JobState(job.state) != JobState.REFRESHING_WEBDAV:
                logger.info(
                    "job_state_changed_during_webdav_refresh",
                    extra={"job_id": job.id, "state": job.state},
                )
                return
            if not visible:
                self._transition_or_log(
                    db,
                    service,
                    job,
                    JobState.NEEDS_ATTENTION,
                    message="WebDAV path not visible",
                    error=msg,
                )
                return
            if msg.startswith("resolved_relative_path="):
                # Keep downstream symlink creation aligned with the concrete path visible in the mount.
                job.torbox_remote_path = msg.split("=", 1)[1]
                db.add(job)
                db.commit()
                db.refresh(job)
                msg = "resolved_remote_path"
            self._transition_or_log(db, service, job, JobState.WEBDAV_VISIBLE, message=msg)
            return

        if state == JobState.NEEDS_ATTENTION:
            if job.retries >= self._settings.max_submit_retries:
                self._transition_or_log(
                    db,
                    service,
                    job,
                    JobState.FAILED,
                    message="Exceeded retries",
                    error=job.error_message,
                )
                return
            job.retries += 1
            db.add(job)
            db.commit()
            db.refresh(job)
            self._transition_or_log(db, service, job, JobState.REFRESHING_WEBDAV, message="Retrying WebDAV visibility")
            return

        if state == JobState.WEBDAV_VISIBLE:
            self._transition_or_log(db, service, job, JobState.CREATING_SYMLINKS, message="Creating symlink tree")
            return

        if state == JobState.CREATING_SYMLINKS:
            if not job.torbox_remote_path:
                self._transition_or_log(
                    db,
                    service,
                    job,
                    JobState.FAILED,
                    message="No remote path",
                    error="missing remote path",
                )
                return
            exported = self._symlink_manager.create_job_symlinks(job.torbox_remote_path, job.info_hash, job.category)
            job.exported_path = exported
            job.save_path = exported
            db.add(job)
            db.commit()
            db.refresh(job)
            self._transition_or_log(db, service, job, JobState.READY_FOR_IMPORT, message="Ready for Sonarr import")

    def active_jobs_count(self) -> int:
        db: Session = self._db_factory()
        try:
            service = JobService(db)
            return len(service.list_active_jobs())
        finally:
            db.close()

    def stop(self) -> None:
        self._running = False
