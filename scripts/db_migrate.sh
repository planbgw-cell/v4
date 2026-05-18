#!/usr/bin/env bash
set -euo pipefail

# 184 -> 203 migration helper
# OTP(2FA) is handled by interactive ssh.

SRC_SSH_USER="${SRC_SSH_USER:-flairy}"
SRC_SSH_HOST="${SRC_SSH_HOST:-122.133.47.184}"
SRC_SSH_PORT="${SRC_SSH_PORT:-22}"

SRC_DB_HOST="${SRC_DB_HOST:-localhost}"
SRC_DB_PORT="${SRC_DB_PORT:-5432}"
SRC_DB_NAME="${SRC_DB_NAME:-flairy_v4}"
SRC_DB_USER="${SRC_DB_USER:-flairy_admin}"

DST_CONTAINER="${DST_CONTAINER:-flairy-db}"
DST_DB_NAME="${DST_DB_NAME:-flairy_v4}"
DST_DB_USER="${DST_DB_USER:-flairy_admin}"

DROP_RECREATE="${DROP_RECREATE:-false}"
SCHEMA_ONLY="${SCHEMA_ONLY:-false}"
DATA_ONLY="${DATA_ONLY:-false}"
DRY_RUN="${DRY_RUN:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --drop-recreate) DROP_RECREATE=true; shift ;;
    --schema-only) SCHEMA_ONLY=true; shift ;;
    --data-only) DATA_ONLY=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --src-db-user) SRC_DB_USER="$2"; shift 2 ;;
    --src-db-name) SRC_DB_NAME="$2"; shift 2 ;;
    --src-db-host) SRC_DB_HOST="$2"; shift 2 ;;
    --src-db-port) SRC_DB_PORT="$2"; shift 2 ;;
    --src-ssh-user) SRC_SSH_USER="$2"; shift 2 ;;
    --src-ssh-host) SRC_SSH_HOST="$2"; shift 2 ;;
    --src-ssh-port) SRC_SSH_PORT="$2"; shift 2 ;;
    --help|-h)
      cat <<USAGE
Usage: scripts/db_migrate.sh [options]
  --drop-recreate   Drop and recreate destination DB before restore
  --schema-only     Dump schema only
  --data-only       Dump data only
  --dry-run         Print commands without running
  --src-db-user U   Source DB user (default: flairy_admin)
  --src-db-name N   Source DB name (default: flairy_v4)
  --src-db-host H   Source DB host on 184 (default: localhost)
  --src-db-port P   Source DB port on 184 (default: 5432)
  --src-ssh-user U  Source SSH user (default: flairy)
  --src-ssh-host H  Source SSH host (default: 122.133.47.184)
  --src-ssh-port P  Source SSH port (default: 22)
USAGE
      exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1 ;;
  esac
done

for cmd in ssh docker; do
  command -v "$cmd" >/dev/null || { echo "Missing command: $cmd" >&2; exit 1; }
done

docker ps --format '{{.Names}}' | grep -qx "$DST_CONTAINER" || {
  echo "Destination container '$DST_CONTAINER' is not running." >&2
  exit 1
}

if [[ -z "${SRC_DB_PASSWORD:-}" ]]; then
  read -rsp "[184] Source DB password for ${SRC_DB_USER}: " SRC_DB_PASSWORD
  echo
fi

DUMP_FLAGS=(--no-owner --no-privileges --format=plain --encoding=UTF8)
[[ "$SCHEMA_ONLY" == "true" ]] && DUMP_FLAGS+=(--schema-only)
[[ "$DATA_ONLY" == "true" ]] && DUMP_FLAGS+=(--data-only)

REMOTE_DUMP_CMD="PGPASSWORD='${SRC_DB_PASSWORD}' pg_dump -h '${SRC_DB_HOST}' -p '${SRC_DB_PORT}' -U '${SRC_DB_USER}' '${SRC_DB_NAME}' ${DUMP_FLAGS[*]}"

if [[ "$DROP_RECREATE" == "true" ]]; then
  echo "Dropping and recreating destination DB '${DST_DB_NAME}' in container '${DST_CONTAINER}'..."
  docker exec "$DST_CONTAINER" psql -U "$DST_DB_USER" -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DST_DB_NAME}' AND pid <> pg_backend_pid();" || true
  docker exec "$DST_CONTAINER" psql -U "$DST_DB_USER" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"${DST_DB_NAME}\";"
  docker exec "$DST_CONTAINER" psql -U "$DST_DB_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${DST_DB_NAME}\";"
fi

echo "Source: ${SRC_SSH_USER}@${SRC_SSH_HOST}:${SRC_SSH_PORT} db=${SRC_DB_NAME}"
echo "Target: container=${DST_CONTAINER} db=${DST_DB_NAME} user=${DST_DB_USER}"

echo "This step will ask SSH password/OTP interactively if required."

PIPE_CMD="ssh -p '${SRC_SSH_PORT}' '${SRC_SSH_USER}@${SRC_SSH_HOST}' \"${REMOTE_DUMP_CMD}\" | docker exec -i '${DST_CONTAINER}' psql -U '${DST_DB_USER}' -d '${DST_DB_NAME}' -v ON_ERROR_STOP=1"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[DRY RUN] ${PIPE_CMD}"
  exit 0
fi

read -rp "Proceed with migration? [y/N] " yn
[[ "${yn}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

set -o pipefail
# shellcheck disable=SC2029
eval "$PIPE_CMD"

echo "Migration completed successfully."
