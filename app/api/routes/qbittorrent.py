"""qBittorrent compatibility shim routes for Sonarr.

These routes intentionally mimic a common subset of qBittorrent Web API v2
used by Sonarr integrations.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse, PlainTextResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.config import Settings, get_settings
from app.models.enums import JobState
from app.models.job import Job
from app.schemas.qbittorrent import QBittorrentInfoItem
from app.services.job_service import JobService, derive_display_name

router = APIRouter(prefix="/api/v2", tags=["qbittorrent-shim"])


def _sid_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key=settings.secret_key, salt="cloudarr-qbit-sid")


def _issue_sid(settings: Settings) -> str:
    serializer = _sid_serializer(settings)
    return str(serializer.dumps({"kind": "qbit-auth"}))


def _verify_sid(token: str, settings: Settings) -> bool:
    serializer = _sid_serializer(settings)
    try:
        payload = serializer.loads(token, max_age=60 * 60 * 24 * 30)
    except (BadSignature, SignatureExpired):
        return False
    return isinstance(payload, dict) and payload.get("kind") == "qbit-auth"


def _is_authenticated(request: Request, settings: Settings) -> bool:
    # qBittorrent compatibility shim: cookie-based auth behavior.
    if not settings.qbit_require_auth:
        return True
    sid = request.cookies.get("SID")
    if not sid:
        return False
    return _verify_sid(sid, settings)


def _require_auth(request: Request, settings: Settings) -> Response | None:
    if not _is_authenticated(request, settings):
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    return None


def _map_state(job_state: JobState) -> str:
    # qBittorrent state terms expected by Sonarr.
    if job_state == JobState.READY_FOR_IMPORT:
        # Completed-and-seeding state; Sonarr treats this as importable/completed.
        return "pausedUP"
    if job_state in {JobState.FAILED, JobState.NEEDS_ATTENTION}:
        return "error"
    if job_state in {JobState.RECEIVED_FROM_SONARR, JobState.VALIDATING, JobState.SUBMITTED_TO_TORBOX}:
        return "metaDL"
    return "downloading"


def _to_info_items(jobs: Iterable[Job]) -> list[QBittorrentInfoItem]:
    items: list[QBittorrentInfoItem] = []
    for job in jobs:
        state = JobState(job.state)
        # Some Sonarr versions submit "." as savepath. Keep output paths usable
        # by preferring exported_path once available and avoiding "." in responses.
        save_path = (job.save_path or "").strip()
        if job.exported_path:
            save_path = job.exported_path
        if save_path in {"", "."}:
            save_path = f"/{job.category}/{job.info_hash}"
        items.append(
            QBittorrentInfoItem(
                hash=job.info_hash,
                name=job.torrent_name or job.sonarr_title or job.info_hash,
                progress=job.progress,
                state=_map_state(state),
                category=job.category,
                save_path=save_path,
                completed=int(job.progress * 1000),
                size=1000,
                amount_left=max(0, int((1 - job.progress) * 1000)),
            )
        )
    return items


@router.post("/auth/login")
async def auth_login(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
    settings: Settings = Depends(get_settings),
) -> Response:
    # qBittorrent compatibility shim endpoint.
    if not settings.qbit_require_auth:
        return PlainTextResponse("Ok.")

    if username == settings.qbit_username and password == settings.qbit_password:
        response = PlainTextResponse("Ok.")
        response.set_cookie(
            key="SID",
            value=_issue_sid(settings),
            httponly=True,
            samesite="lax",
            secure=settings.env == "production",
        )
        return response
    return PlainTextResponse("Fails.", status_code=status.HTTP_403_FORBIDDEN)


@router.post("/auth/logout")
async def auth_logout() -> Response:
    response = PlainTextResponse("Ok.")
    response.delete_cookie("SID")
    return response


@router.get("/app/version")
async def app_version() -> Response:
    # qBittorrent compatibility shim endpoint.
    return PlainTextResponse("4.6.5")


@router.get("/app/webapiVersion")
async def webapi_version() -> Response:
    # qBittorrent compatibility shim endpoint.
    return PlainTextResponse("2.8.3")


@router.get("/app/preferences")
async def app_preferences(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Response:
    # qBittorrent compatibility shim endpoint required by Sonarr test connection.
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error

    return JSONResponse(
        {
            "save_path": f"{settings.symlink_staging_root}/{settings.default_category}",
            "temp_path_enabled": False,
            "temp_path": "",
            "create_subfolder_enabled": False,
            "start_paused_enabled": False,
            "auto_tmm_enabled": False,
            "incomplete_files_ext": False,
            "preallocate_all": False,
            "queueing_enabled": False,
            "max_active_downloads": -1,
            "max_active_torrents": -1,
            "max_active_uploads": -1,
            "use_https": False,
            "web_ui_port": 8080,
        }
    )


@router.post("/torrents/add")
async def torrents_add(
    request: Request,
    urls: str = Form(default=""),
    category: str = Form(default=""),
    savepath: str = Form(default=""),
    torrents: list[UploadFile] | None = File(default=None),
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    # qBittorrent compatibility shim endpoint used by Sonarr for adds.
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error

    service = JobService(db)
    selected_category = category or settings.default_category
    requested_save_path = savepath.strip()
    selected_save_path = (
        requested_save_path if requested_save_path and requested_save_path != "." else f"{settings.symlink_staging_root}/{selected_category}"
    )

    magnet = urls.strip() or None
    if magnet:
        service.create_received_job(
            magnet_uri=magnet,
            name=derive_display_name(magnet, magnet[:120]),
            category=selected_category,
            save_path=selected_save_path,
        )
        return PlainTextResponse("Ok.")

    if torrents:
        cache_dir = Path(settings.torrent_cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        for item in torrents:
            body = await item.read()
            filename = item.filename or "uploaded.torrent"
            cache_file = cache_dir / f"{uuid.uuid4()}-{filename}"
            cache_file.write_bytes(body)
            service.create_received_job(
                magnet_uri=None,
                torrent_file_path=str(cache_file),
                name=filename,
                category=selected_category,
                save_path=selected_save_path,
            )
        return PlainTextResponse("Ok.")

    return PlainTextResponse("No URL has been given", status_code=status.HTTP_400_BAD_REQUEST)


@router.get("/torrents/info")
async def torrents_info(
    request: Request,
    hashes: str = "",
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error

    service = JobService(db)
    jobs = service.list_jobs()
    if hashes and hashes != "all":
        wanted = {value.strip() for value in hashes.split("|") if value.strip()}
        jobs = [job for job in jobs if job.info_hash in wanted]
    return JSONResponse([item.model_dump() for item in _to_info_items(jobs)])


@router.get("/torrents/files")
async def torrents_files(
    request: Request,
    hash: str,
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """qBittorrent compatibility shim endpoint used by Sonarr import handling."""
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error

    service = JobService(db)
    job = service.get_by_hash(hash)
    if not job:
        return JSONResponse([])

    remote_name = (job.torbox_remote_path or "").lstrip("/")
    if not remote_name:
        fallback_name = (job.torrent_name or job.sonarr_title or job.info_hash).strip()
        remote_name = f"{fallback_name}.mkv"
    if "/" not in remote_name:
        remote_name = f"torrents/{remote_name}"

    progress = 1.0 if JobState(job.state) == JobState.READY_FOR_IMPORT else max(0.0, min(1.0, job.progress))
    return JSONResponse(
        [
            {
                "index": 0,
                "name": remote_name,
                "size": 1000,
                "progress": progress,
                "priority": 1,
                "is_seed": False,
                "piece_range": [0, 0],
                "availability": progress,
            }
        ]
    )


@router.get("/torrents/categories")
async def torrents_categories(
    request: Request,
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    # qBittorrent compatibility shim endpoint used by Sonarr category validation.
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error

    service = JobService(db)
    categories: dict[str, dict[str, str]] = {
        settings.default_category: {
            "name": settings.default_category,
            "savePath": f"{settings.symlink_staging_root}/{settings.default_category}",
        }
    }

    for job in service.list_jobs():
        categories[job.category] = {
            "name": job.category,
            "savePath": f"{settings.symlink_staging_root}/{job.category}",
        }
    return JSONResponse(categories)


@router.post("/torrents/createCategory")
async def torrents_create_category(
    request: Request,
    category: str = Form(default=""),
    savePath: str = Form(default=""),
    settings: Settings = Depends(get_settings),
) -> Response:
    # qBittorrent compatibility shim endpoint. Category persistence is not required
    # because Sonarr always sends category with add requests and Cloudarr stores it per job.
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error
    _ = (category, savePath)
    return PlainTextResponse("Ok.")


@router.post("/torrents/editCategory")
async def torrents_edit_category(
    request: Request,
    category: str = Form(default=""),
    savePath: str = Form(default=""),
    settings: Settings = Depends(get_settings),
) -> Response:
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error
    _ = (category, savePath)
    return PlainTextResponse("Ok.")


@router.post("/torrents/removeCategories")
async def torrents_remove_categories(
    request: Request,
    categories: str = Form(default=""),
    settings: Settings = Depends(get_settings),
) -> Response:
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error
    _ = categories
    return PlainTextResponse("Ok.")


@router.get("/torrents/properties")
async def torrent_properties(
    request: Request,
    hash: str,
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error

    service = JobService(db)
    job = service.get_by_hash(hash)
    if not job:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    return JSONResponse(
        {
            "save_path": (job.exported_path or job.save_path or "").strip() or f"/{job.category}/{job.info_hash}",
            "comment": "Cloudarr/TorBox",
            "total_size": 1000,
            "progress": job.progress,
            "addition_date": int(job.created_at.timestamp()),
        }
    )


@router.post("/torrents/delete")
async def torrents_delete(
    request: Request,
    hashes: str = Form(default=""),
    hash_single: str = Form(default="", alias="hash"),
    deleteFiles: str = Form(default="false"),  # noqa: N803
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """qBittorrent compatibility shim: Sonarr calls this after import to remove the torrent."""
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error

    form = await request.form()
    hash_values: list[str] = []
    if hashes.strip():
        hash_values.extend(h.strip() for h in hashes.split("|") if h.strip())
    if hash_single.strip():
        hash_values.append(hash_single.strip())
    hash_values.extend(value.strip() for value in form.getlist("hashes[]") if str(value).strip())
    hash_values.extend(value.strip() for value in form.getlist("hashes[0]") if str(value).strip())

    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered_hashes = [h for h in hash_values if not (h in seen or seen.add(h))]

    service = JobService(db)
    for hash_str in ordered_hashes:
        job = service.get_by_hash(hash_str)
        if job and JobState(job.state) == JobState.READY_FOR_IMPORT:
            service.transition(job, JobState.IMPORTED_OPTIONAL_DETECTED, message="Imported by Sonarr")
    return PlainTextResponse("Ok.")


@router.get("/sync/maindata")
async def sync_maindata(
    request: Request,
    rid: int = 0,
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    auth_error = _require_auth(request, settings)
    if auth_error:
        return auth_error

    service = JobService(db)
    torrents = {}
    for item in _to_info_items(service.list_jobs()):
        torrents[item.hash] = item.model_dump()
    return JSONResponse({"rid": rid + 1, "full_update": True, "torrents": torrents})
