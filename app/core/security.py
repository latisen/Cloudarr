"""Authentication and session security helpers."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException, Request, status
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class DashboardAuth:
    """Session-based auth helper for dashboard routes."""

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def get_csrf_token(request: Request) -> str:
        token = request.session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            request.session["csrf_token"] = token
        return token

    @staticmethod
    def validate_csrf(request: Request, submitted_token: str) -> None:
        token = request.session.get("csrf_token")
        if not token or token != submitted_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")

    @staticmethod
    def require_session(request: Request) -> dict[str, Any]:
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return user
