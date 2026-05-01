from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.enums import JobState
from app.models.job import JobEvent
from app.services.job_service import JobService
from app.services.provider.base import ProviderStatus, ProviderSubmission
from app.services.worker import JobWorker


class _DummyProvider:
    async def submit_magnet(self, magnet_uri: str) -> ProviderSubmission:
        return ProviderSubmission(provider_job_id="dummy", display_name="dummy")

    async def submit_torrent_bytes(self, filename: str, data: bytes) -> ProviderSubmission:
        return ProviderSubmission(provider_job_id="dummy", display_name=filename)

    async def get_status(self, provider_job_id: str) -> ProviderStatus:
        return ProviderStatus(
            provider_job_id=provider_job_id,
            status="queued",
            progress=0.0,
            remote_path=None,
            error=None,
        )

    async def healthcheck(self) -> tuple[bool, str]:
        return True, "ok"


class _ReadyProvider:
    async def submit_magnet(self, magnet_uri: str) -> ProviderSubmission:
        return ProviderSubmission(provider_job_id="dummy", display_name="dummy")

    async def submit_torrent_bytes(self, filename: str, data: bytes) -> ProviderSubmission:
        return ProviderSubmission(provider_job_id="dummy", display_name=filename)

    async def get_status(self, provider_job_id: str) -> ProviderStatus:
        return ProviderStatus(
            provider_job_id=provider_job_id,
            status="completed",
            progress=1.0,
            remote_path="/links/test.mkv",
            error=None,
        )

    async def healthcheck(self) -> tuple[bool, str]:
        return True, "ok"


class _DummyMountManager:
    async def ensure_remote_path_visible(self, remote_path: str) -> tuple[bool, str]:
        return False, "not-used"


class _SlowMountManager:
    async def ensure_remote_path_visible(self, remote_path: str) -> tuple[bool, str]:
        await asyncio.sleep(0.01)
        return False, "slow-not-visible"


class _DummySymlinkManager:
    def create_job_symlinks(self, remote_rel_path: str, job_id: str, category: str) -> str:
        return "/tmp/not-used"


@pytest.mark.asyncio
async def test_waiting_for_torbox_times_out_to_needs_attention(db_session: Session) -> None:
    service = JobService(db_session)
    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:abc",
        name="test",
        category="sonarr",
        save_path="/links",
    )
    service.transition(job, JobState.VALIDATING, message="ok")
    job.torbox_job_id = "provider-1"
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    service.transition(job, JobState.SUBMITTED_TO_TORBOX, message="ok")
    service.transition(job, JobState.WAITING_FOR_TORBOX, message="ok")

    # Simulate that the job entered WAITING_FOR_TORBOX long ago.
    waiting_event = db_session.scalar(
        select(JobEvent)
        .where(JobEvent.job_id == job.id, JobEvent.state == JobState.WAITING_FOR_TORBOX.value)
        .order_by(JobEvent.created_at.desc())
    )
    assert waiting_event is not None
    waiting_event.created_at = dt.datetime.utcnow() - dt.timedelta(seconds=7200)
    db_session.add(waiting_event)
    db_session.commit()
    db_session.refresh(job)

    worker = JobWorker(
        db_factory=lambda: db_session,
        settings=Settings(provider_wait_timeout_seconds=60),
        provider=_DummyProvider(),
        mount_manager=_DummyMountManager(),
        symlink_manager=_DummySymlinkManager(),
    )

    await worker._process_job(db_session, service, job)

    db_session.refresh(job)
    assert job.state == JobState.NEEDS_ATTENTION.value
    assert job.error_message is not None
    assert "Provider not ready within timeout" in job.error_message


@pytest.mark.asyncio
async def test_waiting_for_torbox_stays_waiting_before_timeout(db_session: Session) -> None:
    service = JobService(db_session)
    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:def",
        name="test2",
        category="sonarr",
        save_path="/links",
    )
    service.transition(job, JobState.VALIDATING, message="ok")
    job.torbox_job_id = "provider-2"
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    service.transition(job, JobState.SUBMITTED_TO_TORBOX, message="ok")
    service.transition(job, JobState.WAITING_FOR_TORBOX, message="ok")

    worker = JobWorker(
        db_factory=lambda: db_session,
        settings=Settings(provider_wait_timeout_seconds=7200),
        provider=_DummyProvider(),
        mount_manager=_DummyMountManager(),
        symlink_manager=_DummySymlinkManager(),
    )

    await worker._process_job(db_session, service, job)

    db_session.refresh(job)
    assert job.state == JobState.WAITING_FOR_TORBOX.value


@pytest.mark.asyncio
async def test_provider_ready_resets_retries_before_webdav_retry_budget(db_session: Session) -> None:
    service = JobService(db_session)
    settings = Settings(max_submit_retries=3)
    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:ghi",
        name="test3",
        category="sonarr",
        save_path="/links",
    )
    service.transition(job, JobState.VALIDATING, message="ok")
    job.torbox_job_id = "provider-3"
    job.retries = settings.max_submit_retries
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    service.transition(job, JobState.SUBMITTED_TO_TORBOX, message="ok")
    service.transition(job, JobState.WAITING_FOR_TORBOX, message="ok")

    worker = JobWorker(
        db_factory=lambda: db_session,
        settings=settings,
        provider=_ReadyProvider(),
        mount_manager=_DummyMountManager(),
        symlink_manager=_DummySymlinkManager(),
    )

    await worker._process_job(db_session, service, job)
    db_session.refresh(job)
    assert job.state == JobState.TORBOX_READY.value
    assert job.retries == 0

    await worker._process_job(db_session, service, job)
    db_session.refresh(job)
    assert job.state == JobState.REFRESHING_WEBDAV.value

    await worker._process_job(db_session, service, job)
    db_session.refresh(job)
    assert job.state == JobState.NEEDS_ATTENTION.value

    await worker._process_job(db_session, service, job)
    db_session.refresh(job)
    assert job.state == JobState.REFRESHING_WEBDAV.value
    assert job.retries == 1


@pytest.mark.asyncio
async def test_ready_for_import_auto_completes_when_staging_consumed(db_session: Session, tmp_path: Path) -> None:
    service = JobService(db_session)
    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:ready1",
        name="ready-test-1",
        category="sonarr",
        save_path="/links",
    )
    service.transition(job, JobState.VALIDATING, message="ok")
    service.transition(job, JobState.SUBMITTED_TO_TORBOX, message="ok")
    service.transition(job, JobState.WAITING_FOR_TORBOX, message="ok")
    service.transition(job, JobState.TORBOX_READY, message="ok")
    service.transition(job, JobState.REFRESHING_WEBDAV, message="ok")
    service.transition(job, JobState.WEBDAV_VISIBLE, message="ok")
    service.transition(job, JobState.CREATING_SYMLINKS, message="ok")

    # Simulate staging path removed by post-import cleanup.
    job.exported_path = str(tmp_path / "missing-staging-path")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    service.transition(job, JobState.READY_FOR_IMPORT, message="ready")

    worker = JobWorker(
        db_factory=lambda: db_session,
        settings=Settings(ready_for_import_autocomplete_seconds=300),
        provider=_DummyProvider(),
        mount_manager=_DummyMountManager(),
        symlink_manager=_DummySymlinkManager(),
    )

    await worker._process_job(db_session, service, job)
    db_session.refresh(job)
    assert job.state == JobState.IMPORTED_OPTIONAL_DETECTED.value


@pytest.mark.asyncio
async def test_ready_for_import_auto_completes_after_grace_period(db_session: Session, tmp_path: Path) -> None:
    service = JobService(db_session)
    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:ready2",
        name="ready-test-2",
        category="sonarr",
        save_path="/links",
    )
    service.transition(job, JobState.VALIDATING, message="ok")
    service.transition(job, JobState.SUBMITTED_TO_TORBOX, message="ok")
    service.transition(job, JobState.WAITING_FOR_TORBOX, message="ok")
    service.transition(job, JobState.TORBOX_READY, message="ok")
    service.transition(job, JobState.REFRESHING_WEBDAV, message="ok")
    service.transition(job, JobState.WEBDAV_VISIBLE, message="ok")
    service.transition(job, JobState.CREATING_SYMLINKS, message="ok")

    # Keep at least one staged symlink-like file so only age-based completion applies.
    staged = tmp_path / "staged"
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "file.txt").write_text("x")
    job.exported_path = str(staged)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    service.transition(job, JobState.READY_FOR_IMPORT, message="ready")

    ready_event = db_session.scalar(
        select(JobEvent)
        .where(JobEvent.job_id == job.id, JobEvent.state == JobState.READY_FOR_IMPORT.value)
        .order_by(JobEvent.created_at.desc())
    )
    assert ready_event is not None
    ready_event.created_at = dt.datetime.utcnow() - dt.timedelta(seconds=600)
    db_session.add(ready_event)
    db_session.commit()

    worker = JobWorker(
        db_factory=lambda: db_session,
        settings=Settings(ready_for_import_autocomplete_seconds=60),
        provider=_DummyProvider(),
        mount_manager=_DummyMountManager(),
        symlink_manager=_DummySymlinkManager(),
    )

    await worker._process_job(db_session, service, job)
    db_session.refresh(job)
    assert job.state == JobState.IMPORTED_OPTIONAL_DETECTED.value


@pytest.mark.asyncio
async def test_tick_prioritizes_new_jobs_over_refreshing_webdav(db_session: Session) -> None:
    service = JobService(db_session)

    blocked_job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:blocked",
        name="blocked",
        category="sonarr",
        save_path="/links",
    )
    service.transition(blocked_job, JobState.VALIDATING, message="ok")
    service.transition(blocked_job, JobState.SUBMITTED_TO_TORBOX, message="ok")
    service.transition(blocked_job, JobState.WAITING_FOR_TORBOX, message="ok")
    service.transition(blocked_job, JobState.TORBOX_READY, message="ok")
    blocked_job.torbox_remote_path = "/missing/file.mkv"
    db_session.add(blocked_job)
    db_session.commit()
    db_session.refresh(blocked_job)
    service.transition(blocked_job, JobState.REFRESHING_WEBDAV, message="refreshing")

    new_job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:newjob",
        name="new",
        category="sonarr",
        save_path="/links",
    )

    worker = JobWorker(
        db_factory=lambda: db_session,
        settings=Settings(),
        provider=_DummyProvider(),
        mount_manager=_SlowMountManager(),
        symlink_manager=_DummySymlinkManager(),
    )

    await worker._tick(db_session)

    db_session.refresh(new_job)
    assert new_job.state == JobState.VALIDATING.value
