"""Provider abstraction for remote debrid backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ProviderSubmission:
    """Result for a newly submitted download job."""

    provider_job_id: str
    display_name: str


@dataclass(slots=True)
class ProviderStatus:
    """Normalized provider status for orchestration."""

    provider_job_id: str
    status: str
    progress: float
    remote_path: str | None
    error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status.lower() in {"ready", "completed", "finished"}

    @property
    def is_failed(self) -> bool:
        return self.status.lower() in {"failed", "error"}


class DebridProvider(Protocol):
    """Contract for backend providers like TorBox."""

    async def submit_magnet(self, magnet_uri: str) -> ProviderSubmission: ...

    async def submit_torrent_bytes(self, filename: str, data: bytes) -> ProviderSubmission: ...

    async def get_status(self, provider_job_id: str) -> ProviderStatus: ...

    async def healthcheck(self) -> tuple[bool, str]: ...
