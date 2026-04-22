from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.enums import JobState
from app.services.job_service import JobService


def test_non_terminal_jobs_are_recovered(db_session: Session) -> None:
    service = JobService(db_session)
    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:abc",
        name="test",
        category="sonarr",
        save_path="/links",
    )
    service.transition(job, JobState.VALIDATING, message="ok")

    active = service.list_active_jobs()
    assert len(active) == 1
    assert active[0].id == job.id
