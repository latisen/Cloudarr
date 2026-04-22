"""Admin dashboard routes with session auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.config import Settings, get_settings
from app.core.security import DashboardAuth
from app.models.job import JobEvent
from app.services.job_service import JobService
from app.services.settings_store import SettingsStore

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def _require_dashboard_auth(request: Request) -> dict[str, str]:
    return DashboardAuth.require_session(request)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    csrf = DashboardAuth.get_csrf_token(request)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"csrf_token": csrf, "title": "Cloudarr Login"},
    )


@router.post("/login")
async def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    DashboardAuth.validate_csrf(request, csrf_token)
    if username == settings.admin_user and password == settings.admin_password:
        request.session["user"] = {"username": username}
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url="/login?error=1", status_code=303)


@router.post("/logout")
async def logout_action(request: Request, csrf_token: str = Form(...)) -> RedirectResponse:
    DashboardAuth.validate_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def jobs_page(request: Request, db: Session = Depends(db_session)) -> HTMLResponse:
    _require_dashboard_auth(request)
    csrf = DashboardAuth.get_csrf_token(request)
    service = JobService(db)
    jobs = service.list_jobs()
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {"jobs": jobs, "csrf_token": csrf, "title": "Jobs"},
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    _require_dashboard_auth(request)
    csrf = DashboardAuth.get_csrf_token(request)
    store = SettingsStore(db, settings.secret_key)

    context = {
        "torbox_api_key": "(stored)" if store.get_secret("torbox_api_key") else "",
        "webdav_url": store.get("webdav_url", settings.webdav_url) or "",
        "webdav_username": store.get("webdav_username", settings.webdav_username) or "",
        "webdav_password": "(stored)" if store.get_secret("webdav_password") else "",
        "webdav_mount_path": store.get("webdav_mount_path", settings.webdav_mount_path) or "",
        "symlink_staging_root": store.get("symlink_staging_root", settings.symlink_staging_root) or "",
        "qbit_username": store.get("qbit_username", settings.qbit_username) or "",
        "qbit_password": "(stored)" if store.get_secret("qbit_password") else "",
        "qbit_require_auth": store.get("qbit_require_auth", str(settings.qbit_require_auth).lower()) or "",
        "webdav_refresh_command": store.get("webdav_refresh_command", settings.webdav_refresh_command) or "",
        "webdav_remount_command": store.get("webdav_remount_command", settings.webdav_remount_command) or "",
        "poll_interval_seconds": store.get("poll_interval_seconds", str(settings.poll_interval_seconds)) or "",
        "log_level": store.get("log_level", settings.log_level) or "",
    }

    return templates.TemplateResponse(
        request,
        "settings.html",
        {"title": "Settings", "csrf_token": csrf, "settings": context},
    )


@router.post("/settings")
async def settings_save(
    request: Request,
    torbox_api_key: str = Form(default=""),
    webdav_url: str = Form(default=""),
    webdav_username: str = Form(default=""),
    webdav_password: str = Form(default=""),
    webdav_mount_path: str = Form(...),
    symlink_staging_root: str = Form(...),
    qbit_username: str = Form(...),
    qbit_password: str = Form(default=""),
    qbit_require_auth: str = Form(...),
    webdav_refresh_command: str = Form(...),
    webdav_remount_command: str = Form(...),
    poll_interval_seconds: str = Form(...),
    log_level: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    _require_dashboard_auth(request)
    DashboardAuth.validate_csrf(request, csrf_token)
    store = SettingsStore(db, settings.secret_key)

    if torbox_api_key.strip():
        store.set_secret("torbox_api_key", torbox_api_key.strip())
    if webdav_password.strip():
        store.set_secret("webdav_password", webdav_password.strip())
    if qbit_password.strip():
        store.set_secret("qbit_password", qbit_password.strip())

    store.set("webdav_url", webdav_url.strip())
    store.set("webdav_username", webdav_username.strip())
    store.set("webdav_mount_path", webdav_mount_path.strip())
    store.set("symlink_staging_root", symlink_staging_root.strip())
    store.set("qbit_username", qbit_username.strip())
    store.set("qbit_require_auth", qbit_require_auth.strip().lower())
    store.set("webdav_refresh_command", webdav_refresh_command.strip())
    store.set("webdav_remount_command", webdav_remount_command.strip())
    store.set("poll_interval_seconds", poll_interval_seconds.strip())
    store.set("log_level", log_level.strip().upper())

    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.get("/events", response_class=HTMLResponse)
async def events_page(request: Request, db: Session = Depends(db_session)) -> HTMLResponse:
    _require_dashboard_auth(request)
    csrf = DashboardAuth.get_csrf_token(request)
    events = list(db.scalars(select(JobEvent).order_by(JobEvent.id.desc()).limit(200)))
    return templates.TemplateResponse(
        request,
        "events.html",
        {"title": "Recent Events", "events": events, "csrf_token": csrf},
    )
