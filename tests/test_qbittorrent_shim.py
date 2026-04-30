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


def test_add_with_dot_savepath_uses_default_output_path(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)

    add = client.post(
        "/api/v2/torrents/add",
        data={"urls": "magnet:?xt=urn:btih:123dot", "category": "sonarr", "savepath": "."},
    )
    assert add.status_code == 200

    info = client.get("/api/v2/torrents/info")
    assert info.status_code == 200
    payload = info.json()
    assert len(payload) == 1
    assert payload[0]["save_path"] == "/srv/torbox-arr/links/sonarr"


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
    assert payload[0]["name"].startswith("torrents/")
    assert payload[0]["index"] == 0


def test_torrent_properties_prefers_exported_path(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)
    service = JobService(db_session)

    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:prop1",
        name="Andor.S02E07",
        category="sonarr",
        save_path=".",
    )
    job.exported_path = "/data/downloads/sonarr/prop1"
    job.save_path = "."
    db_session.add(job)
    db_session.commit()

    resp = client.get(f"/api/v2/torrents/properties?hash={job.info_hash}")
    assert resp.status_code == 200
    assert resp.json()["save_path"] == "/data/downloads/sonarr/prop1"


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


def test_torrents_info_reports_ready_jobs_as_paused_up(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)
    service = JobService(db_session)

    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:ready1",
        name="Andor.S02E04",
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

    info = client.get("/api/v2/torrents/info")
    assert info.status_code == 200
    payload = info.json()
    assert payload[0]["state"] == "pausedUP"


def test_torrents_delete_accepts_single_hash_field(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)
    service = JobService(db_session)

    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:abc456",
        name="Andor.S02E05",
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

    resp = client.post("/api/v2/torrents/delete", data={"hash": job.info_hash, "deleteFiles": "false"})
    assert resp.status_code == 200

    updated = service.get_by_hash(job.info_hash)
    assert updated is not None
    assert updated.state == JobState.IMPORTED_OPTIONAL_DETECTED.value


def test_torrents_delete_accepts_hashes_array_field(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)
    service = JobService(db_session)

    job = service.create_received_job(
        magnet_uri="magnet:?xt=urn:btih:abc789",
        name="Andor.S02E06",
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

    resp = client.post("/api/v2/torrents/delete", data={"hashes[]": job.info_hash, "deleteFiles": "false"})
    assert resp.status_code == 200

    updated = service.get_by_hash(job.info_hash)
    assert updated is not None
    assert updated.state == JobState.IMPORTED_OPTIONAL_DETECTED.value


def test_add_requeues_previously_terminal_job(db_session) -> None:
    app = _app(db_session)
    client = TestClient(app)
    service = JobService(db_session)

    magnet = "magnet:?xt=urn:btih:111"
    first = service.create_received_job(
        magnet_uri=magnet,
        name="Andor.S01E01",
        category="sonarr",
        save_path="/links",
    )
    service.transition(first, JobState.VALIDATING, message="test")
    service.transition(first, JobState.FAILED, message="test", error="boom")

    add = client.post(
        "/api/v2/torrents/add",
        data={"urls": magnet, "category": "sonarr", "savepath": "/links"},
    )
    assert add.status_code == 200

    updated = service.get_by_hash(first.info_hash)
    assert updated is not None
    assert updated.id == first.id
    assert updated.state == JobState.RECEIVED_FROM_SONARR.value
    assert updated.progress == 0.0
    assert updated.error_message is None


def test_auth_uses_signed_sid_cookie(db_session) -> None:
    app = FastAPI()
    app.include_router(router)
    from app.api import deps

    app.dependency_overrides[deps.db_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        qbit_require_auth=True,
        qbit_username="sonarr",
        qbit_password="secret",
        secret_key="test-secret",
    )
    client = TestClient(app)

    bad = client.get("/api/v2/torrents/info", cookies={"SID": "cloudarr-auth"})
    assert bad.status_code == 403

    login = client.post("/api/v2/auth/login", data={"username": "sonarr", "password": "secret"})
    assert login.status_code == 200
    sid = login.cookies.get("SID")
    assert sid

    ok = client.get("/api/v2/torrents/info", cookies={"SID": sid})
    assert ok.status_code == 200
