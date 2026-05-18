#!/usr/bin/env bash
# 동시에 여러 프로젝트에 대해 POST generate를 보냅니다 (부하 테스트용).
# 사용법:
#   ./scripts/stress_generate.sh BASE_URL COOKIE_HEADER PROJECT_ID [PROJECT_ID ...]
# 예:
#   ./scripts/stress_generate.sh http://127.0.0.1:8000 "Cookie: session=..." \
#     uuid1 uuid2 uuid3 uuid4
set -euo pipefail
BASE="${1:?base url}"
COOKIE="${2:?cookie header}"
shift 2
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 BASE_URL COOKIE_HEADER PROJECT_ID ..." >&2
  exit 1
fi
for pid in "$@"; do
  curl -sS -o /dev/null -w "%{http_code} ${pid}\n" \
    -X POST "${BASE}/api/projects/${pid}/generate" \
    -H "${COOKIE}" \
    -H "Content-Type: application/json" &
done
wait
echo "Done. Check journalctl -u flairy_v4.service -f for GPU_SLOT / FALLBACK_CPU."
