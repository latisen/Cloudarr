"""Real-Debrid provider implementation.

Real-Debrid provides both torrent control via REST API and file access via WebDAV at
https://dav.real-debrid.com/. This provider handles both, reporting WebDAV paths
that Cloudarr can mount and use for symlink-only imports.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

import httpx

from app.core.config import Settings
from app.services.provider.base import DebridProvider, ProviderStatus, ProviderSubmission


class RealDebridProvider(DebridProvider):
    """Real-Debrid REST API client."""

    _MEDIA_EXTENSIONS = {
        ".mkv",
        ".mp4",
        ".avi",
        ".mov",
        ".m4v",
        ".wmv",
        ".ts",
        ".m2ts",
        ".mpg",
        ".mpeg",
    }

    _AUXILIARY_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".nfo",
        ".sfv",
        ".srr",
        ".txt",
        ".md",
        ".url",
        ".ico",
        ".bmp",
        ".cue",
    }

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

    def _select_remote_path(self, files: list[dict[str, Any]]) -> str | None:
        scored_paths: list[tuple[int, int, int, str]] = []

        for index, file_item in enumerate(files):
            file_path = str(file_item.get("path") or file_item.get("filename") or "").strip()
            if not file_path:
                continue

            lower_path = file_path.lower()
            name = PurePosixPath(file_path).name.lower()
            ext = PurePosixPath(file_path).suffix.lower()
            size = int(file_item.get("bytes") or file_item.get("filesize") or 0)

            is_sample = "sample" in lower_path
            is_proof = "proof" in lower_path
            is_auxiliary = ext in self._AUXILIARY_EXTENSIONS
            is_media = ext in self._MEDIA_EXTENSIONS

            if is_media and not is_sample:
                priority = 4 if not is_proof else 3
            elif not is_auxiliary and not is_sample:
                priority = 2 if not is_proof else 1
            else:
                priority = 0

            scored_paths.append((priority, size, -index, file_path))

        if not scored_paths:
            return None

        best = max(scored_paths)
        return best[3] if best[0] > 0 else scored_paths[0][3]

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

        files = item.get("files") or []
        selected_path = self._select_remote_path(files)
        ready_status = status.lower() in {"downloaded", "uploading", "compressing"}
        # Real-Debrid can remain in "downloading" even when progress has reached 100%.
        # If we already have a concrete mountable path, allow the pipeline to continue.
        ready_progress = status.lower() == "downloading" and progress >= 0.999 and bool(selected_path)
        ready = ready_status or ready_progress
        error: str | None = None
        remote_path: str | None = None

        if ready and selected_path:
            remote_path = selected_path
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
