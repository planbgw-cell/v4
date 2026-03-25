#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "사용법: $0 <output.mp4>"
  exit 1
fi

VIDEO_PATH="$1"
if [[ ! -f "$VIDEO_PATH" ]]; then
  echo "파일이 없습니다: $VIDEO_PATH"
  exit 1
fi

echo "[1/3] ffprobe 메타데이터"
ffprobe -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,profile,level,width,height,pix_fmt,r_frame_rate \
  -of default=noprint_wrappers=1 "$VIDEO_PATH"

echo
echo "[2/3] Subject Test 로그 체크 포인트"
echo "- video_engine 로그에서 [AI Zoompan] subject center norm=(cx, cy) 확인"
echo "- cx/cy가 (0.5, 0.5)가 아닌 샘플에서 x/y 식이 center 고정이 아닌지 확인"
echo "- zoompan 식 내 clamp 사용 여부 확인:"
echo "  max(0,min(iw*cx-(iw/zoom/2),iw-iw/zoom))"
echo "  max(0,min(ih*cy-(ih/zoom/2),ih-ih/zoom))"

echo
echo "[3/3] Collage Test 체크리스트"
echo "- [ ] 유사 감정 페어가 있으면 시작 3초에 2분할 콜라주 등장"
echo "- [ ] 9:16 내에서 상/하 분할 이미지가 찌그러짐 없이 표시"
echo "- [ ] 전체 렌더 결과가 1080x1920 / 30fps / yuv420p 유지"
