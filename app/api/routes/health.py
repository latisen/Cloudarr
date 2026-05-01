"""Health endpoints for API and dashboard."""

from __future__ import annotations

import subprocess

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.security import DashboardAuth
from app.services.health import WorkerHealth, build_health

router = APIRouter(tags=["health"])
templates = Jinja2Templates(directory="app/templates")


def _is_worker_running_systemd() -> bool | None:
    try:
        result = subprocess.run(
            "systemctl is-active cloudarr-worker.service",
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return (result.stdout or "").strip() == "active"
    except Exception:  # noqa: BLE001
        return None


@router.get("/api/health")
async def api_health(request: Request, db: Session = Depends(db_session)) -> JSONResponse:
    runtime = request.app.state.runtime
    worker_running = _is_worker_running_systemd()
    if worker_running is None:
        worker_running = runtime.worker.is_running
    report = await build_health(
        db=db,
        mount_manager=runtime.mount_manager,
        provider=runtime.provider,
        worker_health=WorkerHealth(
            running=worker_running,
            active_jobs=runtime.worker.active_jobs_count(),
        ),
    )
    return JSONResponse(report)


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request, db: Session = Depends(db_session)) -> HTMLResponse:
    DashboardAuth.require_session(request)
    runtime = request.app.state.runtime
    worker_running = _is_worker_running_systemd()
    if worker_running is None:
        worker_running = runtime.worker.is_running
    report = await build_health(
        db=db,
        mount_manager=runtime.mount_manager,
        provider=runtime.provider,
        worker_health=WorkerHealth(
            running=worker_running,
            active_jobs=runtime.worker.active_jobs_count(),
        ),
    )
    csrf = DashboardAuth.get_csrf_token(request)
    return templates.TemplateResponse(
        request,
        "health.html",
        {"title": "Health", "health": report, "csrf_token": csrf},
    )
