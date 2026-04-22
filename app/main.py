"""FastAPI app bootstrap for Cloudarr API and dashboard."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.health import router as health_router
from app.api.routes.qbittorrent import router as qbittorrent_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.session import engine
from app.services.runtime import Runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    Base.metadata.create_all(bind=engine)

    runtime = Runtime(settings)
    app.state.runtime = runtime

    worker_task = asyncio.create_task(runtime.worker.run_forever())
    app.state.worker_task = worker_task
    try:
        yield
    finally:
        runtime.worker.stop()
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


app = FastAPI(title="Cloudarr", lifespan=lifespan)
settings = get_settings()

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.env == "production",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(qbittorrent_router)
app.include_router(dashboard_router)
app.include_router(health_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def run() -> None:
    """Entry point for local execution."""

    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=False)


if __name__ == "__main__":
    run()
