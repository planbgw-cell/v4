"""
이미지에서 도미넌트/액센트 색상 추출. PIL 기반.
앨범 동적 테마(Soft Tint 배경, 포인트 컬러)용.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[misc, assignment]

# 샘플 크기: 작을수록 빠름, 너무 작으면 대표성 감소
SAMPLE_SIZE = (48, 48)
# 도미넌트: 픽셀 양자화 비트 수 (2^BITS 레벨 per 채널)
DOMINANT_BITS = 4
# 액센트: 채도 임계 (0~1). 이 이상인 색만 고려
ACCENT_SAT_MIN = 0.25


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    mx = max(r_, g_, b_)
    mn = min(r_, g_, b_)
    d = mx - mn
    v = mx
    if mx == 0:
        s = 0.0
    else:
        s = d / mx
    if d == 0:
        h = 0.0
    elif mx == r_:
        h = (60 * ((g_ - b_) / d) + 360) % 360
    elif mx == g_:
        h = 60 * ((b_ - r_) / d) + 120
    else:
        h = 60 * ((r_ - g_) / d) + 240
    return (h, s, v)


def get_dominant_color_hex(image_path: Path) -> str | None:
    """
    이미지에서 대표 색상 1개를 추출해 #RRGGBB 반환.
    파일 없음/비이미지/실패 시 None.
    """
    if Image is None:
        logger.warning("color_utils: PIL 없음, 도미넌트 추출 불가")
        return None
    path = Path(image_path)
    if not path.is_file():
        return None
    try:
        img = Image.open(path).convert("RGB")
    except Exception as e:
        logger.debug("color_utils: 이미지 열기 실패 %s: %s", path, e)
        return None
    w, h = img.size
    if w > SAMPLE_SIZE[0] or h > SAMPLE_SIZE[1]:
        img = img.resize(SAMPLE_SIZE, Image.Resampling.LANCZOS)
    pixels = list(img.getdata())
    if not pixels:
        return None
    # 양자화: BITS 비트로 줄여서 버킷 카운트
    shift = 8 - DOMINANT_BITS
    buckets: dict[tuple[int, int, int], int] = {}
    for (r, g, b) in pixels:
        q = (r >> shift, g >> shift, b >> shift)
        buckets[q] = buckets.get(q, 0) + 1
    best = max(buckets.items(), key=lambda x: x[1])[0]
    # 버킷 중심을 RGB로 복원
    r = (best[0] << shift) + (1 << (shift - 1))
    g = (best[1] << shift) + (1 << (shift - 1))
    b = (best[2] << shift) + (1 << (shift - 1))
    r, g, b = min(r, 255), min(g, 255), min(b, 255)
    return _rgb_to_hex(r, g, b)


def get_accent_color_hex(image_path: Path) -> str | None:
    """
    이미지에서 채도가 높은 강조색 1개를 추출해 #RRGGBB 반환.
    적합한 색이 없으면 None.
    """
    if Image is None:
        return None
    path = Path(image_path)
    if not path.is_file():
        return None
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return None
    w, h = img.size
    if w > SAMPLE_SIZE[0] or h > SAMPLE_SIZE[1]:
        img = img.resize(SAMPLE_SIZE, Image.Resampling.LANCZOS)
    pixels = list(img.getdata())
    if not pixels:
        return None
    best_sat = -1.0
    best_rgb: tuple[int, int, int] | None = None
    for (r, g, b) in pixels:
        h_, s, v = _rgb_to_hsv(r, g, b)
        if s >= ACCENT_SAT_MIN and v >= 0.15:
            if s > best_sat:
                best_sat = s
                best_rgb = (r, g, b)
    if best_rgb is None:
        return None
    return _rgb_to_hex(best_rgb[0], best_rgb[1], best_rgb[2])
