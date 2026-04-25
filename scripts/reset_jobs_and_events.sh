#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="media-system"
TARGET="deploy/cloudarr-worker"
DB_PATH="/config/cloudarr.db"

usage() {
  cat <<'EOF'
Usage: scripts/reset_jobs_and_events.sh [options]

Options:
  -n, --namespace <namespace>   Kubernetes namespace (default: media-system)
  -t, --target <resource>       kubectl exec target (default: deploy/cloudarr-worker)
  -d, --db-path <path>          SQLite DB path inside container (default: /config/cloudarr.db)
  -h, --help                    Show this help

Example:
  scripts/reset_jobs_and_events.sh
  scripts/reset_jobs_and_events.sh --namespace media-system --target deploy/cloudarr-worker
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    -t|--target)
      TARGET="$2"
      shift 2
      ;;
    -d|--db-path)
      DB_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

echo "Resetting jobs and events in namespace=${NAMESPACE}, target=${TARGET}, db=${DB_PATH}"

kubectl -n "${NAMESPACE}" exec "${TARGET}" -- sh -lc "python - <<'PY'
import sqlite3

db_path = '${DB_PATH}'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute('PRAGMA foreign_keys=ON')
cur.execute('BEGIN')
cur.execute('DELETE FROM job_events')
cur.execute('DELETE FROM jobs')
conn.commit()

cur.execute('SELECT COUNT(*) FROM jobs')
jobs = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM job_events')
events = cur.fetchone()[0]

print(f'jobs={jobs} events={events}')
PY"

echo "Done."