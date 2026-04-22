"""Schemas for qBittorrent compatibility responses."""

from pydantic import BaseModel


class QBittorrentInfoItem(BaseModel):
    """Subset of qBittorrent torrent info fields Sonarr expects."""

    hash: str
    name: str
    progress: float
    state: str
    category: str
    save_path: str
    completed: int
    size: int
    amount_left: int
