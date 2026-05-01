#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-0} -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/install_media_stack_ubuntu.sh"
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="/opt/cloudarr"
ENV_DIR="/etc/cloudarr"
RCLONE_DIR="/etc/rclone"

SONARR_USER="sonarr"
RADARR_USER="radarr"
CLOUDARR_USER="cloudarr"

MEDIA_ROOT="/srv/media"
DOWNLOAD_ROOT="${MEDIA_ROOT}/data/downloads"
SONARR_DOWNLOADS="${DOWNLOAD_ROOT}/sonarr"
RADARR_DOWNLOADS="${DOWNLOAD_ROOT}/radarr"
MOUNT_ROOT="${MEDIA_ROOT}/mnt/debrid"

SONARR_VERSION_URL="https://services.sonarr.tv/v1/download/main/latest?version=4&os=linux&arch=x64"
RADARR_VERSION_URL="https://radarr.servarr.com/v1/update/master/updatefile?os=linux&runtime=netcore&arch=x64"

log() {
  echo "[install-media-stack] $*"
}

require_repo_file() {
  if [[ ! -f "$REPO_DIR/pyproject.toml" ]]; then
    echo "Cloudarr repository not found at $REPO_DIR"
    echo "Run this script from inside a Cloudarr checkout."
    exit 1
  fi
}

install_packages() {
  log "Installing required packages"
  apt-get update
  apt-get install -y \
    curl \
    wget \
    ca-certificates \
    tar \
    unzip \
    sqlite3 \
    acl \
    rclone \
    python3 \
    python3-venv \
    python3-pip \
    mediainfo \
    libchromaprint-tools
}

download_archive() {
  local url="$1"
  local out="$2"
  local name="$3"

  log "Downloading ${name}"
  if ! curl -fL --retry 5 --retry-delay 2 --connect-timeout 20 -A "Cloudarr Installer" "$url" -o "$out"; then
    echo "Failed downloading ${name} from: ${url}"
    exit 1
  fi
}

extract_archive() {
  local archive="$1"
  local destination="$2"
  local name="$3"

  rm -rf "$destination"
  mkdir -p "$destination"

  if tar -tzf "$archive" >/dev/null 2>&1; then
    tar -xzf "$archive" -C "$destination" --strip-components=1
    return
  fi

  if unzip -tqq "$archive" >/dev/null 2>&1; then
    unzip -q "$archive" -d "$destination"
    if [[ -d "$destination/Sonarr" ]]; then
      mv "$destination/Sonarr"/* "$destination"/
      rmdir "$destination/Sonarr" || true
    fi
    if [[ -d "$destination/Radarr" ]]; then
      mv "$destination/Radarr"/* "$destination"/
      rmdir "$destination/Radarr" || true
    fi
    return
  fi

  echo "Downloaded ${name} is not a valid tar.gz or zip archive."
  echo "First bytes of file:"
  head -c 200 "$archive" | tr -dc '[:print:]\n' || true
  echo
  exit 1
}

ensure_users() {
  log "Ensuring service users"
  id -u "$SONARR_USER" >/dev/null 2>&1 || useradd --system --create-home --home /var/lib/sonarr --shell /usr/sbin/nologin "$SONARR_USER"
  id -u "$RADARR_USER" >/dev/null 2>&1 || useradd --system --create-home --home /var/lib/radarr --shell /usr/sbin/nologin "$RADARR_USER"
  id -u "$CLOUDARR_USER" >/dev/null 2>&1 || useradd --system --create-home --home /opt/cloudarr --shell /usr/sbin/nologin "$CLOUDARR_USER"
}

prepare_paths() {
  log "Preparing filesystem paths"
  mkdir -p "$MEDIA_ROOT/config/sonarr" "$MEDIA_ROOT/config/radarr"
  mkdir -p "$SONARR_DOWNLOADS" "$RADARR_DOWNLOADS"
  mkdir -p "$MOUNT_ROOT" "$MOUNT_ROOT/imports"
  mkdir -p "$APP_DIR" "$ENV_DIR" "$RCLONE_DIR" /var/lib/cloudarr/torrents

  chown -R "$SONARR_USER":"$SONARR_USER" "$MEDIA_ROOT/config/sonarr"
  chown -R "$RADARR_USER":"$RADARR_USER" "$MEDIA_ROOT/config/radarr"
  chown -R "$CLOUDARR_USER":"$CLOUDARR_USER" "$APP_DIR" "$SONARR_DOWNLOADS" "$RADARR_DOWNLOADS" "$MOUNT_ROOT" /var/lib/cloudarr

  chmod 755 "$MEDIA_ROOT" "$DOWNLOAD_ROOT" "$SONARR_DOWNLOADS" "$RADARR_DOWNLOADS" "$MOUNT_ROOT"
  setfacl -Rm u:${SONARR_USER}:rwx,u:${RADARR_USER}:rwx,u:${CLOUDARR_USER}:rwx "$DOWNLOAD_ROOT" || true
  setfacl -Rm d:u:${SONARR_USER}:rwx,d:u:${RADARR_USER}:rwx,d:u:${CLOUDARR_USER}:rwx "$DOWNLOAD_ROOT" || true
}

install_sonarr() {
  log "Installing Sonarr"
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  download_archive "$SONARR_VERSION_URL" "$tmp/sonarr.archive" "Sonarr"
  extract_archive "$tmp/sonarr.archive" "/opt/Sonarr" "Sonarr"
  chown -R "$SONARR_USER":"$SONARR_USER" /opt/Sonarr

  cat >/etc/systemd/system/sonarr.service <<'EOF'
[Unit]
Description=Sonarr Daemon
After=network.target

[Service]
User=sonarr
Group=sonarr
Type=simple
ExecStart=/opt/Sonarr/Sonarr -nobrowser -data=/srv/media/config/sonarr
TimeoutStopSec=20
KillMode=process
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
}

install_radarr() {
  log "Installing Radarr"
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  download_archive "$RADARR_VERSION_URL" "$tmp/radarr.archive" "Radarr"
  extract_archive "$tmp/radarr.archive" "/opt/Radarr" "Radarr"
  chown -R "$RADARR_USER":"$RADARR_USER" /opt/Radarr

  cat >/etc/systemd/system/radarr.service <<'EOF'
[Unit]
Description=Radarr Daemon
After=network.target

[Service]
User=radarr
Group=radarr
Type=simple
ExecStart=/opt/Radarr/Radarr -nobrowser -data=/srv/media/config/radarr
TimeoutStopSec=20
KillMode=process
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
}

install_cloudarr() {
  log "Installing Cloudarr"
  cp -a "$REPO_DIR"/. "$APP_DIR"/
  chown -R "$CLOUDARR_USER":"$CLOUDARR_USER" "$APP_DIR"

  if [[ ! -d "$APP_DIR/.venv" ]]; then
    python3 -m venv "$APP_DIR/.venv"
  fi
  "$APP_DIR/.venv/bin/pip" install --upgrade pip
  "$APP_DIR/.venv/bin/pip" install -e "$APP_DIR"

  if [[ ! -f "$ENV_DIR/cloudarr.env" ]]; then
    cat >"$ENV_DIR/cloudarr.env" <<EOF
CLOUDARR_ENV=production
CLOUDARR_DB_URL=sqlite:////opt/cloudarr/cloudarr.db
CLOUDARR_LOG_LEVEL=INFO
CLOUDARR_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
CLOUDARR_ADMIN_USER=admin
CLOUDARR_ADMIN_PASSWORD=change-me

CLOUDARR_QBIT_USERNAME=sonarr
CLOUDARR_QBIT_PASSWORD=sonarr-pass
CLOUDARR_QBIT_REQUIRE_AUTH=true
CLOUDARR_DEFAULT_CATEGORY=sonarr

CLOUDARR_PROVIDER_NAME=realdebrid
CLOUDARR_REALDEBRID_API_BASE=https://api.real-debrid.com/rest/1.0
CLOUDARR_REALDEBRID_API_TOKEN=

CLOUDARR_WEBDAV_URL=https://dav.real-debrid.com/
CLOUDARR_WEBDAV_USERNAME=
CLOUDARR_WEBDAV_PASSWORD=
CLOUDARR_WEBDAV_MOUNT_PATH=/mnt/debrid
CLOUDARR_WEBDAV_REMOTE_ROOT=torrents
CLOUDARR_SYMLINK_STAGING_ROOT=${SONARR_DOWNLOADS}
CLOUDARR_TORRENT_CACHE_DIR=/var/lib/cloudarr/torrents

CLOUDARR_WEBDAV_REFRESH_COMMAND=rclone rc vfs/refresh recursive=true
CLOUDARR_WEBDAV_REMOUNT_COMMAND=sudo systemctl restart debrid-rclone-mount.service
CLOUDARR_POLL_INTERVAL_SECONDS=15
CLOUDARR_MAX_SUBMIT_RETRIES=6
CLOUDARR_ENABLE_EMBEDDED_WORKER=false
EOF
  fi

  cp "$APP_DIR/systemd/cloudarr-api.service" /etc/systemd/system/cloudarr-api.service
  cp "$APP_DIR/systemd/cloudarr-worker.service" /etc/systemd/system/cloudarr-worker.service

  sed -i 's#/mnt/torbox#/mnt/debrid#g' /etc/systemd/system/cloudarr-api.service
  sed -i 's#/mnt/torbox#/mnt/debrid#g' /etc/systemd/system/cloudarr-worker.service
  sed -i 's#/srv/torbox-arr#/srv/media/data/downloads#g' /etc/systemd/system/cloudarr-api.service
  sed -i 's#/srv/torbox-arr#/srv/media/data/downloads#g' /etc/systemd/system/cloudarr-worker.service
}

install_rclone_mount_service() {
  log "Installing rclone mount service"
  cat >/etc/systemd/system/debrid-rclone-mount.service <<'EOF'
[Unit]
Description=Debrid WebDAV rclone mount
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=cloudarr
Group=cloudarr
ExecStart=/usr/bin/rclone mount realdebrid: /mnt/debrid --config /etc/rclone/rclone.conf --allow-other --dir-cache-time 30s --vfs-cache-mode off --poll-interval 15s --rc --rc-no-auth
ExecStop=/bin/fusermount -u /mnt/debrid
Restart=always
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

  cat >/etc/fuse.conf <<'EOF'
user_allow_other
EOF

  if [[ ! -f /etc/rclone/rclone.conf ]]; then
    cat >/etc/rclone/rclone.conf <<'EOF'
[realdebrid]
type = webdav
url = https://dav.real-debrid.com/
vendor = other
user =
pass =
EOF
    chown root:root /etc/rclone/rclone.conf
    chmod 600 /etc/rclone/rclone.conf
  fi
}

install_sudoers_for_dashboard() {
  log "Configuring sudoers for dashboard service control"
  cat >/etc/sudoers.d/cloudarr-services <<'EOF'
cloudarr ALL=(root) NOPASSWD: /bin/systemctl restart sonarr.service
cloudarr ALL=(root) NOPASSWD: /bin/systemctl restart radarr.service
cloudarr ALL=(root) NOPASSWD: /bin/systemctl restart cloudarr-api.service
cloudarr ALL=(root) NOPASSWD: /bin/systemctl restart cloudarr-worker.service
cloudarr ALL=(root) NOPASSWD: /bin/systemctl restart debrid-rclone-mount.service
cloudarr ALL=(root) NOPASSWD: /bin/systemctl is-active sonarr.service
cloudarr ALL=(root) NOPASSWD: /bin/systemctl is-active radarr.service
cloudarr ALL=(root) NOPASSWD: /bin/systemctl is-active cloudarr-api.service
cloudarr ALL=(root) NOPASSWD: /bin/systemctl is-active cloudarr-worker.service
cloudarr ALL=(root) NOPASSWD: /bin/systemctl is-active debrid-rclone-mount.service
EOF
  chmod 440 /etc/sudoers.d/cloudarr-services
}

enable_services() {
  log "Enabling and starting services"
  systemctl daemon-reload
  systemctl enable sonarr.service radarr.service debrid-rclone-mount.service cloudarr-api.service cloudarr-worker.service

  local mount_ready="false"
  if rclone --config /etc/rclone/rclone.conf listremotes 2>/dev/null | grep -q '^realdebrid:$'; then
    if systemctl restart debrid-rclone-mount.service; then
      mount_ready="true"
    else
      log "WARNING: debrid-rclone-mount.service failed to start."
      log "Check: systemctl status debrid-rclone-mount.service"
      log "Check: journalctl -xeu debrid-rclone-mount.service"
    fi
  else
    log "WARNING: rclone remote 'realdebrid' is missing in /etc/rclone/rclone.conf"
    log "Create it and run: sudo systemctl restart debrid-rclone-mount.service"
  fi

  systemctl restart sonarr.service radarr.service cloudarr-api.service cloudarr-worker.service

  if [[ "$mount_ready" != "true" ]]; then
    log "WARNING: Core services are running, but WebDAV mount is not active yet."
  fi
}

print_next_steps() {
  cat <<EOF

Installation complete.

Next steps:
1. Configure /etc/rclone/rclone.conf with a [realdebrid] WebDAV remote.
2. Edit /etc/cloudarr/cloudarr.env for API keys and credentials.
3. Restart services:
   sudo systemctl restart debrid-rclone-mount.service cloudarr-api.service cloudarr-worker.service sonarr.service radarr.service
4. Open:
   Sonarr: http://<server-ip>:8989
   Radarr: http://<server-ip>:7878
   Cloudarr: http://<server-ip>:8080

EOF
}

require_repo_file
install_packages
ensure_users
prepare_paths
install_sonarr
install_radarr
install_cloudarr
install_rclone_mount_service
install_sudoers_for_dashboard
enable_services
print_next_steps
