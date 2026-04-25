from app.core.config import Settings
from app.services.provider.realdebrid import RealDebridProvider
import pytest


def test_select_remote_path_prefers_video_over_proof_image() -> None:
    provider = RealDebridProvider(Settings())

    selected = provider._select_remote_path(
        [
            {"path": "/Proof/andor.s01e01.2160p.uhd.bluray.x265.proof-stories.jpg", "bytes": 12345},
            {"path": "/Andor.S01E01.2160p.UHD.BluRay.x265-STORIES.mkv", "bytes": 4_000_000_000},
            {"path": "/Proof/release.nfo", "bytes": 512},
        ]
    )

    assert selected == "/Andor.S01E01.2160p.UHD.BluRay.x265-STORIES.mkv"


def test_select_remote_path_falls_back_to_non_auxiliary_file() -> None:
    provider = RealDebridProvider(Settings())

    selected = provider._select_remote_path(
        [
            {"path": "/Release/readme.txt", "bytes": 128},
            {"path": "/Release/archive.rar", "bytes": 1024},
            {"path": "/Release/poster.jpg", "bytes": 2048},
        ]
    )

    assert selected == "/Release/archive.rar"


@pytest.mark.asyncio
async def test_get_status_treats_downloading_100_with_media_path_as_ready() -> None:
    provider = RealDebridProvider(Settings())

    async def fake_get_json(*, path: str):
        _ = path
        return {
            "status": "downloading",
            "bytes": 1_000,
            "original_bytes": 1_000,
            "files": [
                {"path": "/Proof/info.jpg", "bytes": 10},
                {"path": "/Show/episode.mkv", "bytes": 999},
            ],
        }

    provider._get_json = fake_get_json  # type: ignore[method-assign]
    result = await provider.get_status("job-1")

    assert result.status == "completed"
    assert result.is_ready
    assert result.remote_path == "/Show/episode.mkv"