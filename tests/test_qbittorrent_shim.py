from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.qbittorrent import router
from app.core.config import Settings, get_settings


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
