"""WebDAV mount management and deterministic refresh logic."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from app.core.config import Settings

logger = logging.getLogger(__name__)


class WebDavMountManager:
    """Handles mount health checks and cache refresh/remount strategy."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mount_path = Path(settings.webdav_mount_path)
        self.last_successful_refresh: str | None = None

    def _run_shell(self, cmd: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
            return True, result.stdout.strip()
        except subprocess.CalledProcessError as exc:
            return False, (exc.stderr or exc.stdout or str(exc)).strip()

    def is_mount_available(self) -> tuple[bool, str]:
        if not self.mount_path.exists():
            return False, f"Mount path does not exist: {self.mount_path}"
        if not self.mount_path.is_dir():
            return False, f"Mount path is not a directory: {self.mount_path}"
        if not os.path.ismount(self.mount_path):
            return False, f"Path is not currently mounted: {self.mount_path}"
        try:
            _ = next(self.mount_path.iterdir(), None)
        except OSError as exc:
            return False, f"Cannot list mount directory: {exc}"
        return True, "ok"

    async def refresh_mount_view(self) -> tuple[bool, str]:
        ok, output = self._run_shell(self.settings.webdav_refresh_command)
        if ok:
            self.last_successful_refresh = output or "refreshed"
            return True, output or "refreshed"

        logger.warning("webdav_refresh_failed", extra={"state": "REFRESHING_WEBDAV", "msg": output})
        remount_ok, remount_output = self._run_shell(self.settings.webdav_remount_command)
        if remount_ok:
            self.last_successful_refresh = remount_output or "remounted"
            return True, remount_output or "remounted"
        return False, remount_output

    async def ensure_remote_path_visible(self, remote_path: str) -> tuple[bool, str]:
        """Force refresh and validate visibility of remote path in mounted filesystem."""

        rel = remote_path.lstrip("/")
        expected = self.mount_path / rel

        for attempt in range(1, self.settings.refresh_max_attempts + 1):
            if expected.exists():
                return True, f"visible_after_attempt_{attempt}"
            await self.refresh_mount_view()
            await asyncio.sleep(self.settings.refresh_retry_seconds)
        return False, f"remote path not visible after retries: {expected}"
