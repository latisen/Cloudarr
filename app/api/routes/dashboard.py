"""Admin dashboard routes with session auth."""

from __future__ import annotations

import subprocess
from urllib.parse import quote_plus

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


def _restart_command_defaults() -> dict[str, str]:
    return {
        "sonarr": "sudo systemctl restart sonarr.service",
        "radarr": "sudo systemctl restart radarr.service",
        "cloudarr_api": "sudo systemctl restart cloudarr-api.service",
        "cloudarr_worker": "sudo systemctl restart cloudarr-worker.service",
        "webdav_mount": "sudo systemctl restart torbox-rclone-mount.service",
    }


def _service_status_command(unit_name: str) -> str:
    return f"systemctl is-active {unit_name} || true"


def _service_statuses(store: SettingsStore) -> dict[str, str]:
    units = {
        "sonarr": store.get("sonarr_service_name", "sonarr.service") or "sonarr.service",
        "radarr": store.get("radarr_service_name", "radarr.service") or "radarr.service",
        "cloudarr_api": store.get("cloudarr_api_service_name", "cloudarr-api.service") or "cloudarr-api.service",
        "cloudarr_worker": store.get("cloudarr_worker_service_name", "cloudarr-worker.service") or "cloudarr-worker.service",
        "webdav_mount": store.get("webdav_mount_service_name", "torbox-rclone-mount.service")
        or "torbox-rclone-mount.service",
    }
    statuses: dict[str, str] = {}
    for key, unit in units.items():
        try:
            result = subprocess.run(
                _service_status_command(unit),
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
            value = (result.stdout or result.stderr).strip() or "unknown"
            statuses[key] = value
        except Exception:  # noqa: BLE001
            statuses[key] = "unavailable"
    return statuses


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
    restart_defaults = _restart_command_defaults()

    service_result = request.query_params.get("service_result") or ""
    service_target = request.query_params.get("service_target") or ""
    service_detail = request.query_params.get("service_detail") or ""
    saved = request.query_params.get("saved") == "1"

    context = {
        "saved": saved,
        "service_result": service_result,
        "service_target": service_target,
        "service_detail": service_detail,
        "provider_name": store.get("provider_name", settings.provider_name) or "",
        "default_category": store.get("default_category", settings.default_category) or "",
        "realdebrid_api_base": store.get("realdebrid_api_base", settings.realdebrid_api_base) or "",
        "realdebrid_api_token": "(stored)" if store.get_secret("realdebrid_api_token") else "",
        "torbox_api_base": store.get("torbox_api_base", settings.torbox_api_base) or "",
        "torbox_api_key": "(stored)" if store.get_secret("torbox_api_key") else "",
        "torbox_torrents_path": store.get("torbox_torrents_path", settings.torbox_torrents_path) or "",
        "torbox_mylist_path": store.get("torbox_mylist_path", settings.torbox_mylist_path) or "",
        "torbox_health_path": store.get("torbox_health_path", settings.torbox_health_path) or "",
        "webdav_url": store.get("webdav_url", settings.webdav_url) or "",
        "webdav_username": store.get("webdav_username", settings.webdav_username) or "",
        "webdav_password": "(stored)" if store.get_secret("webdav_password") else "",
        "webdav_mount_path": store.get("webdav_mount_path", settings.webdav_mount_path) or "",
        "webdav_remote_root": store.get("webdav_remote_root", settings.webdav_remote_root) or "",
        "symlink_staging_root": store.get("symlink_staging_root", settings.symlink_staging_root) or "",
        "qbit_username": store.get("qbit_username", settings.qbit_username) or "",
        "qbit_password": "(stored)" if store.get_secret("qbit_password") else "",
        "qbit_require_auth": store.get("qbit_require_auth", str(settings.qbit_require_auth).lower()) or "",
        "admin_user": store.get("admin_user", settings.admin_user) or "",
        "admin_password": "(stored)" if store.get_secret("admin_password") else "",
        "webdav_refresh_command": store.get("webdav_refresh_command", settings.webdav_refresh_command) or "",
        "webdav_remount_command": store.get("webdav_remount_command", settings.webdav_remount_command) or "",
        "poll_interval_seconds": store.get("poll_interval_seconds", str(settings.poll_interval_seconds)) or "",
        "log_level": store.get("log_level", settings.log_level) or "",
        "service_statuses": _service_statuses(store),
        "sonarr_service_name": store.get("sonarr_service_name", "sonarr.service") or "sonarr.service",
        "radarr_service_name": store.get("radarr_service_name", "radarr.service") or "radarr.service",
        "cloudarr_api_service_name": store.get("cloudarr_api_service_name", "cloudarr-api.service") or "cloudarr-api.service",
        "cloudarr_worker_service_name": store.get("cloudarr_worker_service_name", "cloudarr-worker.service")
        or "cloudarr-worker.service",
        "webdav_mount_service_name": store.get("webdav_mount_service_name", "torbox-rclone-mount.service")
        or "torbox-rclone-mount.service",
        "service_restart_commands": {
            "sonarr": store.get("sonarr_restart_command", restart_defaults["sonarr"]) or restart_defaults["sonarr"],
            "radarr": store.get("radarr_restart_command", restart_defaults["radarr"]) or restart_defaults["radarr"],
            "cloudarr_api": (
                store.get("cloudarr_api_restart_command", restart_defaults["cloudarr_api"]) or restart_defaults["cloudarr_api"]
            ),
            "cloudarr_worker": (
                store.get("cloudarr_worker_restart_command", restart_defaults["cloudarr_worker"])
                or restart_defaults["cloudarr_worker"]
            ),
            "webdav_mount": (
                store.get("webdav_mount_restart_command", restart_defaults["webdav_mount"])
                or restart_defaults["webdav_mount"]
            ),
        },
    }

    return templates.TemplateResponse(
        request,
        "settings.html",
        {"title": "Settings", "csrf_token": csrf, "settings": context},
    )


@router.post("/settings")
async def settings_save(
    request: Request,
    provider_name: str = Form(...),
    default_category: str = Form(...),
    realdebrid_api_base: str = Form(...),
    realdebrid_api_token: str = Form(default=""),
    torbox_api_base: str = Form(...),
    torbox_api_key: str = Form(default=""),
    torbox_torrents_path: str = Form(...),
    torbox_mylist_path: str = Form(...),
    torbox_health_path: str = Form(...),
    webdav_url: str = Form(default=""),
    webdav_username: str = Form(default=""),
    webdav_password: str = Form(default=""),
    webdav_mount_path: str = Form(...),
    webdav_remote_root: str = Form(default=""),
    symlink_staging_root: str = Form(...),
    qbit_username: str = Form(...),
    qbit_password: str = Form(default=""),
    qbit_require_auth: str = Form(...),
    admin_user: str = Form(...),
    admin_password: str = Form(default=""),
    webdav_refresh_command: str = Form(...),
    webdav_remount_command: str = Form(...),
    poll_interval_seconds: str = Form(...),
    log_level: str = Form(...),
    sonarr_service_name: str = Form(default="sonarr.service"),
    radarr_service_name: str = Form(default="radarr.service"),
    cloudarr_api_service_name: str = Form(default="cloudarr-api.service"),
    cloudarr_worker_service_name: str = Form(default="cloudarr-worker.service"),
    webdav_mount_service_name: str = Form(default="torbox-rclone-mount.service"),
    sonarr_restart_command: str = Form(default=""),
    radarr_restart_command: str = Form(default=""),
    cloudarr_api_restart_command: str = Form(default=""),
    cloudarr_worker_restart_command: str = Form(default=""),
    webdav_mount_restart_command: str = Form(default=""),
    csrf_token: str = Form(...),
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    _require_dashboard_auth(request)
    DashboardAuth.validate_csrf(request, csrf_token)
    store = SettingsStore(db, settings.secret_key)

    if realdebrid_api_token.strip():
        store.set_secret("realdebrid_api_token", realdebrid_api_token.strip())
    if torbox_api_key.strip():
        store.set_secret("torbox_api_key", torbox_api_key.strip())
    if webdav_password.strip():
        store.set_secret("webdav_password", webdav_password.strip())
    if qbit_password.strip():
        store.set_secret("qbit_password", qbit_password.strip())
    if admin_password.strip():
        store.set_secret("admin_password", admin_password.strip())

    store.set("provider_name", provider_name.strip().lower())
    store.set("default_category", default_category.strip())
    store.set("realdebrid_api_base", realdebrid_api_base.strip())
    store.set("torbox_api_base", torbox_api_base.strip())
    store.set("torbox_torrents_path", torbox_torrents_path.strip())
    store.set("torbox_mylist_path", torbox_mylist_path.strip())
    store.set("torbox_health_path", torbox_health_path.strip())
    store.set("webdav_url", webdav_url.strip())
    store.set("webdav_username", webdav_username.strip())
    store.set("webdav_mount_path", webdav_mount_path.strip())
    store.set("webdav_remote_root", webdav_remote_root.strip())
    store.set("symlink_staging_root", symlink_staging_root.strip())
    store.set("qbit_username", qbit_username.strip())
    store.set("qbit_require_auth", qbit_require_auth.strip().lower())
    store.set("admin_user", admin_user.strip())
    store.set("webdav_refresh_command", webdav_refresh_command.strip())
    store.set("webdav_remount_command", webdav_remount_command.strip())
    store.set("poll_interval_seconds", poll_interval_seconds.strip())
    store.set("log_level", log_level.strip().upper())
    store.set("sonarr_service_name", sonarr_service_name.strip())
    store.set("radarr_service_name", radarr_service_name.strip())
    store.set("cloudarr_api_service_name", cloudarr_api_service_name.strip())
    store.set("cloudarr_worker_service_name", cloudarr_worker_service_name.strip())
    store.set("webdav_mount_service_name", webdav_mount_service_name.strip())

    restart_defaults = _restart_command_defaults()
    store.set("sonarr_restart_command", sonarr_restart_command.strip() or restart_defaults["sonarr"])
    store.set("radarr_restart_command", radarr_restart_command.strip() or restart_defaults["radarr"])
    store.set(
        "cloudarr_api_restart_command",
        cloudarr_api_restart_command.strip() or restart_defaults["cloudarr_api"],
    )
    store.set(
        "cloudarr_worker_restart_command",
        cloudarr_worker_restart_command.strip() or restart_defaults["cloudarr_worker"],
    )
    store.set(
        "webdav_mount_restart_command",
        webdav_mount_restart_command.strip() or restart_defaults["webdav_mount"],
    )

    # Re-hydrate and rebuild runtime components so new settings apply immediately.
    runtime = request.app.state.runtime
    runtime.reload_from_db()

    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/jobs/retry")
async def retry_job(
    request: Request,
    job_id: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Reset a failed job to QUEUED state for retry."""
    _require_dashboard_auth(request)
    DashboardAuth.validate_csrf(request, csrf_token)

    try:
        stmt = select(JobEvent).where(JobEvent.id == job_id)
        job = db.scalars(stmt).first()
        if not job:
            return RedirectResponse(
                url="/jobs?error=Job+not+found",
                status_code=303,
            )
        from app.models.job import JobState

        if job.state in [JobState.COMPLETED.value, JobState.FAILED.value, JobState.NEEDS_ATTENTION.value]:
            job.state = JobState.QUEUED.value
            job.error_message = None
            job.retries = 0
            db.add(job)
            db.commit()
            return RedirectResponse(
                url="/jobs?retry_result=ok",
                status_code=303,
            )
        return RedirectResponse(
            url="/jobs?error=Can+only+retry+failed+or+completed+jobs",
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            url=f"/jobs?error={quote_plus(str(exc)[:80])}",
            status_code=303,
        )


@router.post("/settings/service-action")
async def service_action(
    request: Request,
    target: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    _require_dashboard_auth(request)
    DashboardAuth.validate_csrf(request, csrf_token)
    store = SettingsStore(db, settings.secret_key)

    command_key = {
        "sonarr": "sonarr_restart_command",
        "radarr": "radarr_restart_command",
        "cloudarr_api": "cloudarr_api_restart_command",
        "cloudarr_worker": "cloudarr_worker_restart_command",
        "webdav_mount": "webdav_mount_restart_command",
    }.get(target)
    if command_key is None:
        return RedirectResponse(url="/settings?service_result=error&service_target=invalid&service_detail=Unknown+service", status_code=303)

    command = store.get(command_key)
    if not command:
        command = _restart_command_defaults()[target]

    try:
        result = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode == 0:
            return RedirectResponse(
                url=f"/settings?service_result=ok&service_target={target}&service_detail=Restart+completed",
                status_code=303,
            )
        detail = quote_plus((result.stderr or result.stdout or "unknown failure").strip()[:160])
        return RedirectResponse(
            url=f"/settings?service_result=error&service_target={target}&service_detail={detail}",
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        detail = quote_plus(str(exc).strip()[:160])
        return RedirectResponse(
            url=f"/settings?service_result=error&service_target={target}&service_detail={detail}",
            status_code=303,
        )


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
