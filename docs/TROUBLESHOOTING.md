# Troubleshooting

## Sonarr Cannot Connect to qBittorrent Client

- Verify `cloudarr-api.service` is running.
- Test endpoint manually:
  - `curl http://127.0.0.1:8080/api/v2/app/version`
- Check firewall/reverse proxy.

## Jobs Stay in `WAITING_FOR_TORBOX`

- Verify `CLOUDARR_TORBOX_API_KEY`.
- Check `GET /api/health` torbox status.
- Inspect `Recent Events` dashboard page.

## Jobs Reach `TORBOX_READY` but Not `WEBDAV_VISIBLE`

- Check mount with `mount | grep /mnt/torbox`.
- Verify `torbox-rclone-mount.service` is active.
- Verify `CLOUDARR_WEBDAV_REFRESH_COMMAND` and `CLOUDARR_WEBDAV_REMOUNT_COMMAND`.
- Confirm remote path exists in mounted tree.

## Broken Symlinks

- Confirm mount is present and accessible.
- If mount changed, rerun refresh/remount and retry failed jobs.

## Dashboard Login Fails

- Validate `CLOUDARR_ADMIN_USER` and `CLOUDARR_ADMIN_PASSWORD` values in `/etc/cloudarr/cloudarr.env`.
- Restart API service after env changes.

## Database Lock Issues (SQLite)

- For high concurrency, migrate to PostgreSQL by setting `CLOUDARR_DB_URL`.
- Run Alembic migrations against PostgreSQL before switching services.
