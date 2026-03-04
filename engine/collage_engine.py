"""
인트로 전용 아티스틱 콜라주 엔진.
유니크 리스트 중 score 상위 2~3장으로 9:16 캔버스, 화이트 테두리·랜덤 회전·레이어드 오버레이 후 1개 .mp4 생성.
배경: 상위 1위 이미지 강한 블러. FFmpeg: 미세한 줌인(Ken Burns) 효과.
"""
import logging
import random
import subprocess
from pathlib import Path

from app.models import MediaFile

logger = logging.getLogger(__name__)

# 9:16 FHD 세로, 30fps CFR (video_engine 단일 클립과 동일 규격)
CANVAS_W = 1080
CANVAS_H = 1920
COLLAGE_FPS = 30
# 인트로용 상위 장수 (2~3장)
INTRO_TOP_N_MIN = 2
INTRO_TOP_N_MAX = 3
# 화이트 테두리(px), 랜덤 회전 범위(도)
WHITE_BORDER_PX = 15
ROTATE_DEG_MIN = -5
ROTATE_DEG_MAX = 5
# 인트로 타이틀: 상단 10% (192px), Classic Serif 68px, 미색 #F9F9F9
INTRO_TITLE_Y_OFFSET = 192
INTRO_TITLE_FONT_SIZE = 68
INTRO_TITLE_COLOR = (0xF9, 0xF9, 0xF9)
INTRO_TITLE_SHADOW_COLOR = (0, 0, 0, 180)
INTRO_TITLE_SHADOW_OFFSET = 2


def get_intro_images(media_files: list[MediaFile]) -> list[MediaFile]:
    """
    유니크 리스트(이미 is_selected=True) 중 이미지 타입만 골라
    ai_analysis['score'] 기준 내림차순 정렬 후 상위 2~3장 반환.
    """
    image_only = [mf for mf in media_files if mf.file_type == "image"]
    if not image_only:
        return []

    def score_of(mf: MediaFile) -> float:
        if not mf.ai_analysis or not isinstance(mf.ai_analysis.get("score"), (int, float)):
            return 0.0
        return float(mf.ai_analysis["score"])

    image_only.sort(key=score_of, reverse=True)
    n = min(INTRO_TOP_N_MAX, max(INTRO_TOP_N_MIN, len(image_only)))
    return image_only[:n]


def get_intro_group_only(media_files: list[MediaFile]) -> list[MediaFile]:
    """인트로용 이미지만 반환 (get_intro_images와 동일)."""
    return get_intro_images(media_files)


def get_intro_outro_groups(
    media_files: list[MediaFile],
) -> tuple[list[MediaFile], list[MediaFile]]:
    """아웃로 폐기: 인트로만 반환, 아웃로는 항상 빈 리스트."""
    intro = get_intro_images(media_files)
    return intro, []


def _load_image_upright(path: Path):
    """PIL로 EXIF 보정 후 세운 이미지 반환. 의존성: app.utils.media_processor."""
    from app.utils.media_processor import load_image_upright
    return load_image_upright(path)


def render_collage_clip(
    media_list: list[MediaFile],
    base_dir: Path,
    out_path: Path,
    duration_sec: float = 3.0,
    summary_text: str = "",
    title: str = "Our Precious Memories",
) -> Path:
    """
    인트로 전용 콜라주 1개 생성.
    9:16(1080x1920) 캔버스, 상위 1위 이미지 블러 배경, 화이트 테두리·랜덤 회전·레이어드 오버레이.
    FFmpeg: 미세한 줌인(zoompan) 적용. 출력: 1080x1920, 30fps CFR, yuv420p.
    """
    if not media_list:
        raise ValueError("콜라주용 미디어가 없습니다.")

    base_dir = Path(base_dir)
    out_path = Path(out_path)

    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        raise RuntimeError("콜라주 생성에 PIL이 필요합니다. Pillow를 설치하세요.")

    # 1) 이미지 로드: upright_path 우선, 방향 보정
    loaded: list = []
    for mf in media_list:
        rel = (mf.ai_analysis or {}).get("upright_path") or mf.file_path
        path = base_dir / rel
        if not path.is_file():
            path = base_dir / mf.file_path
        if not path.is_file():
            logger.warning("콜라주 스킵: 파일 없음 %s", path)
            continue
        try:
            img = _load_image_upright(path)
            img = img.convert("RGB")
            loaded.append(img)
        except Exception as e:
            logger.warning("콜라주 이미지 로드 실패 %s: %s", path.name, e)

    if not loaded:
        raise RuntimeError("콜라주용 이미지를 하나도 로드하지 못했습니다.")

    # 2) 배경: 상위 1위 이미지를 꽉 채운 뒤 강한 가우시안 블러
    bg = ImageOps.fit(loaded[0], (CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)
    canvas = bg.filter(ImageFilter.GaussianBlur(radius=50))

    # 2.5) 인트로 타이틀: 상단 10% 중앙, Playfair Display/Lora, 미색·그림자
    try:
        from PIL import ImageDraw, ImageFont
        fonts_dir = base_dir / "static" / "fonts"
        font_path = fonts_dir / "PlayfairDisplay[wght].ttf"
        if not font_path.is_file():
            font_path = fonts_dir / "Lora-Regular.ttf"
        if font_path.is_file():
            font = ImageFont.truetype(str(font_path), INTRO_TITLE_FONT_SIZE)
            draw = ImageDraw.Draw(canvas)
            label = (title or "Our Precious Memories").strip()[:60] or "Our Precious Memories"
            # 그림자 (오프셋 2,2 검정)
            draw.text(
                (CANVAS_W // 2 + INTRO_TITLE_SHADOW_OFFSET, INTRO_TITLE_Y_OFFSET + INTRO_TITLE_SHADOW_OFFSET),
                label, fill=(0, 0, 0), font=font, anchor="ma",
            )
            draw.text(
                (CANVAS_W // 2, INTRO_TITLE_Y_OFFSET),
                label, fill=INTRO_TITLE_COLOR, font=font, anchor="ma",
            )
        else:
            logger.warning("인트로 타이틀 폰트 없음, 텍스트 스킵")
    except Exception as e:
        logger.warning("인트로 타이틀 그리기 실패: %s", e)

    # 3) 사진 레이어드 배치 (2~3장: 타이틀 하단부터, 좌우/위2+아래1, 화이트 테두리, 랜덤 회전)
    cell_max = 620
    # 타이틀 하단 여유 두고 배치 (y 최소 720)
    positions = [(120, 720), (580, 720), (350, 1000)]

    for i, img in enumerate(loaded[: len(positions)]):
        w, h = img.size
        scale = min(cell_max / max(w, h), 1.0)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        if nw < 1 or nh < 1:
            nw, nh = max(1, nw), max(1, nh)
        img_s = img.resize((nw, nh), Image.Resampling.LANCZOS)

        # 화이트 테두리
        bordered = ImageOps.expand(img_s, border=WHITE_BORDER_PX, fill="white")

        # -5~5도 랜덤 회전 (expand=True로 모서리 잘림 방지)
        deg = random.uniform(ROTATE_DEG_MIN, ROTATE_DEG_MAX)
        rotated = bordered.rotate(
            deg, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255)
        )
        rw, rh = rotated.size

        x, y = positions[i]
        x = max(10, min(CANVAS_W - rw - 10, x))
        y = max(10, min(CANVAS_H - rh - 10, y))
        canvas.paste(rotated, (x, y))

    # 4) 임시 프레임 저장 후 FFmpeg (미세한 줌인 효과)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame_path = out_path.parent / "collage_frame.png"
    canvas.save(frame_path, "PNG")

    duration = max(0.1, duration_sec)
    total_frames = int(duration * COLLAGE_FPS)
    # zoompan: 1.0 -> 1.1 미세 줌인
    vf_chain = (
        f"format=yuv420p,fps={COLLAGE_FPS},"
        f"zoompan=z='min(zoom+0.0005,1.1)':d={total_frames}:s={CANVAS_W}x{CANVAS_H}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(frame_path),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", vf_chain,
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if frame_path.is_file():
        try:
            frame_path.unlink()
        except OSError:
            pass

    if result.returncode != 0:
        logger.error("콜라주 FFmpeg stderr: %s", result.stderr)
        raise RuntimeError(f"콜라주 FFmpeg 실패: {result.stderr or result.stdout}")

    if not out_path.is_file():
        raise RuntimeError(f"콜라주 출력 파일이 생성되지 않음: {out_path}")

    logger.info("인트로 콜라주 생성 완료: %s (score 상위 %d장)", out_path.name, len(loaded))
    return out_path
