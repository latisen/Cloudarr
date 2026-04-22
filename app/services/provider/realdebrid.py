"""Real-Debrid provider implementation.

Important limitation:
Real-Debrid's official API exposes torrent submission, selection, status, and
download links, but it does not expose a WebDAV filesystem. That means Cloudarr
cannot derive a mount-backed filesystem path from Real-Debrid alone.

This provider is therefore correct for torrent control/status, but will report a
clear error when content is ready but no mountable path can be produced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.services.provider.base import DebridProvider, ProviderStatus, ProviderSubmission


class RealDebridProvider(DebridProvider):
    """Real-Debrid REST API client."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.realdebrid_api_base.rstrip("/")
        self._token = settings.realdebrid_api_token
        self._add_magnet_path = settings.realdebrid_add_magnet_path
        self._add_torrent_path = settings.realdebrid_add_torrent_path
        self._info_path = settings.realdebrid_info_path
        self._select_files_path = settings.realdebrid_select_files_path
        self._user_path = settings.realdebrid_user_path
        self._timeout = httpx.Timeout(20.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    def _normalized_path(self, path: str) -> str:
        return path if path.startswith("/") else f"/{path}"

    async def _post_form(self, *, path: str, data: dict[str, str], files: dict[str, tuple[str, bytes, str]] | None = None) -> Any:
        url = f"{self._base}{self._normalized_path(path)}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, data=data, files=files, headers=self._headers())
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:800] if exc.response is not None else ""
                raise RuntimeError(f"Real-Debrid POST failed at {url}: {exc}; body={body}") from exc
            if not response.text.strip():
                return None
            return response.json()

    async def _put_file(self, *, path: str, filename: str, payload: bytes) -> Any:
        url = f"{self._base}{self._normalized_path(path)}"
        headers = {key: value for key, value in self._headers().items() if key != "Accept"}
        headers["Content-Type"] = "application/x-bittorrent"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.put(url, params={"host": "real-debrid"}, content=payload, headers=headers)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:800] if exc.response is not None else ""
                raise RuntimeError(f"Real-Debrid PUT failed at {url}: {exc}; body={body}") from exc
            return response.json()

    async def _get_json(self, *, path: str) -> Any:
        url = f"{self._base}{self._normalized_path(path)}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, headers=self._headers())
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:800] if exc.response is not None else ""
                raise RuntimeError(f"Real-Debrid GET failed at {url}: {exc}; body={body}") from exc
            return response.json()

    async def submit_magnet(self, magnet_uri: str) -> ProviderSubmission:
        payload = await self._post_form(path=self._add_magnet_path, data={"magnet": magnet_uri})
        torrent_id = str(payload.get("id") or "")
        await self._post_form(path=f"{self._select_files_path}/{torrent_id}", data={"files": "all"})
        return ProviderSubmission(provider_job_id=torrent_id, display_name=magnet_uri)

    async def submit_torrent_bytes(self, filename: str, data: bytes) -> ProviderSubmission:
        upload = await self._put_file(path=self._add_torrent_path, filename=filename, payload=data)
        torrent_id = str(upload.get("id") or "")
        await self._post_form(path=f"{self._select_files_path}/{torrent_id}", data={"files": "all"})
        return ProviderSubmission(provider_job_id=torrent_id, display_name=filename)

    async def get_status(self, provider_job_id: str) -> ProviderStatus:
        item = await self._get_json(path=f"{self._info_path}/{provider_job_id}")

        status = str(item.get("status", "unknown"))
        bytes_total = float(item.get("bytes", 0) or 0)
        bytes_done = float(item.get("original_bytes", 0) or 0)
        progress = 0.0
        if bytes_total > 0 and bytes_done > 0:
            progress = min(max(bytes_done / bytes_total, 0.0), 1.0)
        elif status.lower() in {"downloaded", "compressing", "uploading", "waiting_files_selection", "queued"}:
            progress = float(item.get("progress", 0.0) or 0.0)
            if progress > 1.0:
                progress /= 100.0

        links = item.get("links") or []
        files = item.get("files") or []
        ready = status.lower() in {"downloaded", "uploading", "compressing"}
        error: str | None = None
        remote_path: str | None = None

        if ready:
            error = (
                "Real-Debrid torrent is ready, but the official API does not expose a WebDAV or mountable filesystem path. "
                "Cloudarr's symlink-only import flow cannot continue without an external mountable mirror."
            )
            if files:
                remote_path = str(Path(files[0].get("path") or files[0].get("filename") or "").name)
        elif status.lower() in {"error", "virus", "dead"}:
            error = item.get("message") or status

        return ProviderStatus(
            provider_job_id=provider_job_id,
            status="completed" if ready else status,
            progress=progress,
            remote_path=remote_path,
            error=error,
        )

    async def healthcheck(self) -> tuple[bool, str]:
        if not self._token:
            return False, "Real-Debrid API token is not configured"
        try:
            await self._get_json(path=self._user_path)
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, f"realdebrid_unreachable: {exc}"
