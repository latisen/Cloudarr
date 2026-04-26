from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.qbittorrent import router
from app.core.config import Settings, get_settings
from app.models.enums import JobState
from app.services.job_service import JobService


def _app(db_session):
    app = FastAPI()
    app.include_router(router)

    from app.api import deps

    app.dependency_overrides[deps.db_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: Settings(qbit_require_auth=False)
    return app


def test_add_and_list_torrent(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)

    add = client.post(
        "/api/v2/torrents/add",
        data={"urls": "magnet:?xt=urn:btih:123", "category": "sonarr", "savepath": "/links"},
    )
    assert add.status_code == 200

    info = client.get("/api/v2/torrents/info")
    assert info.status_code == 200
    payload = info.json()
    assert len(payload) == 1
    assert payload[0]["category"] == "sonarr"


def test_add_and_list_torrent_uses_magnet_display_name(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)

    magnet = (
        "magnet:?xt=urn:btih:123"
        "&dn=Andor.S01E01.2160p.WEB-DL"
        "&tr=udp%3A%2F%2Ftracker.example%3A1337"
    )
    add = client.post(
        "/api/v2/torrents/add",
        data={"urls": magnet, "category": "sonarr", "savepath": "/links"},
    )
    assert add.status_code == 200

    info = client.get("/api/v2/torrents/info")
    assert info.status_code == 200
    payload = info.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "Andor.S01E01.2160p.WEB-DL"


def test_torrents_files_returns_file_info(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)

    add = client.post(
        "/api/v2/torrents/add",
        data={"urls": "magnet:?xt=urn:btih:123", "category": "sonarr", "savepath": "/links"},
    )
    assert add.status_code == 200

    info = client.get("/api/v2/torrents/info")
    item = info.json()[0]
    files = client.get(f"/api/v2/torrents/files?hash={item['hash']}")
    assert files.status_code == 200
    payload = files.json()
    assert len(payload) == 1
    assert payload[0]["name"]
    assert payload[0]["index"] == 0


def test_torrents_delete_transitions_ready_job(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)
    service = JobService(db_session)

    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:abc123",
        name="Andor.S02E03",
        category="sonarr",
        save_path="/links",
    )
    service.transition(job, JobState.VALIDATING, message="test")
    service.transition(job, JobState.SUBMITTED_TO_TORBOX, message="test")
    service.transition(job, JobState.WAITING_FOR_TORBOX, message="test")
    service.transition(job, JobState.TORBOX_READY, message="test")
    service.transition(job, JobState.REFRESHING_WEBDAV, message="test")
    service.transition(job, JobState.WEBDAV_VISIBLE, message="test")
    service.transition(job, JobState.CREATING_SYMLINKS, message="test")
    service.transition(job, JobState.READY_FOR_IMPORT, message="test")

    resp = client.post("/api/v2/torrents/delete", data={"hashes": job.info_hash, "deleteFiles": "false"})
    assert resp.status_code == 200

    updated = service.get_by_hash(job.info_hash)
    assert updated is not None
    assert updated.state == JobState.IMPORTED_OPTIONAL_DETECTED.value
