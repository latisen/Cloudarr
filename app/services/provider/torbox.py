"""TorBox provider implementation.

Assumptions:
- POST /api/v1/torrents accepts either magnet link payload or multipart torrent upload.
- GET /api/v1/torrents/{id} returns status/progress/webdav_path fields.

These are isolated behind the provider interface so endpoint mappings can be adjusted
without impacting qBittorrent compatibility logic.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.services.provider.base import DebridProvider, ProviderStatus, ProviderSubmission


class TorBoxProvider(DebridProvider):
    """TorBox API client wrapper."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.torbox_api_base.rstrip("/")
        self._api_key = settings.torbox_api_key
        self._timeout = httpx.Timeout(20.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    async def submit_magnet(self, magnet_uri: str) -> ProviderSubmission:
        payload = {"magnet": magnet_uri}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base}/api/v1/torrents",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()

        return ProviderSubmission(
            provider_job_id=str(data.get("id") or data.get("torrent_id") or data.get("job_id")),
            display_name=str(data.get("name") or "torbox-job"),
        )

    async def submit_torrent_bytes(self, filename: str, data: bytes) -> ProviderSubmission:
        files = {"file": (filename, data, "application/x-bittorrent")}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base}/api/v1/torrents",
                files=files,
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()

        return ProviderSubmission(
            provider_job_id=str(payload.get("id") or payload.get("torrent_id") or payload.get("job_id")),
            display_name=str(payload.get("name") or filename),
        )

    async def get_status(self, provider_job_id: str) -> ProviderStatus:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base}/api/v1/torrents/{provider_job_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()

        progress = float(data.get("progress", 0.0))
        if progress > 1.0:
            progress /= 100.0

        return ProviderStatus(
            provider_job_id=provider_job_id,
            status=str(data.get("status", "unknown")),
            progress=max(0.0, min(progress, 1.0)),
            remote_path=data.get("webdav_path") or data.get("path"),
            error=data.get("error"),
        )

    async def healthcheck(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, "TorBox API key is not configured"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self._base}/api/v1/health", headers=self._headers())
                response.raise_for_status()
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, f"torbox_unreachable: {exc}"
