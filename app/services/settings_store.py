"""Persistent settings and encrypted secret store."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.models.setting import AppSetting, SecretSetting


class SettingsStore:
    """Stores mutable settings in DB while keeping secrets encrypted."""

    def __init__(self, db: Session, app_secret: str) -> None:
        self.db = db
        digest = hashlib.sha256(app_secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.db.get(AppSetting, key)
        return row.value if row else default

    def set(self, key: str, value: str) -> None:
        row = self.db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=value)
            self.db.add(row)
        else:
            row.value = value
        self.db.commit()

    def get_secret(self, key: str) -> str | None:
        row = self.db.get(SecretSetting, key)
        if not row:
            return None
        return self._fernet.decrypt(row.encrypted_value.encode("utf-8")).decode("utf-8")

    def set_secret(self, key: str, value: str) -> None:
        encrypted = self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        row = self.db.get(SecretSetting, key)
        if row is None:
            row = SecretSetting(key=key, encrypted_value=encrypted)
            self.db.add(row)
        else:
            row.encrypted_value = encrypted
        self.db.commit()
