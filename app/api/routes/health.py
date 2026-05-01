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
    runtime = request.app.state.runtime
    report = await build_health(
        db=db,
        mount_manager=runtime.mount_manager,
        provider=runtime.provider,
        worker_health=WorkerHealth(
            running=runtime.worker.is_running,
            active_jobs=runtime.worker.active_jobs_count(),
        ),
    )
    return JSONResponse(report)


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request, db: Session = Depends(db_session)) -> HTMLResponse:
    DashboardAuth.require_session(request)
    runtime = request.app.state.runtime
    report = await build_health(
        db=db,
        mount_manager=runtime.mount_manager,
        provider=runtime.provider,
        worker_health=WorkerHealth(
            running=runtime.worker.is_running,
            active_jobs=runtime.worker.active_jobs_count(),
        ),
    )
    csrf = DashboardAuth.get_csrf_token(request)
    return templates.TemplateResponse(
        request,
        "health.html",
        {"title": "Health", "health": report, "csrf_token": csrf},
    )
