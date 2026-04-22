"""Standalone worker entrypoint for systemd deployment."""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.session import engine
from app.services.runtime import Runtime


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    Base.metadata.create_all(bind=engine)
    runtime = Runtime(settings)
    await runtime.worker.run_forever()


def run() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    run()
