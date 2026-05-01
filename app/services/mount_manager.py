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
        self._remote_root = settings.webdav_remote_root.strip("/")
        self.last_successful_refresh: str | None = None

    def _run_shell(self, cmd: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.settings.webdav_command_timeout_seconds,
            )
            return True, result.stdout.strip()
        except subprocess.TimeoutExpired as exc:
            return False, f"command timed out after {self.settings.webdav_command_timeout_seconds}s: {cmd}"
        except subprocess.CalledProcessError as exc:
            return False, (exc.stderr or exc.stdout or str(exc)).strip()

    def _resolve_fallback_limited(self, rel: str) -> Path | None:
        """Fallback filename search with bounded directory traversal.

        Strategy:
        1. First do a cheap first-level scan in remote_root directories whose name
           shares the file stem. This handles the common case where Real-Debrid places
           a torrent file inside a same-named folder (e.g. Foo.mkv lives at
           torrents/Foo[rarbg]/Foo.mkv).
        2. Fall back to a bounded full walk if the targeted scan fails.
        """

        name = Path(rel).name
        if not name:
            return None

        stem_lower = Path(name).stem.lower()

        roots: list[Path] = []
        if self._remote_root:
            roots.append(self.mount_path / self._remote_root)
        roots.append(self.mount_path)

        # --- Pass 1: prioritised scan in matching first-level subdirs ---
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            try:
                for entry in root.iterdir():
                    if not entry.is_dir():
                        continue
                    if stem_lower not in entry.name.lower():
                        continue
                    # Look for the target file inside this matching subdir
                    try:
                        lower_map = {f.name.lower(): f for f in entry.iterdir() if f.is_file()}
                        matched = lower_map.get(name.lower())
                        if matched:
                            return matched
                    except OSError:
                        continue
            except OSError:
                continue

        # --- Pass 2: bounded full walk ---
        max_entries = self.settings.webdav_fallback_search_max_entries
        visited_entries = 0
        seen: set[Path] = set()

        for root in roots:
            if root in seen or not root.exists() or not root.is_dir():
                continue
            seen.add(root)
            try:
                for current_root, dirs, files in os.walk(root):
                    visited_entries += len(dirs) + len(files)
                    if visited_entries > max_entries:
                        logger.warning(
                            "webdav_fallback_search_capped",
                            extra={
                                "state": "REFRESHING_WEBDAV",
                                "max_entries": max_entries,
                                "target_name": name,
                            },
                        )
                        return None

                    lower_map = {entry.lower(): entry for entry in files}
                    matched = lower_map.get(name.lower())
                    if matched:
                        return Path(current_root) / matched
            except OSError:
                continue

        return None

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

        logger.warning("webdav_refresh_failed", extra={"state": "REFRESHING_WEBDAV", "refresh_output": output})
        remount_ok, remount_output = self._run_shell(self.settings.webdav_remount_command)
        if remount_ok:
            self.last_successful_refresh = remount_output or "remounted"
            return True, remount_output or "remounted"
        return False, remount_output

    async def ensure_remote_path_visible(self, remote_path: str) -> tuple[bool, str]:
        """Force one refresh attempt and validate visibility of remote path.

        The worker revisits REFRESHING_WEBDAV jobs on later ticks, so this method
        should stay bounded and cheap enough that one stuck WebDAV refresh does not
        starve newer jobs in the same queue.
        """

        rel = remote_path.lstrip("/")
        candidates: list[Path] = [self.mount_path / rel]
        if self._remote_root:
            prefixed = [
                self.mount_path / self._remote_root / rel,
                self.mount_path / self._remote_root / "torrents" / rel,
            ]
            for candidate in reversed(prefixed):
                if candidate not in candidates:
                    candidates.insert(0, candidate)

        torrents_candidate = self.mount_path / "torrents" / rel
        if torrents_candidate not in candidates:
            candidates.append(torrents_candidate)

        attempt = 1
        logger.info(
            "webdav_visibility_attempt",
            extra={
                "state": "REFRESHING_WEBDAV",
                "attempt": attempt,
                "max_attempts": self.settings.refresh_max_attempts,
                "remote_path": remote_path,
            },
        )
        for candidate in candidates:
            if candidate.exists():
                rel_found = candidate.relative_to(self.mount_path).as_posix()
                if rel_found != rel:
                    return True, f"resolved_relative_path=/{rel_found}"
                return True, f"visible_after_attempt_{attempt}"

        resolved = self._resolve_fallback_limited(rel)
        if resolved is not None:
            rel_resolved = resolved.relative_to(self.mount_path).as_posix()
            return True, f"resolved_relative_path=/{rel_resolved}"

        await self.refresh_mount_view()
        await asyncio.sleep(self.settings.refresh_retry_seconds)

        for candidate in candidates:
            if candidate.exists():
                rel_found = candidate.relative_to(self.mount_path).as_posix()
                if rel_found != rel:
                    return True, f"resolved_relative_path=/{rel_found}"
                return True, f"visible_after_attempt_{attempt}"

        resolved = self._resolve_fallback_limited(rel)
        if resolved is not None:
            rel_resolved = resolved.relative_to(self.mount_path).as_posix()
            return True, f"resolved_relative_path=/{rel_resolved}"

        checked = ", ".join(str(candidate) for candidate in candidates)
        return False, f"remote path not visible after retries: {checked}"
