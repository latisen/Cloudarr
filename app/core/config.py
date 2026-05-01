"""Application settings and defaults."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLOUDARR_", extra="ignore")

    env: str = "development"
    db_url: str = "sqlite:///./cloudarr.db"
    log_level: str = "INFO"

    secret_key: str = "dev-secret"
    session_https_only: bool = False
    admin_user: str = "admin"
    admin_password: str = "admin"

    qbit_username: str = "sonarr"
    qbit_password: str = "sonarr-pass"
    qbit_require_auth: bool = True
    default_category: str = "sonarr"

    provider_name: str = "realdebrid"

    realdebrid_api_base: str = "https://api.real-debrid.com/rest/1.0"
    realdebrid_api_token: str = ""
    realdebrid_add_magnet_path: str = "/torrents/addMagnet"
    realdebrid_add_torrent_path: str = "/torrents/addTorrent"
    realdebrid_info_path: str = "/torrents/info"
    realdebrid_select_files_path: str = "/torrents/selectFiles"
    realdebrid_user_path: str = "/user"

    torbox_api_base: str = "https://api.torbox.app"
    torbox_api_key: str = ""
    torbox_torrents_path: str = "/v1/api/torrents/createtorrent"
    torbox_mylist_path: str = "/v1/api/torrents/mylist"
    torbox_health_path: str = "/v1/api/torrents/mylist"

    webdav_url: str = ""
    webdav_username: str = ""
    webdav_password: str = ""
    webdav_mount_path: str = "/mnt/torbox"
    symlink_staging_root: str = "/srv/torbox-arr/links"
    torbox_remote_root: str = "/"
    webdav_remote_root: str = "links"
    torrent_cache_dir: str = "/var/lib/cloudarr/torrents"

    refresh_max_attempts: int = Field(default=10, ge=1, le=100)
    refresh_retry_seconds: int = Field(default=10, ge=0, le=300)
    webdav_refresh_command: str = "rclone rc vfs/refresh recursive=true"
    webdav_remount_command: str = "systemctl restart torbox-rclone-mount.service"
    webdav_command_timeout_seconds: int = Field(default=20, ge=1, le=600)
    webdav_fallback_search_max_entries: int = Field(default=5000, ge=100, le=100000)

    poll_interval_seconds: int = Field(default=3, ge=3, le=600)
    max_submit_retries: int = Field(default=3, ge=1, le=10)
    provider_wait_timeout_seconds: int = Field(default=7200, ge=60, le=604800)
    enable_embedded_worker: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return singleton settings instance."""

    return Settings()
