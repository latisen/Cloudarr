"""Health endpoints for API and dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.security import DashboardAuth
from app.services.health import WorkerHealth, build_health

router = APIRouter(tags=["health"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/api/health")
async def api_health(request: Request, db: Session = Depends(db_session)) -> JSONResponse:
    import subprocess
    runtime = request.app.state.runtime
    
    # Check if worker is actually running in systemd (more reliable than in-process flag)
    worker_running = runtime.worker.is_running
    try:
        result = subprocess.run(
            "systemctl is-active cloudarr-worker.service",
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        worker_running = result.returncode == 0
    except Exception:  # noqa: BLE001
        pass  # Fall back to in-process flag
    
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
    import subprocess
    DashboardAuth.require_session(request)
    runtime = request.app.state.runtime
    
    # Check if worker is actually running in systemd (more reliable than in-process flag)
    worker_running = runtime.worker.is_running
    try:
        result = subprocess.run(
            "systemctl is-active cloudarr-worker.service",
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        worker_running = result.returncode == 0
    except Exception:  # noqa: BLE001
        pass  # Fall back to in-process flag
    
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
