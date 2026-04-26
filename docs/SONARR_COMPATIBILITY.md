# Sonarr Compatibility Notes

Cloudarr emulates the qBittorrent Web API subset Sonarr commonly uses.

Current default backend provider is Real-Debrid for torrent submission/status.

Important limitation: Real-Debrid's official API does not expose a WebDAV filesystem, so Cloudarr cannot complete its symlink-only import flow unless you also provide a separate mountable mirror for completed files.

## Implemented qBittorrent Shim Endpoints

- `POST /api/v2/auth/login`
- `POST /api/v2/auth/logout`
- `GET /api/v2/app/version`
- `GET /api/v2/app/webapiVersion`
- `POST /api/v2/torrents/add`
- `GET /api/v2/torrents/info`
- `GET /api/v2/torrents/properties`
- `GET /api/v2/sync/maindata`
- `POST /api/v2/torrents/delete`

## Sonarr Download Client Configuration

1. In Sonarr: Settings > Download Clients > Add > qBittorrent.
2. Host: Cloudarr server IP/hostname.
3. Port: `8080` (or your reverse-proxy port).
4. Username/password: values from `CLOUDARR_QBIT_USERNAME` / `CLOUDARR_QBIT_PASSWORD`.
5. Category: match `CLOUDARR_DEFAULT_CATEGORY` (default `sonarr`).
6. Completed Download Handling: enabled in Sonarr.

## Path Behavior

- Cloudarr reports a completed path under `CLOUDARR_SYMLINK_STAGING_ROOT`.
- Files in that directory are symlinks to `CLOUDARR_WEBDAV_MOUNT_PATH`.
- Sonarr imports from symlink paths; media payload remains on WebDAV mount.

## Extension Points

- qBittorrent shim can be extended with additional API endpoints if your Sonarr version requires them.
- Torrent file upload handling currently creates a pseudo-magnet identity and marks extension points in route code.
