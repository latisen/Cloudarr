# Cloudarr

Cloudarr is a production-focused service that presents itself to Sonarr as a qBittorrent-like download client while using a debrid backend provider.

**Deployment Options:**
- **Systemd/Ubuntu**: Native systemd services for direct deployment
- **Kubernetes**: Docker-based deployment for Kubernetes clusters

Current default provider: Real-Debrid for torrent control and polling.

Core principle: media payload is never copied or downloaded locally by Cloudarr. Completed imports are exposed through symlink-only staging paths that point at mounted WebDAV content.

Real-Debrid integration: The system uses Real-Debrid's REST API (`https://api.real-debrid.com/rest/1.0`) for torrent management and their WebDAV filesystem (`https://dav.real-debrid.com/`) for file mounting. Use your Real-Debrid credentials for WebDAV authentication.

## Deployment Guides

- **[Ubuntu/Systemd Guide](docs/UBUNTU_INSTALLATION.md)** - Traditional systemd deployment
- **[Kubernetes Guide](docs/KUBERNETES_DEPLOYMENT.md)** - Docker + Kubernetes deployment

## Final Project Structure

```text
.
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py
├── app/
│   ├── api/
│   │   ├── deps.py
│   │   └── routes/
│   │       ├── dashboard.py
│   │       ├── health.py
│   │       └── qbittorrent.py
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── security.py
│   ├── db/
│   │   ├── base.py
│   │   └── session.py
│   ├── models/
│   │   ├── enums.py
│   │   ├── job.py
│   │   └── setting.py
│   ├── services/
│   │   ├── provider/
│   │   │   ├── base.py
│   │   │   ├── realdebrid.py
│   │   │   └── torbox.py
│   │   ├── health.py
│   │   ├── job_service.py
│   │   ├── mount_manager.py
│   │   ├── runtime.py
│   │   ├── settings_store.py
│   │   ├── state_machine.py
│   │   ├── symlink_manager.py
│   │   └── worker.py
│   ├── static/
│   │   └── style.css
│   ├── templates/
│   │   ├── base.html
│   │   ├── events.html
│   │   ├── health.html
│   │   ├── jobs.html
│   │   ├── login.html
│   │   └── settings.html
│   ├── main.py
│   └── worker_main.py
├── docs/
│   ├── SONARR_COMPATIBILITY.md
│   └── TROUBLESHOOTING.md
├── scripts/
│   └── install_ubuntu.sh
├── systemd/
│   ├── cloudarr-api.service
│   ├── cloudarr-worker.service
│   └── torbox-rclone-mount.service
├── tests/
│   ├── conftest.py
│   ├── test_mount_refresh.py
│   ├── test_no_copy_paths.py
│   ├── test_qbittorrent_shim.py
│   ├── test_restart_recovery.py
│   ├── test_state_machine.py
│   └── test_symlink_only.py
├── .env.example
├── alembic.ini
├── pyproject.toml
└── requirements.txt
```

## Architecture Summary

1. Sonarr talks to Cloudarr using qBittorrent Web API-compatible routes (`/api/v2/...`).
2. Incoming magnet/torrent requests become persisted jobs in SQLAlchemy.
3. Worker process submits jobs to the configured provider and polls readiness.
4. When a provider reports ready and a mountable path exists, Cloudarr forces WebDAV refresh/remount logic and verifies path visibility.
5. Cloudarr creates symlink-only export directories under staging root (`/srv/torbox-arr/links/...`).
6. Sonarr sees completed download paths from the shim and imports from symlink paths.

## qBittorrent Compatibility Scope

Implemented routes:

- `POST /api/v2/auth/login`
- `POST /api/v2/auth/logout`
- `GET /api/v2/app/version`
- `GET /api/v2/app/webapiVersion`
- `POST /api/v2/torrents/add`
- `GET /api/v2/torrents/info`
- `GET /api/v2/torrents/files`
- `GET /api/v2/torrents/properties`
- `GET /api/v2/sync/maindata`
- `POST /api/v2/torrents/delete`

See `docs/SONARR_COMPATIBILITY.md` for Sonarr setup details.

## Provider Notes

- `realdebrid` is the default provider and uses the official Real-Debrid REST API.
- Real-Debrid does not expose WebDAV in the official API documentation.
- Because of that, Real-Debrid jobs can be submitted and monitored, but symlink-only import will stop once the torrent is ready unless you supply a separate mountable filesystem that mirrors those completed files.

## Job State Machine

- `RECEIVED_FROM_SONARR`
- `VALIDATING`
- `SUBMITTED_TO_TORBOX`
- `WAITING_FOR_TORBOX`
- `TORBOX_READY`
- `REFRESHING_WEBDAV`
- `WEBDAV_VISIBLE`
- `CREATING_SYMLINKS`
- `READY_FOR_IMPORT`
- `IMPORTED_OPTIONAL_DETECTED`
- `FAILED`
- `NEEDS_ATTENTION`

Transitions are validated in `app/services/state_machine.py` and persisted in `job_events`.

## Security

- Dashboard uses authenticated session login (`/login`).
- CSRF token validation for form posts.
- Secrets can be stored encrypted at rest via `secret_settings`.
- qBittorrent shim auth can be required via environment settings.
- Credentials and API keys are not intentionally logged.

## Ubuntu Installation (Primary Target)

### Quick Install

From repository root:

```bash
sudo bash scripts/install_ubuntu.sh
```

Then edit:

- `/etc/cloudarr/cloudarr.env`
- `/etc/rclone/rclone.conf`

Enable/restart services:

```bash
sudo systemctl daemon-reload
sudo systemctl restart torbox-rclone-mount.service cloudarr-api.service cloudarr-worker.service
sudo systemctl status torbox-rclone-mount.service cloudarr-api.service cloudarr-worker.service
```

### Manual Install

1. Install dependencies:

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip rclone
```

2. Create runtime user and folders:

```bash
sudo useradd --system --home /opt/cloudarr --shell /usr/sbin/nologin cloudarr || true
sudo mkdir -p /opt/cloudarr /etc/cloudarr /srv/torbox-arr/links /mnt/torbox
sudo chown -R cloudarr:cloudarr /opt/cloudarr /srv/torbox-arr /mnt/torbox
```

3. Install Python app:

```bash
sudo cp -r . /opt/cloudarr
cd /opt/cloudarr
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

4. Configure env:

```bash
sudo cp .env.example /etc/cloudarr/cloudarr.env
sudoedit /etc/cloudarr/cloudarr.env
```

5. Configure a mountable WebDAV remote in `/etc/rclone/rclone.conf` only if you have an external filesystem mirror for completed content.

6. Install systemd unit files:

```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable torbox-rclone-mount.service cloudarr-api.service cloudarr-worker.service
sudo systemctl start torbox-rclone-mount.service cloudarr-api.service cloudarr-worker.service
```

## Database and Migrations

Initialize migration schema:

```bash
alembic upgrade head
```

Default DB is SQLite (`cloudarr.db`), configurable through `CLOUDARR_DB_URL`.

## Running in Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

In a second shell:

```bash
python -m app.worker_main
```

## Dashboard

- `GET /login` for admin authentication.
- `GET /` jobs view.
- `GET /settings` mutable operational settings.
- `GET /health` operational status.
- `GET /events` recent event stream.

## Health Endpoint

- `GET /api/health`

Reports DB status, mount status, TorBox API status, worker state, and last refresh success.

## Reliability Notes

- Job states persist in DB and survive restart.
- Worker re-reads active jobs on every tick.
- Refresh/remount retries are configurable.
- Stale WebDAV visibility is handled explicitly before symlink creation.
- Broken symlink scan utility exists in symlink manager.

## Non-Goals Enforced

- No media download path in Cloudarr runtime logic.
- No copy/hardlink strategy for media payload.
- Export is symlink-only to mounted WebDAV content.

## Testing

Run:

```bash
pytest
```

Coverage focus:

- qBittorrent compatibility behavior
- state transition validation
- symlink-only path behavior
- WebDAV refresh retries
- restart recovery for non-terminal jobs

## Troubleshooting

See `docs/TROUBLESHOOTING.md`.