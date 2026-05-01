#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-0} -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/update.sh"
  exit 1
fi

APP_DIR="/opt/cloudarr"
RUN_USER="${SUDO_USER:-}"
if [[ -n "$RUN_USER" && "$RUN_USER" != "root" ]]; then
  SOURCE_DIR="$(eval echo "~$RUN_USER")/Cloudarr"
else
  SOURCE_DIR="$HOME/Cloudarr"
fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "Starting Cloudarr update..."

# 1. Pull latest code in user checkout
log "Pulling latest code in $SOURCE_DIR..."
if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  log "ERROR: Git checkout not found at $SOURCE_DIR"
  exit 1
fi

if [[ -n "$RUN_USER" && "$RUN_USER" != "root" ]]; then
  sudo -u "$RUN_USER" git -C "$SOURCE_DIR" pull --ff-only
else
  git -C "$SOURCE_DIR" pull --ff-only
fi

# 2. Sync checkout into /opt/cloudarr
log "Syncing code to $APP_DIR..."
cp -a "$SOURCE_DIR"/. "$APP_DIR"/

# 3. Clean Python bytecode cache
log "Cleaning Python cache..."
find "$APP_DIR" -name '*.pyc' -delete || true
find "$APP_DIR" -name '__pycache__' -type d -delete || true

# 4. Update Python dependencies (if needed)
log "Updating Python dependencies..."
"$APP_DIR/.venv/bin/pip" install -e "$APP_DIR" >/dev/null 2>&1 || {
  log "WARNING: pip install had issues, continuing anyway"
}

# 5. Fix permissions
log "Fixing permissions..."
chown -R cloudarr:cloudarr "$APP_DIR"

# 6. Restart services
log "Restarting Cloudarr services..."
systemctl restart cloudarr-api.service
systemctl restart cloudarr-worker.service

# Wait for services to stabilize
sleep 2

# 7. Check status
log "Checking service status..."
api_status=$(systemctl is-active cloudarr-api.service)
worker_status=$(systemctl is-active cloudarr-worker.service)

log "cloudarr-api.service: $api_status"
log "cloudarr-worker.service: $worker_status"

if [[ "$api_status" == "active" ]] && [[ "$worker_status" == "active" ]]; then
  log "✓ Update completed successfully!"
  exit 0
else
  log "✗ One or more services failed to start!"
  exit 1
fi
