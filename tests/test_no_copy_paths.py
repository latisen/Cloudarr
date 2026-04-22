from __future__ import annotations

from pathlib import Path


FORBIDDEN_TOKENS = [
    "shutil.copy",
    "shutil.copy2",
    "shutil.copyfile",
    "requests.get(",
    "httpx.get(",
    "open(\"wb\"",
]


def test_media_copy_operations_not_used_in_symlink_manager() -> None:
    content = Path("app/services/symlink_manager.py").read_text(encoding="utf-8")
    for token in FORBIDDEN_TOKENS:
        assert token not in content
