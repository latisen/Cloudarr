#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/cloudarr
ENV_DIR=/etc/cloudarr
SERVICE_DIR=/etc/systemd/system
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

apt-get update
apt-get install -y python3.12 python3.12-venv python3-pip rclone

id -u cloudarr >/dev/null 2>&1 || useradd --system --home /opt/cloudarr --shell /usr/sbin/nologin cloudarr
mkdir -p "$APP_DIR" "$ENV_DIR" /srv/torbox-arr/links /mnt/torbox
chown -R cloudarr:cloudarr "$APP_DIR" /srv/torbox-arr /mnt/torbox

if [[ ! -f "$REPO_DIR/pyproject.toml" ]]; then
  echo "Could not find pyproject.toml in source repository: $REPO_DIR"
  echo "Run this installer from a valid Cloudarr checkout."
  exit 1
fi

if [[ ! -d "$APP_DIR/.venv" ]]; then
  python3.12 -m venv "$APP_DIR/.venv"
fi

cp -a "$REPO_DIR"/. "$APP_DIR"/

if [[ ! -f "$APP_DIR/pyproject.toml" ]]; then
  echo "Install copy failed: $APP_DIR/pyproject.toml not found"
  exit 1
fi

chown -R cloudarr:cloudarr "$APP_DIR"

cd "$APP_DIR"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -e .

if [[ ! -f "$ENV_DIR/cloudarr.env" ]]; then
  cp .env.example "$ENV_DIR/cloudarr.env"
fi

cp systemd/cloudarr-api.service "$SERVICE_DIR/cloudarr-api.service"
cp systemd/cloudarr-worker.service "$SERVICE_DIR/cloudarr-worker.service"
cp systemd/torbox-rclone-mount.service "$SERVICE_DIR/torbox-rclone-mount.service"

systemctl daemon-reload
systemctl enable torbox-rclone-mount.service cloudarr-api.service cloudarr-worker.service

echo "Installed. Edit /etc/cloudarr/cloudarr.env and /etc/rclone/rclone.conf, then run:"
echo "For Real-Debrid, note that the official API does not provide WebDAV; the mount service is only useful if you supply an external mountable mirror."
echo "  systemctl restart torbox-rclone-mount.service cloudarr-api.service cloudarr-worker.service"
