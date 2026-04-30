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
        self._torrents_path = settings.torbox_torrents_path
        self._mylist_path = settings.torbox_mylist_path
        self._health_path = settings.torbox_health_path
        self._timeout = httpx.Timeout(20.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    def _normalized_path(self, path: str) -> str:
        return path if path.startswith("/") else f"/{path}"

    def _unwrap_standard_response(self, payload: dict[str, Any], *, url: str) -> Any:
        if "success" not in payload:
            return payload
        if not payload.get("success", False):
            raise RuntimeError(
                f"TorBox API error at {url}: {payload.get('error') or 'UNKNOWN'} - {payload.get('detail') or 'no detail'}"
            )
        return payload.get("data")

    async def _post_form(self, *, path: str, form_data: dict[str, Any], files: dict[str, tuple[str, bytes, str]] | None = None) -> Any:
        url = f"{self._base}{self._normalized_path(path)}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, data=form_data, files=files, headers=self._headers())
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:800] if exc.response is not None else ""
                raise RuntimeError(f"TorBox POST failed at {url}: {exc}; body={body}") from exc
            return self._unwrap_standard_response(response.json(), url=url)

    async def _get_json(self, *, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}{self._normalized_path(path)}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, params=params, headers=self._headers())
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:800] if exc.response is not None else ""
                raise RuntimeError(f"TorBox GET failed at {url}: {exc}; body={body}") from exc
            return self._unwrap_standard_response(response.json(), url=url)

    async def submit_magnet(self, magnet_uri: str) -> ProviderSubmission:
        data = await self._post_form(
            path=self._torrents_path,
            form_data={
                "magnet": magnet_uri,
                "seed": "1",
                "allow_zip": "true",
            },
        )
        provider_job_id = str(data.get("torrent_id") or data.get("id") or data.get("auth_id") or "")
        if not provider_job_id:
            raise RuntimeError(f"TorBox create torrent returned missing id; payload_keys={sorted(data.keys())}")

        return ProviderSubmission(
            provider_job_id=provider_job_id,
            display_name=str(data.get("hash") or "torbox-job"),
        )

    async def submit_torrent_bytes(self, filename: str, data: bytes) -> ProviderSubmission:
        files = {"file": (filename, data, "application/x-bittorrent")}
        payload = await self._post_form(
            path=self._torrents_path,
            form_data={
                "seed": "1",
                "allow_zip": "true",
                "name": filename,
            },
            files=files,
        )
        provider_job_id = str(payload.get("torrent_id") or payload.get("id") or payload.get("auth_id") or "")
        if not provider_job_id:
            raise RuntimeError(f"TorBox upload returned missing id; payload_keys={sorted(payload.keys())}")

        return ProviderSubmission(
            provider_job_id=provider_job_id,
            display_name=str(payload.get("hash") or filename),
        )

    async def get_status(self, provider_job_id: str) -> ProviderStatus:
        data = await self._get_json(
            path=self._mylist_path,
            params={
                "id": provider_job_id,
                "bypass_cache": "true",
            },
        )

        item = data[0] if isinstance(data, list) else data

        progress = float(item.get("progress", 0.0))
        if progress > 1.0:
            progress /= 100.0

        remote_path = item.get("download_path")
        if not remote_path:
            files = item.get("files") or []
            if files:
                remote_path = files[0].get("absolute_path")

        download_state = str(item.get("download_state", "unknown"))
        is_finished = bool(item.get("download_finished", False))
        normalized_status = "completed" if is_finished else download_state

        return ProviderStatus(
            provider_job_id=provider_job_id,
            status=normalized_status,
            progress=max(0.0, min(progress, 1.0)),
            remote_path=remote_path,
            error=item.get("error") or item.get("tracker_message"),
        )

    async def healthcheck(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, "TorBox API key is not configured"

        try:
            await self._get_json(path=self._health_path, params={"limit": "1"})
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, f"torbox_unreachable: {exc}"
