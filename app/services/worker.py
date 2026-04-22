"""Background worker for TorBox orchestration lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.enums import JobState
from app.models.job import Job
from app.services.job_service import JobService
from app.services.mount_manager import WebDavMountManager
from app.services.provider.base import DebridProvider
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
        while self._running:
            db: Session = self._db_factory()
            try:
                await self._tick(db)
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
                service.transition(
                    job,
                    JobState.FAILED,
                    message="Unhandled worker exception",
                    error=str(exc),
                )

    async def _process_job(self, db: Session, service: JobService, job: Job) -> None:
        state = JobState(job.state)

        if state == JobState.RECEIVED_FROM_SONARR:
            service.transition(job, JobState.VALIDATING, message="Validating job")
            return

        if state == JobState.VALIDATING:
            if job.magnet_uri:
                submission = await self._provider.submit_magnet(job.magnet_uri)
            elif job.torrent_file_path:
                payload_path = Path(job.torrent_file_path)
                if not payload_path.exists():
                    service.transition(
                        job,
                        JobState.FAILED,
                        message="Missing torrent payload",
                        error=f"Not found: {payload_path}",
                    )
                    return
                data = payload_path.read_bytes()
                submission = await self._provider.submit_torrent_bytes(payload_path.name, data)
            else:
                service.transition(job, JobState.FAILED, message="Missing input", error="No magnet or torrent file")
                return

            job.torbox_job_id = submission.provider_job_id
            job.torrent_name = submission.display_name or job.torrent_name
            db.add(job)
            db.commit()
            db.refresh(job)
            service.transition(job, JobState.SUBMITTED_TO_TORBOX, message="Submitted to TorBox")
            return

        if state == JobState.SUBMITTED_TO_TORBOX:
            service.transition(job, JobState.WAITING_FOR_TORBOX, message="Waiting for TorBox readiness")
            return

        if state == JobState.WAITING_FOR_TORBOX:
            if not job.torbox_job_id:
                service.transition(job, JobState.FAILED, message="Missing TorBox job id", error="No provider ID")
                return
            status = await self._provider.get_status(job.torbox_job_id)
            job.progress = status.progress
            if status.is_failed:
                service.transition(job, JobState.FAILED, message="TorBox failed", error=status.error or "unknown")
                return
            if status.is_ready:
                job.torbox_remote_path = status.remote_path
                db.add(job)
                db.commit()
                db.refresh(job)
                service.transition(job, JobState.TORBOX_READY, message="TorBox marked content ready")
            else:
                db.add(job)
                db.commit()
            return

        if state == JobState.TORBOX_READY:
            service.transition(job, JobState.REFRESHING_WEBDAV, message="Refreshing WebDAV view")
            return

        if state == JobState.REFRESHING_WEBDAV:
            if not job.torbox_remote_path:
                service.transition(job, JobState.FAILED, message="No remote path", error="torbox_remote_path missing")
                return
            visible, msg = await self._mount_manager.ensure_remote_path_visible(job.torbox_remote_path)
            if not visible:
                service.transition(job, JobState.NEEDS_ATTENTION, message="WebDAV path not visible", error=msg)
                return
            service.transition(job, JobState.WEBDAV_VISIBLE, message=msg)
            return

        if state == JobState.NEEDS_ATTENTION:
            if job.retries >= self._settings.max_submit_retries:
                service.transition(job, JobState.FAILED, message="Exceeded retries", error=job.error_message)
                return
            job.retries += 1
            db.add(job)
            db.commit()
            db.refresh(job)
            service.transition(job, JobState.REFRESHING_WEBDAV, message="Retrying WebDAV visibility")
            return

        if state == JobState.WEBDAV_VISIBLE:
            service.transition(job, JobState.CREATING_SYMLINKS, message="Creating symlink tree")
            return

        if state == JobState.CREATING_SYMLINKS:
            if not job.torbox_remote_path:
                service.transition(job, JobState.FAILED, message="No remote path", error="missing remote path")
                return
            exported = self._symlink_manager.create_job_symlinks(job.torbox_remote_path, job.info_hash, job.category)
            job.exported_path = exported
            job.save_path = exported
            db.add(job)
            db.commit()
            db.refresh(job)
            service.transition(job, JobState.READY_FOR_IMPORT, message="Ready for Sonarr import")

    def active_jobs_count(self) -> int:
        db: Session = self._db_factory()
        try:
            service = JobService(db)
            return len(service.list_active_jobs())
        finally:
            db.close()

    def stop(self) -> None:
        self._running = False
