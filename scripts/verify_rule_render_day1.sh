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

echo "[1/2] ffprobe 메타데이터 확인"
ffprobe -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,profile,level,width,height,pix_fmt,r_frame_rate \
  -of default=noprint_wrappers=1 "$VIDEO_PATH"

echo
echo "[2/2] 수동 시각 검증 체크리스트"
echo "- [ ] 1080x1920 / 30fps / yuv420p / h264(high@4.2) 확인"
echo "- [ ] 16:9 원본이 찌그러짐 없이 중앙 배치(좌우 black 영역 포함)"
echo "- [ ] 1:1 / 4:21에서도 클립별 3초 줌인(1.0 -> 1.2) 부드럽게 동작"
echo "- [ ] 클립 간 xfade 0.5초 전환이 자연스럽고 프레임 튐 없음"
