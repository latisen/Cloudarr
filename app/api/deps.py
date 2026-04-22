"""Shared FastAPI dependencies."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db


def db_session(db: Session = Depends(get_db)) -> Session:
    """Alias dependency for DB session."""

    return db
