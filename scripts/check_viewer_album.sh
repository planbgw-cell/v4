#!/usr/bin/env bash
# 앨범 뷰어 페이지·스크립트·JSON 응답 확인 (서버에서 실행)
# 사용: ./scripts/check_viewer_album.sh [base_url]
# 예: ./scripts/check_viewer_album.sh http://127.0.0.1:8000
BASE="${1:-http://127.0.0.1:8000}"
ID="02fea7b8-7583-4bee-a77d-ef011480f22c"

echo "=== 1. 뷰어 HTML (앨범용 스크립트 포함 여부) ==="
HTML=$(curl -sL "${BASE}/viewer/album/${ID}")
if echo "$HTML" | grep -q "album-viewer-init.js"; then
  echo "  OK: album-viewer-init.js 참조 있음"
else
  echo "  FAIL: album-viewer-init.js 참조 없음 (이전 템플릿이거나 block scripts 누락)"
fi
if echo "$HTML" | grep -q "flipbookRoot"; then
  echo "  OK: flipbookRoot ID 있음"
else
  echo "  FAIL: flipbookRoot 없음"
fi
if echo "$HTML" | grep -q "viewerRoot"; then
  echo "  OK: viewerRoot ID 있음"
else
  echo "  FAIL: viewerRoot 없음"
fi

echo ""
echo "=== 2. 정적 파일 /static/js/album-viewer-init.js ==="
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/static/js/album-viewer-init.js")
echo "  HTTP $STATUS"
if [ "$STATUS" = "200" ]; then
  echo "  OK"
else
  echo "  FAIL: 200이 아님 (배포 경로/마운트 확인)"
fi

echo ""
echo "=== 3. album_layout.json ==="
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/outputs/${ID}/album_layout.json")
echo "  HTTP $STATUS"
if [ "$STATUS" = "200" ]; then
  PAGES=$(curl -sL "${BASE}/outputs/${ID}/album_layout.json" | grep -o '"pages"' | wc -l)
  echo "  OK (pages 키 존재)"
else
  echo "  FAIL: 200이 아님"
fi

echo ""
echo "=== 4. HTML 길이 (빈 응답 여부) ==="
LEN=$(echo "$HTML" | wc -c)
echo "  $LEN bytes"
if [ "$LEN" -lt 500 ]; then
  echo "  FAIL: 응답이 너무 짧음 (에러 페이지 또는 조각만 반환 가능성)"
fi
