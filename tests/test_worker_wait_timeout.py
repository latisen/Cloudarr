from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.enums import JobState
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


class _DummyMountManager:
    async def ensure_remote_path_visible(self, remote_path: str) -> tuple[bool, str]:
        return False, "not-used"


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

    # Simulate that the job has been waiting for a long time already.
    job.updated_at = dt.datetime.utcnow() - dt.timedelta(seconds=7200)
    db_session.add(job)
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
