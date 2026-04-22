# Ubuntu/Systemd Installation Guide

This guide covers deploying Cloudarr as native Ubuntu systemd services.

## Prerequisites

- Ubuntu 20.04+ with root or sudo access
- Python 3.12+
- rclone installed for WebDAV mounting
- Real-Debrid subscription and credentials

## Step 1: Clone Repository

```bash
git clone https://github.com/latisen/Cloudarr.git /opt/cloudarr
cd /opt/cloudarr
```

## Step 2: Create Virtual Environment and Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e .
```

## Step 3: Initialize Database

```bash
alembic upgrade head
```

## Step 4: Configure Environment

Create `/etc/cloudarr/cloudarr.env`:

```bash
sudo mkdir -p /etc/cloudarr
sudo tee /etc/cloudarr/cloudarr.env << 'EOF'
# Core
CLOUDARR_ENV=production
CLOUDARR_DB_URL=sqlite:////opt/cloudarr/cloudarr.db
CLOUDARR_LOG_LEVEL=INFO
CLOUDARR_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
CLOUDARR_ADMIN_USER=admin
CLOUDARR_ADMIN_PASSWORD=change-me

# Sonarr/qBittorrent shim
CLOUDARR_QBIT_USERNAME=sonarr
CLOUDARR_QBIT_PASSWORD=sonarr-pass
CLOUDARR_QBIT_REQUIRE_AUTH=true
CLOUDARR_DEFAULT_CATEGORY=sonarr

# Provider
CLOUDARR_PROVIDER_NAME=realdebrid

# Real-Debrid API
CLOUDARR_REALDEBRID_API_BASE=https://api.real-debrid.com/rest/1.0
CLOUDARR_REALDEBRID_API_TOKEN=<your-token>
CLOUDARR_REALDEBRID_ADD_MAGNET_PATH=/torrents/addMagnet
CLOUDARR_REALDEBRID_ADD_TORRENT_PATH=/torrents/addTorrent
CLOUDARR_REALDEBRID_INFO_PATH=/torrents/info
CLOUDARR_REALDEBRID_SELECT_FILES_PATH=/torrents/selectFiles
CLOUDARR_REALDEBRID_USER_PATH=/user

# WebDAV
CLOUDARR_WEBDAV_URL=https://dav.real-debrid.com/
CLOUDARR_WEBDAV_USERNAME=<your-real-debrid-username>
CLOUDARR_WEBDAV_PASSWORD=<your-real-debrid-password>
CLOUDARR_WEBDAV_MOUNT_PATH=/mnt/torbox
CLOUDARR_SYMLINK_STAGING_ROOT=/srv/torbox-arr/links
CLOUDARR_TORRENT_CACHE_DIR=/var/lib/cloudarr/torrents

# Refresh / remount
CLOUDARR_REFRESH_MAX_ATTEMPTS=12
CLOUDARR_REFRESH_RETRY_SECONDS=10
CLOUDARR_WEBDAV_REFRESH_COMMAND=rclone rc vfs/refresh recursive=true
CLOUDARR_WEBDAV_REMOUNT_COMMAND=systemctl restart torbox-rclone-mount.service

# Worker
CLOUDARR_POLL_INTERVAL_SECONDS=15
CLOUDARR_MAX_SUBMIT_RETRIES=3
EOF
```

Update the placeholder values with your Real-Debrid credentials.

## Step 5: Create Cloudarr User

```bash
sudo useradd -m -s /bin/bash cloudarr
sudo mkdir -p /srv/torbox-arr/links /var/lib/cloudarr/torrents
sudo chown -R cloudarr:cloudarr /opt/cloudarr /srv/torbox-arr /var/lib/cloudarr
sudo chmod 755 /srv/torbox-arr /mnt/torbox
```

## Step 6: Configure rclone

```bash
sudo mkdir -p /etc/rclone
sudo rclone config create realdebrid webdav url=https://dav.real-debrid.com/ vendor=other \
  username=<your-username> password=<your-password> --config /etc/rclone/rclone.conf
```

## Step 7: Install Systemd Services

```bash
sudo cp /opt/cloudarr/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## Step 8: Start Services

```bash
sudo systemctl enable cloudarr-api.service cloudarr-worker.service torbox-rclone-mount.service
sudo systemctl start cloudarr-api.service cloudarr-worker.service torbox-rclone-mount.service
```

Verify:

```bash
sudo systemctl status cloudarr-api.service
sudo systemctl status cloudarr-worker.service
sudo systemctl status torbox-rclone-mount.service
```

## Step 9: Configure Sonarr Download Client

1. In Sonarr, go to **Settings → Download Clients**
2. Add new **qBittorrent** client:
   - Name: `Cloudarr`
   - Host: `localhost` (or your server IP)
   - Port: `8080`
   - Username: `sonarr`
   - Password: `sonarr-pass`
   - Require Authentication: ✓

## Accessing Web Dashboard

Open browser to: `http://localhost:8080`

- Default user: `admin`
- Default password: `change-me` (set in `.env`)

## Checking Status

View API health:

```bash
curl http://localhost:8080/api/health
```

View worker logs:

```bash
journalctl -u cloudarr-worker.service -f
```

View full logs:

```bash
journalctl -u cloudarr-api.service -u cloudarr-worker.service -f
```

## Updating

To update Cloudarr after pulling new code:

```bash
cd /opt/cloudarr
git pull origin main
source .venv/bin/activate
pip install -e .
alembic upgrade head
sudo systemctl restart cloudarr-api.service cloudarr-worker.service
```

Or use the provided deployment script:

```bash
./scripts/deploy_update.sh
```

## Troubleshooting

### Services won't start

Check logs for errors:

```bash
journalctl -xeu cloudarr-api.service
journalctl -xeu cloudarr-worker.service
journalctl -xeu torbox-rclone-mount.service
```

### WebDAV mount not working

Verify rclone config:

```bash
sudo rclone --config /etc/rclone/rclone.conf ls realdebrid:
```

Check mount:

```bash
mount | grep /mnt/torbox
ls /mnt/torbox
```

### Database permission issues

Ensure cloudarr user owns the database:

```bash
sudo chown cloudarr:cloudarr /opt/cloudarr/cloudarr.db
```

### Too many open files

Increase file descriptor limit in systemd:

```bash
sudo nano /etc/systemd/system/cloudarr-*.service
# Add: LimitNOFILE=65535
sudo systemctl daemon-reload
sudo systemctl restart cloudarr-*.service
```
