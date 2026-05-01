from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.mount_manager import WebDavMountManager


@pytest.mark.asyncio
async def test_refresh_visibility_single_attempt_per_tick(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    assert not ok
    assert calls["count"] == 1

    ok, msg = await manager.ensure_remote_path_visible("ready")
    assert ok
    assert msg == "visible_after_attempt_1"
    assert calls["count"] == 2


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


@pytest.mark.asyncio
async def test_refresh_visibility_checks_links_torrents_candidate(tmp_path: Path) -> None:
    settings = Settings(
        webdav_mount_path=str(tmp_path),
        webdav_remote_root="links",
        refresh_max_attempts=1,
        refresh_retry_seconds=0,
        webdav_refresh_command="true",
        webdav_remount_command="false",
    )
    manager = WebDavMountManager(settings)

    target = tmp_path / "links" / "torrents" / "andor.s01e02.2160p.uhd.bluray.x265-stories.mkv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    ok, msg = await manager.ensure_remote_path_visible("/andor.s01e02.2160p.uhd.bluray.x265-stories.mkv")
    assert ok
    assert msg == "resolved_relative_path=/links/torrents/andor.s01e02.2160p.uhd.bluray.x265-stories.mkv"


@pytest.mark.asyncio
async def test_refresh_visibility_checks_root_torrents_candidate(tmp_path: Path) -> None:
    settings = Settings(
        webdav_mount_path=str(tmp_path),
        webdav_remote_root="links",
        refresh_max_attempts=1,
        refresh_retry_seconds=0,
        webdav_refresh_command="true",
        webdav_remount_command="false",
    )
    manager = WebDavMountManager(settings)

    target = tmp_path / "torrents" / "Andor S02E01 One Year Later 2160p DSNP WEB-DL DDP5 1 DV HDR H 265-NTb.mkv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    ok, msg = await manager.ensure_remote_path_visible("/Andor S02E01 One Year Later 2160p DSNP WEB-DL DDP5 1 DV HDR H 265-NTb.mkv")
    assert ok
    assert msg == "resolved_relative_path=/torrents/Andor S02E01 One Year Later 2160p DSNP WEB-DL DDP5 1 DV HDR H 265-NTb.mkv"


@pytest.mark.asyncio
async def test_refresh_visibility_resolves_filename_case_insensitive(tmp_path: Path) -> None:
    settings = Settings(
        webdav_mount_path=str(tmp_path),
        webdav_remote_root="links",
        refresh_max_attempts=1,
        refresh_retry_seconds=0,
        webdav_refresh_command="true",
        webdav_remount_command="false",
    )
    manager = WebDavMountManager(settings)

    target = tmp_path / "links" / "Series" / "Andor.S01E02.REPACK.2160p.WEB.h265-KOGi.mkv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    ok, msg = await manager.ensure_remote_path_visible("/andor.s01e02.repack.2160p.web.h265-kogi.mkv")
    assert ok
    assert msg == "resolved_relative_path=/links/Series/Andor.S01E02.REPACK.2160p.WEB.h265-KOGi.mkv"


@pytest.mark.asyncio
async def test_refresh_visibility_resolves_release_with_rarbg_suffix(tmp_path: Path) -> None:
    settings = Settings(
        webdav_mount_path=str(tmp_path),
        webdav_remote_root="",
        refresh_max_attempts=1,
        refresh_retry_seconds=0,
        webdav_refresh_command="true",
        webdav_remount_command="false",
    )
    manager = WebDavMountManager(settings)

    target = (
        tmp_path
        / "torrents"
        / "Andor.S01E02.REPACK.2160p.WEB.h265-KOGi[rarbg]"
        / "Andor.S01E02.REPACK.2160p.WEB.h265-KOGi[rarbg].mkv"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    ok, msg = await manager.ensure_remote_path_visible("/Andor.S01E02.REPACK.2160p.WEB.h265-KOGi.mkv")
    assert ok
    assert (
        msg
        == "resolved_relative_path=/torrents/Andor.S01E02.REPACK.2160p.WEB.h265-KOGi[rarbg]/Andor.S01E02.REPACK.2160p.WEB.h265-KOGi[rarbg].mkv"
    )


@pytest.mark.asyncio
async def test_refresh_visibility_resolves_space_separated_remote_path_to_dot_release_layout(tmp_path: Path) -> None:
    settings = Settings(
        webdav_mount_path=str(tmp_path),
        webdav_remote_root="",
        refresh_max_attempts=1,
        refresh_retry_seconds=0,
        webdav_refresh_command="true",
        webdav_remount_command="false",
    )
    manager = WebDavMountManager(settings)

    target = (
        tmp_path
        / "torrents"
        / "Andor.S01E04.Aldhani.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-FraMeSToR"
        / "andor.s01e04.aldhani.uhd.bluray.2160p.truehd.atmos.7.1.dv.hevc.hybrid.remux-framestor.mkv"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    ok, msg = await manager.ensure_remote_path_visible(
        "/Andor S01E04 Aldhani UHD BluRay 2160p TrueHD Atmos 7 1 DV HEVC HYBRID REMUX-FraMeSToR.mkv"
    )
    assert ok
    assert (
        msg
        == "resolved_relative_path=/torrents/Andor.S01E04.Aldhani.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-FraMeSToR/andor.s01e04.aldhani.uhd.bluray.2160p.truehd.atmos.7.1.dv.hevc.hybrid.remux-framestor.mkv"
    )


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
