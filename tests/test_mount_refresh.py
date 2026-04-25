from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.mount_manager import WebDavMountManager


@pytest.mark.asyncio
async def test_refresh_visibility_retries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = Settings(
        webdav_mount_path=str(tmp_path),
        refresh_max_attempts=3,
        refresh_retry_seconds=0,
        webdav_refresh_command="true",
        webdav_remount_command="true",
    )
    manager = WebDavMountManager(settings)

    calls = {"count": 0}

    async def fake_refresh() -> tuple[bool, str]:
        calls["count"] += 1
        if calls["count"] == 2:
            (tmp_path / "ready").mkdir(parents=True, exist_ok=True)
        return True, "ok"

    async def no_sleep(_: int) -> None:
        return None

    monkeypatch.setattr(manager, "refresh_mount_view", fake_refresh)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    ok, _ = await manager.ensure_remote_path_visible("ready")
    assert ok
    assert calls["count"] >= 1


@pytest.mark.asyncio
async def test_refresh_visibility_resolves_by_filename(tmp_path: Path) -> None:
    settings = Settings(
        webdav_mount_path=str(tmp_path),
        webdav_remote_root="links",
        refresh_max_attempts=1,
        refresh_retry_seconds=0,
        webdav_refresh_command="true",
        webdav_remount_command="false",
    )
    manager = WebDavMountManager(settings)

    target = tmp_path / "links" / "series" / "Andor S02E12.mkv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    ok, msg = await manager.ensure_remote_path_visible("/Andor S02E12.mkv")
    assert ok
    assert msg == "resolved_relative_path=/links/series/Andor S02E12.mkv"


def test_run_shell_times_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = Settings(
        webdav_mount_path=str(tmp_path),
        webdav_command_timeout_seconds=1,
        webdav_refresh_command="true",
        webdav_remount_command="true",
    )
    manager = WebDavMountManager(settings)

    def fake_run(*args, **kwargs):
        _ = (args, kwargs)
        raise subprocess.TimeoutExpired(cmd="sleep 999", timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, msg = manager._run_shell("sleep 999")
    assert not ok
    assert "timed out" in msg


def test_resolve_fallback_limited_respects_cap(tmp_path: Path) -> None:
    settings = Settings(
        webdav_mount_path=str(tmp_path),
        webdav_fallback_search_max_entries=100,
    )
    manager = WebDavMountManager(settings)

    root = tmp_path / "links"
    root.mkdir(parents=True, exist_ok=True)
    # Build enough files to exceed the cap before any expected match.
    for idx in range(200):
        (root / f"f{idx}.txt").write_text("x")

    result = manager._resolve_fallback_limited("/target.mkv")
    assert result is None
