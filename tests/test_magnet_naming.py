from app.services.job_service import derive_display_name
from app.services.job_service import JobService


def test_derive_display_name_extracts_dn_from_realistic_magnet() -> None:
    magnet = (
        "magnet:?xt=urn:btih:7585266CB4F87A0132C10BC8D89280D9CA9E9D11"
        "&dn=andor+s01e09+multi+2160p+uhd+bluray+x265-seskapile+mkv"
        "&tr=udp%3A%2F%2Ftracker.example%3A1337"
    )

    assert derive_display_name(magnet, magnet[:120]) == "andor s01e09 multi 2160p uhd bluray x265-seskapile mkv"


def test_existing_job_with_magnet_title_is_upgraded_when_dn_is_available(db_session) -> None:
    service = JobService(db_session)
    magnet = (
        "magnet:?xt=urn:btih:7585266CB4F87A0132C10BC8D89280D9CA9E9D11"
        "&dn=andor+s01e09+multi+2160p+uhd+bluray+x265-seskapile+mkv"
        "&tr=udp%3A%2F%2Ftracker.example%3A1337"
    )

    first = service.create_received_job(
        magnet_uri=magnet,
        name=magnet[:120],
        category="sonarr",
        save_path="/links",
    )
    first.torrent_name = magnet[:120]
    first.sonarr_title = magnet[:120]
    db_session.add(first)
    db_session.commit()
    db_session.refresh(first)

    second = service.create_received_job(
        magnet_uri=magnet,
        name="andor s01e09 multi 2160p uhd bluray x265-seskapile mkv",
        category="sonarr",
        save_path="/links",
    )

    assert second.id == first.id
    assert second.torrent_name == "andor s01e09 multi 2160p uhd bluray x265-seskapile mkv"
    assert second.sonarr_title == "andor s01e09 multi 2160p uhd bluray x265-seskapile mkv"
