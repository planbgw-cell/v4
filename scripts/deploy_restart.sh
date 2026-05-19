#!/usr/bin/env bash
# Pull latest code and restart gunicorn so workers load updated Python modules.
# Usage: ./scripts/deploy_restart.sh [git remote branch]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BRANCH="${2:-main}"
REMOTE="${1:-origin}"

echo "[deploy] git pull ${REMOTE} ${BRANCH}"
git pull "$REMOTE" "$BRANCH"

echo "[deploy] restart flairy_v4.service"
sudo systemctl restart flairy_v4.service
sleep 2

if systemctl is-active --quiet flairy_v4.service; then
  echo "[deploy] OK: flairy_v4 is active"
  systemctl show flairy_v4.service -p ActiveEnterTimestamp --value
else
  echo "[deploy] ERROR: flairy_v4 failed to start" >&2
  systemctl status flairy_v4.service --no-pager || true
  exit 1
fi

# Sanity: filter concat merge path present on disk
if grep -q 'filter concat' "$ROOT/engine/video_engine.py"; then
  echo "[deploy] OK: video_engine has filter concat merge"
else
  echo "[deploy] WARN: filter concat not found in video_engine.py" >&2
fi
