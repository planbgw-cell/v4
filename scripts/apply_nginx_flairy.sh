#!/bin/bash
# www.flairy.kr → flairy.kr 301 포함 Nginx 설정 적용 (root/sudo 필요)
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)/deploy/nginx/flairy.conf"
DEST="/etc/nginx/sites-available/flairy"

cp "$SRC" "$DEST"
ln -sf "$DEST" /etc/nginx/sites-enabled/flairy
nginx -t
systemctl reload nginx
echo "OK: nginx reloaded ($(head -1 "$SRC"))"
