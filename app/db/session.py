"""Database engine and session factory."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

connect_args: dict[str, object] = {}
if settings.db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.db_url, future=True, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Session:
    """Yield a DB session for FastAPI dependency injection."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
