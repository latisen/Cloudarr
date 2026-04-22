from __future__ import annotations

from pathlib import Path

from app.services.symlink_manager import SymlinkManager


def test_symlink_manager_creates_symlink_only(tmp_path: Path) -> None:
    mount = tmp_path / "mnt"
    staging = tmp_path / "links"
    remote = mount / "release"
    remote.mkdir(parents=True)
    media = remote / "episode.mkv"
    media.write_text("dummy")

    manager = SymlinkManager(str(mount), str(staging))
    output = manager.create_job_symlinks("release", "abc123", "sonarr")

    linked = Path(output) / "episode.mkv"
    assert linked.is_symlink()
    assert linked.resolve() == media.resolve()


def test_symlink_manager_rejects_non_mount_sources(tmp_path: Path) -> None:
    mount = tmp_path / "mnt"
    staging = tmp_path / "links"
    manager = SymlinkManager(str(mount), str(staging))

    bad = tmp_path / "outside"
    bad.mkdir(parents=True)

    try:
        manager.create_job_symlinks("../outside", "abc123", "sonarr")
        assert False, "expected ValueError"
    except ValueError:
        assert True
