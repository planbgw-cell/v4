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
from app.utils.path_manager import get_font_path_escaped_for_ffmpeg
from engine.preprocess_media import ensure_fhd_portrait

logger = logging.getLogger(__name__)

# 9:16 FHD 세로, 30fps CFR (video_engine 단일 클립과 동일 규격)
CANVAS_W = 1080
CANVAS_H = 1920
COLLAGE_FPS = 30
# zoompan은 픽셀 수에 비례해 CPU 부하 증가 → 절반 해상도에서 처리 후 업스케일
ZOOMPAN_W = CANVAS_W // 2
ZOOMPAN_H = CANVAS_H // 2
# 인트로 FFmpeg 전체 타임아웃(초) — 저사양/공유 CPU에서도 완료되도록 여유
COLLAGE_FFMPEG_TIMEOUT_SEC = 240
# 인트로용 상위 장수 (2~3장)
INTRO_TOP_N_MIN = 2
INTRO_TOP_N_MAX = 3
# 화이트 테두리(px), 랜덤 회전 범위(도)
WHITE_BORDER_PX = 20
ROTATE_DEG_MIN = -7
ROTATE_DEG_MAX = 7
# 폴라로이드 그림자(입체감)
POLAROID_SHADOW_ALPHA = 120
POLAROID_SHADOW_BLUR = 14
POLAROID_SHADOW_OFFSET = (10, 12)
# 인트로 B안: 하단 프로스트 패널 + 메인/서브 타이틀 (재생 컨트롤 위 여백)
INTRO_PANEL_MARGIN_BOTTOM = 160  # 플레이어 바 대비 상단
INTRO_PANEL_WIDTH = 980
INTRO_PANEL_HEIGHT = 200
INTRO_PANEL_RADIUS = 28
INTRO_TITLE_MAIN_SIZE = 62
INTRO_TITLE_SUB_SIZE = 34
INTRO_TITLE_MAIN_COLOR = (0xFA, 0xF5, 0xE8)  # Creamy white
INTRO_TITLE_SUB_COLOR = (0xD4, 0xAF, 0x37)  # Gentle gold
INTRO_TITLE_SHADOW_OFFSET = 2
# 상단 앨범 제목 (FFmpeg drawtext): 1080x1920 기준 상단 20~30% 밴드, 가로 한 줄 말줄임
INTRO_TITLE_TOP_Y = 450
INTRO_TITLE_TOP_FONTSIZE = 80
INTRO_TITLE_TOP_COLOR = "0xF9F9F9"  # Creamy White
INTRO_TITLE_TOP_BORDER_W = 4
# 가로 한 줄 안전 폭(튜닝): 한글 약 2유닛, ASCII 1유닛 — 1080px·fontsize 80 기준
INTRO_TITLE_MAX_UNITS_KR_APPROX = 18  # 한글 전용에 가깝게 쓸 때 참고
INTRO_TITLE_MAX_UNITS_EN_APPROX = 36
INTRO_TITLE_MAX_DISPLAY_UNITS = 36  # 혼합 문자열 가중 합 상한


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


def _char_display_unit(ch: str) -> int:
    """한 줄 폭 추정: 한글·전각류 2, ASCII 등 1."""
    if len(ch) != 1:
        return sum(_char_display_unit(c) for c in ch)
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3:
        return 2
    if o > 127:
        return 2
    return 1


def _escape_drawtext_text(raw: str) -> str:
    """FFmpeg drawtext text= 값 이스케이프 (video_engine._escape_drawtext와 동일 규칙)."""
    return (raw or "").replace("\\", "\\\\").replace("'", "'\\''").replace(":", "\\:")


def truncate_intro_title_display(
    title: str,
    max_units: int = INTRO_TITLE_MAX_DISPLAY_UNITS,
) -> str:
    """
    앨범 제목을 한 줄로 표시하기 위한 말줄임(...).
    Python 단에서만 처리하고 FFmpeg에는 display_title만 넘긴다.
    """
    s = (title or "").strip()
    if not s:
        return "Our Precious Memories"
    ellipsis = "..."
    ell_units = _char_display_unit(ellipsis)
    budget = max_units - ell_units
    if budget < 4:
        budget = max_units
    acc = 0
    out_chars: list[str] = []
    for ch in s:
        u = _char_display_unit(ch)
        if acc + u > budget:
            return ("".join(out_chars) + ellipsis).strip() or "…"
        out_chars.append(ch)
        acc += u
    return "".join(out_chars)


def format_ai_intro_title(title: str) -> str:
    """AI 인트로 상단 제목: 10자 초과 시 말줄임(...) (기획안 len 기준)."""
    s = (title or "").strip()
    limit = 10
    if len(s) > limit:
        return s[:limit] + "..."
    return s


def _build_intro_top_title_drawtext(display_title: str) -> str:
    """인트로 콜라주 상단 중앙: Noto Sans KR, 크림 화이트, 부드러운 그림자."""
    label = _escape_drawtext_text(display_title) or " "
    font_esc = get_font_path_escaped_for_ffmpeg("NotoSansKR[wght].ttf")
    if font_esc:
        font_opt = f"fontfile='{font_esc}':"
    else:
        font_opt = ""
    return (
        f"drawtext=text='{label}':{font_opt}fontsize={INTRO_TITLE_TOP_FONTSIZE}:"
        f"fontcolor={INTRO_TITLE_TOP_COLOR}:shadowcolor=black@0.6:shadowx=2:shadowy=2:"
        f"x=(w-text_w)/2:y={INTRO_TITLE_TOP_Y}"
    )


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


def _draw_frosted_intro_title_overlay(
    canvas,
    subtitle: str,
    fonts_dir: Path,
) -> None:
    """
    하단 중앙: 블러 샘플 + 반투명 라운드 패널(프로스트 글래스) + 서브 타이틀만.
    앨범 메인 제목은 FFmpeg drawtext(상단)로만 그려 중복·두 줄 깨짐을 방지한다.
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    w, h = CANVAS_W, CANVAS_H
    pw = min(INTRO_PANEL_WIDTH, w - 80)
    ph = INTRO_PANEL_HEIGHT
    x0 = (w - pw) // 2
    y1 = h - INTRO_PANEL_MARGIN_BOTTOM
    y0 = y1 - ph - 36
    x1 = x0 + pw
    y1 = y0 + ph
    if y0 < 0:
        y0 = 40
        y1 = y0 + ph

    region = canvas.crop((x0, y0, x1, y1))
    rw, rh = region.size
    if rw >= 4 and rh >= 4:
        small = region.resize((max(1, rw // 2), max(1, rh // 2)), Image.Resampling.LANCZOS)
        blurred = small.filter(ImageFilter.GaussianBlur(radius=14))
        blurred = blurred.resize((rw, rh), Image.Resampling.LANCZOS)
        blended = Image.blend(region, blurred, 0.48)
        canvas.paste(blended, (x0, y0))
        overlay = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
        dr = ImageDraw.Draw(overlay)
        dr.rounded_rectangle((0, 0, rw, rh), radius=INTRO_PANEL_RADIUS, fill=(255, 255, 255, 88))
        canvas.paste(overlay, (x0, y0), overlay)

    font_sub = None
    for name in ("NotoSansKR[wght].ttf", "NanumPenScript-Regular.ttf"):
        p = fonts_dir / name
        if p.is_file():
            try:
                font_sub = ImageFont.truetype(str(p), INTRO_TITLE_SUB_SIZE)
                break
            except OSError:
                continue
    if font_sub is None:
        try:
            font_sub = ImageFont.load_default()
        except Exception:
            return
    draw = ImageDraw.Draw(canvas)
    sub_text = (subtitle or "").strip()[:100]
    cx = w // 2
    oy = INTRO_TITLE_SHADOW_OFFSET
    if sub_text:
        # 메인 제목 없음: 패널 안 세로 중앙에 서브만
        sy = y0 + max(20, (ph - INTRO_TITLE_SUB_SIZE) // 2)
        fs = font_sub
        if fs is not None:
            for dx, dy in ((oy, oy), (-oy, -oy), (oy, -oy), (-oy, oy)):
                draw.text((cx + dx, sy + dy), sub_text, fill=(0, 0, 0), font=fs, anchor="ms")
            draw.text((cx, sy), sub_text, fill=INTRO_TITLE_SUB_COLOR, font=fs, anchor="ms")


def render_collage_clip(
    media_list: list[MediaFile],
    base_dir: Path,
    out_path: Path,
    duration_sec: float = 3.0,
    summary_text: str = "",
    title: str = "Our Precious Memories",
    subtitle: str = "",
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

    # 3) 폴라로이드 3장 레이어드 배치 (좌 기울임, 우 기울임, 하단 1장) + 그림자 + 오버랩
    cell_max = 640
    # 상단 제목 영역(세이프 존) 아래부터 배치
    positions = [
        (120, 720),   # left
        (520, 700),   # right (겹치도록 살짝 위/좌)
        (320, 1040),  # bottom
    ]

    def _paste_polaroid(base, polaroid_rgba, x: int, y: int) -> None:
        """그림자 + 폴라로이드 RGBA를 base(RGB)에 합성."""
        from PIL import Image, ImageFilter
        rw, rh = polaroid_rgba.size
        # shadow: alpha 마스크를 블러 처리
        shadow = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
        alpha = polaroid_rgba.split()[-1]
        shadow_mask = alpha.point(lambda a: 255 if a > 0 else 0)
        shadow.paste((0, 0, 0, POLAROID_SHADOW_ALPHA), (0, 0), shadow_mask)
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=POLAROID_SHADOW_BLUR))

        sx = x + POLAROID_SHADOW_OFFSET[0]
        sy = y + POLAROID_SHADOW_OFFSET[1]
        base.paste(shadow, (sx, sy), shadow)
        base.paste(polaroid_rgba, (x, y), polaroid_rgba)

    for i, img in enumerate(loaded[: len(positions)]):
        w, h = img.size
        scale = min(cell_max / max(w, h), 1.0)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        if nw < 1 or nh < 1:
            nw, nh = max(1, nw), max(1, nh)
        img_s = img.resize((nw, nh), Image.Resampling.LANCZOS)

        # 화이트 테두리
        bordered = ImageOps.expand(img_s, border=WHITE_BORDER_PX, fill="white").convert("RGBA")

        # -5~5도 랜덤 회전 (expand=True로 모서리 잘림 방지)
        deg = random.uniform(ROTATE_DEG_MIN, ROTATE_DEG_MAX)
        # 좌/우는 방향성 부여해 폴라로이드 느낌 강화
        if i == 0:
            deg = -abs(deg)
        elif i == 1:
            deg = abs(deg)
        rotated = bordered.rotate(deg, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255, 255))
        rw, rh = rotated.size

        x, y = positions[i]
        x = max(10, min(CANVAS_W - rw - 10, x))
        y = max(10, min(CANVAS_H - rh - 10, y))
        _paste_polaroid(canvas, rotated, x, y)

    # 기존 B안(하단 프로스트 패널)은 AI 인트로 고도화에서는 사용하지 않는다.

    # 4) 임시 프레임 저장 후 FFmpeg (미세한 줌인 효과 + 페이드 인/아웃)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame_path = out_path.parent / "collage_frame.png"
    canvas.save(frame_path, "PNG")

    duration = max(0.1, duration_sec)
    total_frames = max(1, int(duration * COLLAGE_FPS))
    # 페이드 인(fade=t=in)은 첫 프레임을 검은색에서 시작시키므로 사용하지 않음 — 첫 화면부터 콜라주+타이틀 노출
    fade_out = 0.35
    fade_out_st = max(0.0, duration - fade_out)
    display_title = format_ai_intro_title(title)
    logger.info(
        "AI 인트로 상단 제목(display_title): %r (len<=10)",
        display_title,
    )
    draw_title = _build_intro_top_title_drawtext(display_title)
    # 제목 아래 divider(얇은 선)
    divider_y = INTRO_TITLE_TOP_Y + int(INTRO_TITLE_TOP_FONTSIZE * 1.2)
    draw_divider = (
        f"drawbox=x=(w-520)/2:y={divider_y}:w=520:h=3:color=white@0.45:t=fill"
    )
    # 저해상도에서 zoompan(픽셀 수 1/4) → bilinear 업스케일 → 인코딩 부하·타임아웃 완화
    # 상단 앨범 제목은 마지막 drawtext로 고정(배경 줌과 무관하게 선명한 한 줄)
    vf_chain = (
        f"scale={ZOOMPAN_W}:{ZOOMPAN_H}:flags=fast_bilinear,"
        f"format=yuv420p,fps={COLLAGE_FPS},"
        f"zoompan=z='min(zoom+0.0005,1.1)':d={total_frames}:s={ZOOMPAN_W}x{ZOOMPAN_H}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',"
        f"scale={CANVAS_W}:{CANVAS_H}:flags=bilinear,format=yuv420p,"
        f"fade=t=out:st={fade_out_st:.3f}:d={fade_out},"
        f"{draw_divider},{draw_title}"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(frame_path),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", vf_chain,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest", str(out_path),
    ]
    logger.info(
        "콜라주 FFmpeg 시작 (zoompan %dx%d→%dx%d, timeout=%ss)",
        ZOOMPAN_W,
        ZOOMPAN_H,
        CANVAS_W,
        CANVAS_H,
        COLLAGE_FFMPEG_TIMEOUT_SEC,
    )
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=COLLAGE_FFMPEG_TIMEOUT_SEC
    )
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


def render_split_intro_clip(
    media_pair: list[MediaFile],
    base_dir: Path,
    out_path: Path,
    duration_sec: float = 3.0,
) -> Path:
    """
    2분할(상/하) 인트로 클립 생성.
    - 입력 2장을 preprocess_media.ensure_fhd_portrait로 사전 1080x1920 정규화
    - ffmpeg overlay로 1080x960 + 1080x960 영역에 배치
    """
    if len(media_pair) < 2:
        raise ValueError("2분할 콜라주에는 2개 미디어가 필요합니다.")

    base_dir = Path(base_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prep_paths: list[Path] = []
    for i, mf in enumerate(media_pair[:2]):
        rel = (mf.ai_analysis or {}).get("upright_path") or mf.file_path
        src_path = base_dir / rel
        if not src_path.is_file():
            src_path = base_dir / mf.file_path
        if not src_path.is_file():
            raise FileNotFoundError(f"분할 콜라주 소스 파일 없음: {mf.file_path}")
        prep = out_path.parent / f"split_intro_src_{i:02d}.jpg"
        prep_paths.append(ensure_fhd_portrait(src_path, prep))

    duration = max(0.1, float(duration_sec))
    filter_complex = (
        "[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[top];"
        "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[bottom];"
        "color=c=black:s=1080x1920:r=30[base];"
        "[base][top]overlay=0:0[tmp];"
        "[tmp][bottom]overlay=0:960,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(prep_paths[0]),
        "-loop",
        "1",
        "-i",
        str(prep_paths[1]),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "2:a",
        "-t",
        f"{duration:.3f}",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-level:v",
        "4.2",
        "-b:v",
        "6M",
        "-maxrate",
        "8M",
        "-bufsize",
        "12M",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=COLLAGE_FFMPEG_TIMEOUT_SEC)
    for p in prep_paths:
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    if result.returncode != 0:
        logger.error("2분할 인트로 FFmpeg stderr: %s", result.stderr)
        raise RuntimeError(f"2분할 콜라주 생성 실패: {result.stderr or result.stdout}")
    if not out_path.is_file():
        raise RuntimeError(f"2분할 콜라주 출력 파일이 생성되지 않음: {out_path}")
    logger.info("2분할 인트로 콜라주 생성 완료: %s", out_path.name)
    return out_path
