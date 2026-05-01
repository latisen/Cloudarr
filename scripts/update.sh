#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-0} -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/update.sh"
  exit 1
fi

APP_DIR="/opt/cloudarr"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "Starting Cloudarr update..."

# 1. Pull latest code
log "Pulling latest code from git..."
cd "$APP_DIR"
git pull

# 2. Clean Python bytecode cache
log "Cleaning Python cache..."
find "$APP_DIR" -name '*.pyc' -delete || true
find "$APP_DIR" -name '__pycache__' -type d -delete || true

# 3. Update Python dependencies (if needed)
log "Updating Python dependencies..."
"$APP_DIR/.venv/bin/pip" install -e "$APP_DIR" >/dev/null 2>&1 || {
  log "WARNING: pip install had issues, continuing anyway"
}

# 4. Fix permissions
log "Fixing permissions..."
chown -R cloudarr:cloudarr "$APP_DIR"

# 5. Restart services
log "Restarting Cloudarr services..."
systemctl restart cloudarr-api.service
systemctl restart cloudarr-worker.service

# Wait for services to stabilize
sleep 2

# 6. Check status
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
