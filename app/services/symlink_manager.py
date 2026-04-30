"""Symlink-only export manager.

Non-negotiable behavior:
- Never copy or download media payloads.
- Only create symbolic links from staging root to mounted WebDAV files.
"""

from __future__ import annotations

import os
from pathlib import Path


class SymlinkManager:
    """Creates Sonarr-visible symlink trees pointing at mounted WebDAV files."""

    def __init__(self, mount_path: str, staging_root: str) -> None:
        self.mount_path = Path(mount_path).resolve()
        self.staging_root = Path(staging_root).resolve()
        self.staging_root.mkdir(parents=True, exist_ok=True)

    def _assert_under_mount(self, source: Path) -> None:
        src = source.resolve()
        if self.mount_path not in src.parents and src != self.mount_path:
            raise ValueError(f"Refusing non-mounted source path: {src}")

    def create_job_symlinks(self, remote_rel_path: str, job_id: str, category: str) -> str:
        source_root = (self.mount_path / remote_rel_path.lstrip("/")).resolve()
        self._assert_under_mount(source_root)
        if not source_root.exists():
            raise FileNotFoundError(f"Remote path does not exist: {source_root}")

        target_root = self.staging_root / category / job_id
        target_root.mkdir(parents=True, exist_ok=True)

        if source_root.is_file():
            # Preserve mount-relative path for single-file exports so API-reported
            # file names like "torrents/<name>.mkv" resolve inside the job folder.
            link_rel = source_root.relative_to(self.mount_path)
            link = target_root / link_rel
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.exists() or link.is_symlink():
                link.unlink()
            os.symlink(source_root, link)
            return str(target_root)

        for src in source_root.rglob("*"):
            rel = src.relative_to(source_root)
            dst = target_root / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            os.symlink(src, dst)

        return str(target_root)

    def find_broken_symlinks(self, root: str | None = None) -> list[str]:
        base = Path(root).resolve() if root else self.staging_root
        broken: list[str] = []
        for p in base.rglob("*"):
            if p.is_symlink() and not p.exists():
                broken.append(str(p))
        return broken
