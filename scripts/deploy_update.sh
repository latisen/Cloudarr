#!/usr/bin/env bash
set -euo pipefail

# Deploy updated Cloudarr code to /opt/cloudarr and restart services.
# Defaults can be overridden with environment variables:
#   SRC_DIR=/home/latis/Cloudarr APP_DIR=/opt/cloudarr sudo ./scripts/deploy_update.sh

SRC_DIR="${SRC_DIR:-/home/latis/Cloudarr}"
APP_DIR="${APP_DIR:-/opt/cloudarr}"
ENV_FILE="${ENV_FILE:-/etc/cloudarr/cloudarr.env}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
RUNTIME_USER="${RUNTIME_USER:-cloudarr}"
RUNTIME_GROUP="${RUNTIME_GROUP:-cloudarr}"

SERVICES=(
  torbox-rclone-mount.service
  cloudarr-api.service
  cloudarr-worker.service
)

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Source directory not found: $SRC_DIR"
  exit 1
fi

if [[ ! -f "$SRC_DIR/pyproject.toml" ]]; then
  echo "pyproject.toml not found in source: $SRC_DIR"
  exit 1
fi

mkdir -p "$APP_DIR"

if ! command -v rsync >/dev/null 2>&1; then
  echo "Installing rsync..."
  apt-get update
  apt-get install -y rsync
fi

echo "Syncing source from $SRC_DIR to $APP_DIR ..."
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude ".pytest_cache" \
  "$SRC_DIR/" "$APP_DIR/"

if [[ ! -d "$APP_DIR/.venv" ]]; then
  echo "Creating venv in $APP_DIR/.venv ..."
  if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
  else
    python3 -m venv "$APP_DIR/.venv"
  fi
fi

if [[ ! -x "$APP_DIR/.venv/bin/pip" ]]; then
  echo "pip missing in virtualenv, repairing with ensurepip ..."
  "$APP_DIR/.venv/bin/python" -m ensurepip --upgrade
fi

echo "Installing/updating Python package in editable mode ..."
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -e "$APP_DIR"

if [[ -f "$APP_DIR/alembic.ini" ]]; then
  echo "Running database migrations ..."
  (
    cd "$APP_DIR"
    "$APP_DIR/.venv/bin/alembic" upgrade head || true
  )
fi

if [[ -f "$APP_DIR/systemd/cloudarr-api.service" ]]; then
  cp "$APP_DIR/systemd/cloudarr-api.service" /etc/systemd/system/cloudarr-api.service
fi
if [[ -f "$APP_DIR/systemd/cloudarr-worker.service" ]]; then
  cp "$APP_DIR/systemd/cloudarr-worker.service" /etc/systemd/system/cloudarr-worker.service
fi
if [[ -f "$APP_DIR/systemd/torbox-rclone-mount.service" ]]; then
  cp "$APP_DIR/systemd/torbox-rclone-mount.service" /etc/systemd/system/torbox-rclone-mount.service
fi

if [[ -f "$ENV_FILE" ]]; then
  echo "Using env file: $ENV_FILE"
else
  echo "Warning: env file not found: $ENV_FILE"
fi

chown -R "$RUNTIME_USER:$RUNTIME_GROUP" "$APP_DIR"

echo "Reloading systemd and restarting services ..."
systemctl daemon-reload
for svc in "${SERVICES[@]}"; do
  systemctl restart "$svc"
done

for svc in "${SERVICES[@]}"; do
  systemctl --no-pager --full status "$svc" | sed -n '1,18p'
done

echo "Deploy complete."
