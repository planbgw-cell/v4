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

echo "[1/4] ffprobe: video stream 확인"
ffprobe -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,width,height,pix_fmt,r_frame_rate \
  -of default=noprint_wrappers=1:nokey=1 "$VIDEO_PATH"

echo
echo "[2/4] ffprobe: metadata(title/artist) 확인"
ffprobe -v error \
  -show_entries format_tags=title,artist \
  -of default=noprint_wrappers=1:nokey=1 "$VIDEO_PATH" \
  | sed -n '1,10p'

echo
echo "[3/4] faststart 추정: moov atom이 파일 앞쪽에 있는지 확인"
python3 - "$VIDEO_PATH" <<'PY'
import os, sys
path = sys.argv[1]
size = os.path.getsize(path)
head_n = min(size, 5 * 1024 * 1024)  # 5MB
tail_n = min(size, 5 * 1024 * 1024)
with open(path,'rb') as f:
    head = f.read(head_n)
    f.seek(max(0, size - tail_n))
    tail = f.read(tail_n)
def has_moov(buf: bytes) -> bool:
    return b'moov' in buf
head_has = has_moov(head)
tail_has = has_moov(tail)
print(f"file_size={size} bytes")
print(f"moov_in_head(<=5MB)={head_has}")
print(f"moov_in_tail(<=5MB)={tail_has}")
if head_has:
    print("faststart 가능성이 높습니다.")
elif tail_has:
    print("faststart 가능성이 낮습니다(대개 moov가 뒤쪽에 위치).")
else:
    print("moov atom 위치를 판별하기 어렵습니다(바이너리 검색 실패).")
PY

echo
echo "[4/4] 수동 확인 가이드"
echo "- 나레이션 구간에서 BGM이 덕킹되었다가 끝나면 복구되는지(청음)"
echo "- 음악 박자(on-beat)와 xfade 전환이 맞는지(영상 전환 스크럽)"
echo "- 모바일에서 Chrome/Safari 재생 시 버퍼링 없이 첫 프레임이 즉시 표시되는지"

