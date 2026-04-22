"""Health checks for DB, mount, provider, and worker state."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.mount_manager import WebDavMountManager
from app.services.provider.base import DebridProvider


@dataclass(slots=True)
class WorkerHealth:
    running: bool
    active_jobs: int


async def build_health(
    *,
    db: Session,
    mount_manager: WebDavMountManager,
    provider: DebridProvider,
    worker_health: WorkerHealth,
) -> dict[str, object]:
    """Construct a structured health report."""

    db_ok = True
    db_message = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_message = str(exc)

    mount_ok, mount_message = mount_manager.is_mount_available()
    provider_ok, provider_message = await provider.healthcheck()

    return {
        "database": {"ok": db_ok, "message": db_message},
        "mount": {"ok": mount_ok, "message": mount_message},
        "provider": {"ok": provider_ok, "message": provider_message},
        "worker": {
            "running": worker_health.running,
            "active_jobs": worker_health.active_jobs,
        },
        "last_successful_webdav_refresh": mount_manager.last_successful_refresh,
    }
