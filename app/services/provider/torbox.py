"""TorBox provider implementation.

Assumptions:
- POST /api/v1/torrents accepts either magnet link payload or multipart torrent upload.
- GET /api/v1/torrents/{id} returns status/progress/webdav_path fields.

These are isolated behind the provider interface so endpoint mappings can be adjusted
without impacting qBittorrent compatibility logic.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

from app.core.config import Settings
from app.services.provider.base import DebridProvider, ProviderStatus, ProviderSubmission


class TorBoxProvider(DebridProvider):
    """TorBox API client wrapper."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.torbox_api_base.rstrip("/")
        self._api_key = settings.torbox_api_key
        self._torrents_path = settings.torbox_torrents_path
        self._health_path = settings.torbox_health_path
        self._timeout = httpx.Timeout(20.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    def _candidate_torrent_paths(self) -> list[str]:
        configured = self._torrents_path if self._torrents_path.startswith("/") else f"/{self._torrents_path}"
        candidates = [
            configured,
            "/api/v1/torrents",
            "/v1/api/torrents",
            "/v1/torrents",
            "/api/torrents",
            "/torrents",
        ]
        ordered: list[str] = []
        for value in candidates:
            if value not in ordered:
                ordered.append(value)
        return ordered

    async def _post_first_json(
        self,
        *,
        paths: Iterable[str],
        json_payload: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for path in paths:
                url = f"{self._base}{path}"
                response = await client.post(url, json=json_payload, files=files, headers=self._headers())
                if response.status_code == 404:
                    errors.append(f"404 on {url}")
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    body = exc.response.text[:400] if exc.response is not None else ""
                    raise RuntimeError(f"TorBox POST failed at {url}: {exc}; body={body}") from exc
                return response.json()
        raise RuntimeError(f"TorBox torrents endpoint not found. Tried: {', '.join(errors)}")

    async def _get_first_json(self, *, paths: Iterable[str]) -> dict[str, Any]:
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for path in paths:
                url = f"{self._base}{path}"
                response = await client.get(url, headers=self._headers())
                if response.status_code == 404:
                    errors.append(f"404 on {url}")
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    body = exc.response.text[:400] if exc.response is not None else ""
                    raise RuntimeError(f"TorBox GET failed at {url}: {exc}; body={body}") from exc
                return response.json()
        raise RuntimeError(f"TorBox endpoint not found. Tried: {', '.join(errors)}")

    async def submit_magnet(self, magnet_uri: str) -> ProviderSubmission:
        payload = {"magnet": magnet_uri}
        data = await self._post_first_json(paths=self._candidate_torrent_paths(), json_payload=payload)

        return ProviderSubmission(
            provider_job_id=str(data.get("id") or data.get("torrent_id") or data.get("job_id")),
            display_name=str(data.get("name") or "torbox-job"),
        )

    async def submit_torrent_bytes(self, filename: str, data: bytes) -> ProviderSubmission:
        files = {"file": (filename, data, "application/x-bittorrent")}
        payload = await self._post_first_json(paths=self._candidate_torrent_paths(), files=files)

        return ProviderSubmission(
            provider_job_id=str(payload.get("id") or payload.get("torrent_id") or payload.get("job_id")),
            display_name=str(payload.get("name") or filename),
        )

    async def get_status(self, provider_job_id: str) -> ProviderStatus:
        data = await self._get_first_json(
            paths=[f"{path.rstrip('/')}/{provider_job_id}" for path in self._candidate_torrent_paths()]
        )

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
                health_paths = [
                    self._health_path if self._health_path.startswith("/") else f"/{self._health_path}",
                    "/api/v1/health",
                    "/v1/health",
                    "/health",
                ]
                for path in health_paths:
                    response = await client.get(f"{self._base}{path}", headers=self._headers())
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    return True, "ok"
                return False, "torbox_health_endpoint_not_found"
        except Exception as exc:  # noqa: BLE001
            return False, f"torbox_unreachable: {exc}"
