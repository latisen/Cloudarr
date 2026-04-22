"""Runtime dependency container."""

from __future__ import annotations

from app.core.config import Settings
from app.db.session import SessionLocal
from app.services.mount_manager import WebDavMountManager
from app.services.provider.torbox import TorBoxProvider
from app.services.settings_store import SettingsStore
from app.services.symlink_manager import SymlinkManager
from app.services.worker import JobWorker


class Runtime:
    """Application runtime singletons."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._hydrate_settings_from_db()
        self.provider = TorBoxProvider(settings)
        self.mount_manager = WebDavMountManager(settings)
        self.symlink_manager = SymlinkManager(settings.webdav_mount_path, settings.symlink_staging_root)
        self.worker = JobWorker(
            db_factory=SessionLocal,
            settings=settings,
            provider=self.provider,
            mount_manager=self.mount_manager,
            symlink_manager=self.symlink_manager,
        )

    def _hydrate_settings_from_db(self) -> None:
        db = SessionLocal()
        try:
            store = SettingsStore(db, self.settings.secret_key)
            self.settings.torbox_api_key = store.get_secret("torbox_api_key") or self.settings.torbox_api_key
            self.settings.webdav_password = store.get_secret("webdav_password") or self.settings.webdav_password
            self.settings.qbit_password = store.get_secret("qbit_password") or self.settings.qbit_password

            self.settings.webdav_url = store.get("webdav_url", self.settings.webdav_url) or self.settings.webdav_url
            self.settings.webdav_username = (
                store.get("webdav_username", self.settings.webdav_username) or self.settings.webdav_username
            )
            self.settings.webdav_mount_path = (
                store.get("webdav_mount_path", self.settings.webdav_mount_path) or self.settings.webdav_mount_path
            )
            self.settings.symlink_staging_root = (
                store.get("symlink_staging_root", self.settings.symlink_staging_root) or self.settings.symlink_staging_root
            )
            self.settings.webdav_refresh_command = (
                store.get("webdav_refresh_command", self.settings.webdav_refresh_command)
                or self.settings.webdav_refresh_command
            )
            self.settings.webdav_remount_command = (
                store.get("webdav_remount_command", self.settings.webdav_remount_command)
                or self.settings.webdav_remount_command
            )
            self.settings.log_level = store.get("log_level", self.settings.log_level) or self.settings.log_level
            self.settings.qbit_username = store.get("qbit_username", self.settings.qbit_username) or self.settings.qbit_username
            qbit_require_auth = store.get("qbit_require_auth")
            if qbit_require_auth is not None:
                self.settings.qbit_require_auth = qbit_require_auth.lower() in {"1", "true", "yes", "on"}

            poll_interval = store.get("poll_interval_seconds")
            if poll_interval is not None and poll_interval.isdigit():
                self.settings.poll_interval_seconds = int(poll_interval)
        finally:
            db.close()
