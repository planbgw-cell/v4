"""
하이라이트 영상 엔진. 9:16(1080x1920) FHD 세로 규격, EXIF/회전 보정, 스마트 블러·Ken Burns.
"""
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import UUID

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pillow_heif = None  # type: ignore[misc, assignment]

try:
    import piexif
except ImportError:
    piexif = None  # type: ignore[misc, assignment]

# HEIC EXIF용 의존성 가드: 미설치 시 로그만 남기고 JPEG 등은 media_processor에서 처리
def _check_heic_deps() -> None:
    if pillow_heif is None or piexif is None:
        import logging
        logging.getLogger(__name__).warning(
            "HEIC EXIF를 쓰려면 pillow-heif, piexif 설치 필요: pip install pillow-heif piexif"
        )

from app.crud import get_media_files_by_project, get_project, update_project_status
from app.database import ensure_logs_column, SessionLocal
from app.models import MediaFile, Project
from app.utils.media_processor import IMAGE_EXTENSIONS, get_standard_orientation
from app.utils.path_manager import (
    CINEMATIC_FONT_PRIMARY,
    CINEMATIC_FONT_FALLBACK,
    ENGLISH_CAPTION_FONT_PRIMARY,
    ENGLISH_CAPTION_FONT_FALLBACK,
    get_font_path_escaped_for_ffmpeg,
    get_fonts_dir,
)
from engine.bgm_engine import get_dominant_emotion, select_bgm_path
from engine.collage_engine import get_intro_images, render_collage_clip

logger = logging.getLogger(__name__)

# 시네마틱 투명 자막 (Google Photos 스타일): 검은 바 없음, 플로팅 텍스트, 9:16 기준
CINEMATIC_FONT_SIZE = 60
CINEMATIC_FLOAT_Y_OFFSET = 150  # y=h-th-150
# 영문 감성 자막: 플레이어 하단 15% (1920*0.15=288), 타이프라이터 스타일
ENGLISH_CAPTION_FONT_SIZE = 42
ENGLISH_CAPTION_Y_OFFSET = 288  # 하단 15%, y=h-th-288
ENGLISH_CAPTION_TYPEWRITER_CHARS_MAX = 30  # 타이프라이터 drawtext 체인 글자 수 상한
SUBTITLE_RATIO = 0.45  # 전체 클립 중 자막 노출 비율 (40~50%)

# 9:16 FHD 세로 (1080x1920), xfade 호환을 위해 모든 클립 30fps CFR 강제
CANVAS_W = 1080
CANVAS_H = 1920
CLIP_DURATION_SEC = 3
CLIP_FPS = 30
# 스트림 표준화: 포맷·프레임레이트·타임베이스 통일 (yuv420p, 30fps, AVTB)
VF_CFR_IMAGE = ",format=yuv420p,fps=30,settb=AVTB"
VF_CFR_VIDEO = ",fps=30,settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p"
CLIP_FRAMES = CLIP_DURATION_SEC * CLIP_FPS  # 90
# Ken Burns zoompan (90 frames @ 30fps = 3초) — Rule-based: 화면 중앙
ZOOMPAN_916 = (
    "zoompan=z='min(zoom+0.0015,1.5)':d=90:s=1080x1920:"
    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps=30"
)
# AI: Safe Zone 하단 20% 자막 영역 회피 — 줌 중심을 상단으로 12% 오프셋
SAFE_ZONE_TOP_OFFSET = 0.12
# AI: zoompan 최종 배율 (ease-in-out 1.0 → 1.4)
ZOOMPAN_AI_MAX_ZOOM = 1.4
# 가로 사진 배경 블러 강도 (감성 배경)
LANDSCAPE_BOXBLUR = "40:20"

# 모바일 최적화 인코딩 (Phase 5): CRF 23~28, 선택적 HEVC/NVENC
OUTPUT_CRF = 25
USE_HEVC = os.environ.get("USE_HEVC", "").strip().lower() in ("1", "true", "yes")
_NVENC_AVAILABLE: bool | None = None


def _detect_nvenc() -> bool:
    """
    NVENC 런타임 사용 가능 여부를 '실제 더미 인코딩'으로 확인 (한 번만 캐시).
    컴파일 목록(-encoders)이 아닌 libcuda 로드·인코더 오픈 성공 여부로 판단.
    """
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "nullsrc=s=1x1", "-t", "0.1",
                "-c:v", "h264_nvenc",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode == 0:
            _NVENC_AVAILABLE = True
            logger.info("[ENCODER] NVENC runtime check passed. Using h264_nvenc.")
        else:
            _NVENC_AVAILABLE = False
            stderr = (r.stderr or "")[:500]
            if "libcuda" in stderr or "Cannot load" in stderr:
                logger.info(
                    "[ENCODER] NVENC detected but failed to load (e.g. libcuda not found). Falling back to libx264."
                )
            else:
                logger.info("[ENCODER] NVENC unavailable. Falling back to libx264.")
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        _NVENC_AVAILABLE = False
        logger.info("[ENCODER] NVENC check failed (%s). Falling back to libx264.", e)
    return _NVENC_AVAILABLE


def get_video_encoding_args() -> list[str]:
    """모바일 공유용 인코딩 인자. USE_HEVC=1 시 libx265, NVENC 런타임 가능 시 h264_nvenc, 아니면 libx264."""
    if USE_HEVC:
        return ["-c:v", "libx265", "-crf", "26", "-tag:v", "hvc1"]
    if _detect_nvenc():
        return ["-c:v", "h264_nvenc", "-cq", str(OUTPUT_CRF)]
    return ["-c:v", "libx264", "-crf", "23", "-preset", "medium"]


def _write_typewriter_ass(text: str, out_path: Path, duration_sec: float = 3.0) -> None:
    """
    타이프라이터 효과 ASS 자막 파일 생성. 1/15초(약 67ms)당 한 글자 노출(\\kf).
    Phase 4-B: Special Elite 42pt, #F9F9F9, 하단 15%(MarginV=288), Shadow=2.
    """
    raw = (text or "").strip()[:ENGLISH_CAPTION_TYPEWRITER_CHARS_MAX]
    if not raw:
        return

    def _ass_escape(c: str) -> str:
        if c == "\\":
            return "\\\\"
        if c == "{":
            return "{{"
        if c == "}":
            return "}}"
        return c

    typewriter_body = "".join("{\\kf67}" + _ass_escape(c) for c in raw)
    end_sec = max(duration_sec, len(raw) / 15.0 + 0.5)
    h = int(end_sec // 3600)
    m = int((end_sec % 3600) // 60)
    s = end_sec % 60
    end_str = f"{h}:{m:02d}:{s:05.2f}"

    script_info = "[Script Info]\nTitle: Flairy Typewriter\nScriptType: v4.00+\n\n"
    styles = (
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Special Elite,42,&H00F9F9F9,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,0,2,2,10,10,288,1\n\n"
    )
    events = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,{end_str},Default,,0,0,0,,{typewriter_body}\n"
    )
    out_path.write_text(script_info + styles + events, encoding="utf-8")


class FlairyVideoEngine:
    """하이라이트 영상 생성 엔진. storage/raw/{project_id} 읽기, storage/temp·storage/final/{project_id} 사용.
    DB는 로그 기록 시점에만 짧은 세션을 열어 상태 API 블로킹을 방지한다.
    """

    def __init__(self, project_id: UUID, base_dir: Path):
        ensure_logs_column()
        self.project_id = project_id
        self.base_dir = Path(base_dir)
        self.raw_dir = self.base_dir / "storage" / "raw" / str(project_id)
        self.final_dir = self.base_dir / "storage" / "final" / str(project_id)
        self.temp_dir = self.base_dir / "storage" / "temp" / str(project_id)
        # 싱글 포인트: 엔진 생성 시 NVENC 런타임 체크 1회 (캐시되어 이후 인코딩에서 재사용)
        _detect_nvenc()

    def _append_log(self, message: str) -> None:
        """
        프로젝트 logs 필드에 한 줄씩 로그를 누적한다.
        요청 시점에만 짧은 세션을 열고 닫아, 장시간 연결 점유를 하지 않는다.
        실패해도 렌더링 자체는 계속 진행되도록 예외는 삼킨다.
        """
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == self.project_id).first()
            if not project:
                return
            ts = datetime.utcnow().strftime("%H:%M:%S")
            line = f"[{ts}] {message}\n"
            project.logs = (project.logs or "") + line
            db.add(project)
            db.commit()
        except Exception as e:  # noqa: BLE001
            logger.debug("logs DB 저장 실패: %s", e)
        finally:
            db.close()

    def _parse_subject_box(self, ai_analysis: dict | None) -> tuple[float, float, float, float] | None:
        """ai_analysis에서 subject_box [ymin, xmin, ymax, xmax] 추출. 0-1000 정규화 → 0-1 반환."""
        if not ai_analysis or not isinstance(ai_analysis.get("subject_box"), (list, tuple)):
            return None
        box = ai_analysis["subject_box"]
        if len(box) != 4:
            return None
        try:
            ymin, xmin, ymax, xmax = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        except (TypeError, ValueError):
            return None
        if max(ymin, xmin, ymax, xmax) > 1.0:
            ymin, xmin, ymax, xmax = ymin / 1000.0, xmin / 1000.0, ymax / 1000.0, xmax / 1000.0
        if not (0 <= ymin < ymax <= 1 and 0 <= xmin < xmax <= 1):
            return None
        return (ymin, xmin, ymax, xmax)

    def _subject_center_safe(
        self,
        w: int,
        h: int,
        subject_box: tuple[float, float, float, float],
        *,
        scaled_w: float,
        scaled_h: float,
        crop_left: float,
        crop_top: float,
    ) -> tuple[float, float]:
        """subject_box 중심을 1080x1920 캔버스 픽셀 좌표로 변환. 하단 20% 회피를 위해 y를 상단으로 오프셋."""
        ymin, xmin, ymax, xmax = subject_box
        x_c = (xmin + xmax) / 2.0
        y_c = (ymin + ymax) / 2.0
        focus_x = x_c * scaled_w - crop_left
        focus_y = y_c * scaled_h - crop_top
        focus_x = max(0.0, min(float(CANVAS_W), focus_x))
        focus_y = max(0.0, min(float(CANVAS_H), focus_y))
        offset_up = CANVAS_H * SAFE_ZONE_TOP_OFFSET
        focus_y_safe = max(0.0, focus_y - offset_up)
        return (focus_x, focus_y_safe)

    def _build_zoompan_ai_ease(self, focus_x: float, focus_y: float) -> str:
        """피사체 중심(focus_x, focus_y)을 목표로 ease-in-out zoompan. 1.0 → 1.4 (90프레임)."""
        # smoothstep: t*(t*(3-2*t)), t=on/90 → z=1 + (1.4-1)*smoothstep
        return (
            f"zoompan=z='min(1+0.4*(on/90.0)*(on/90.0)*(3-2*on/90.0),{ZOOMPAN_AI_MAX_ZOOM})':"
            f"d={CLIP_FRAMES}:s={CANVAS_W}x{CANVAS_H}:"
            f"x='{focus_x}-({CANVAS_W}/2/zoom)':y='{focus_y}-({CANVAS_H}/2/zoom)':fps={CLIP_FPS}"
        )

    def _probe_media(self, path: Path) -> dict:
        """
        비디오/이미지의 width, height, rotation 조회.
        이미지는 media_processor.get_standard_orientation(단일 소스), 비디오는 ffprobe.
        반환: {"width": int, "height": int, "rotation": 0|90|180|270}.
        """
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            if suffix in (".heic", ".heif"):
                _check_heic_deps()
            try:
                return get_standard_orientation(path)
            except Exception as e:  # noqa: BLE001
                logger.warning("get_standard_orientation 실패, ffprobe 시도: %s", e)
                # fallback: ffprobe (rotation=0 가능)
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-show_entries",
            "stream_side_data=rotation",
            "-show_entries",
            "stream_tags=rotate",
            "-show_entries",
            "format_tags=rotate",
            "-of",
            "json",
            str(path),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.warning("ffprobe 실패: %s", result.stderr)
                raise RuntimeError(f"ffprobe 실패: {result.stderr}")
            data = json.loads(result.stdout)
            streams = data.get("streams") or []
            if not streams:
                raise RuntimeError("비디오 스트림 없음")
            s = streams[0]
            w = int(s.get("width", 0))
            h = int(s.get("height", 0))
            if w <= 0 or h <= 0:
                raise RuntimeError("width/height 없음")
            rotation = 0
            side_data = s.get("side_data") or []
            for sd in side_data:
                if "rotation" in sd:
                    rotation = int(float(sd["rotation"]))
                    break
            if rotation == 0:
                tags = s.get("tags") or {}
                rot_tag = tags.get("rotate")
                if rot_tag is not None:
                    rotation = int(float(rot_tag))
            if rotation == 0:
                fmt = data.get("format") or {}
                fmt_tags = fmt.get("tags") or {}
                rot_tag = fmt_tags.get("rotate")
                if rot_tag is not None:
                    rotation = int(float(rot_tag))
            rotation = int(rotation) % 360
            if rotation not in (0, 90, 180, 270):
                rotation = 0
            return {"width": w, "height": h, "rotation": rotation}
        except json.JSONDecodeError as e:
            logger.warning("ffprobe JSON 파싱 실패: %s", e)
            raise RuntimeError(f"ffprobe 출력 파싱 실패: {e}") from e

    def _build_916_vf(
        self,
        input_path: Path,
        media_file: MediaFile | None = None,
        use_ai: bool = False,
        used_upright_file: bool = False,
    ) -> str:
        """
        9:16(1080x1920) 캔버스용 -vf 문자열 생성.
        AI 모드: DB(media_file.width/height)만 사용, EXIF 미사용. width < height 이면 세로(Portrait).
        used_upright_file이 True일 때만 ai_analysis dimension 사용(원본 사용 시 probe+rotation).
        Rule-based: 파일 probe로 rotation 판단.
        """
        file_id = (media_file.file_path if media_file else input_path.name) or input_path.name
        use_db_dimensions = False
        if use_ai and media_file:
            # 1) DB 컬럼 width/height (물리 회전 후 규격)
            if getattr(media_file, "width", None) is not None and getattr(media_file, "height", None) is not None:
                w = int(media_file.width)
                h = int(media_file.height)
                rot = 0
                probe = {"width": w, "height": h, "rotation": rot}
                use_db_dimensions = True
                logger.info("[RENDER] 916_vf DB dimensions only (no EXIF): %sx%s", w, h)
            # 2) ai_analysis fallback: 실제로 upright 파일을 입력으로 쓸 때만 사용
            elif used_upright_file and media_file.ai_analysis and media_file.ai_analysis.get("upright_path"):
                c = media_file.ai_analysis
                if c.get("width") is not None and c.get("height") is not None:
                    w = int(c["width"])
                    h = int(c["height"])
                    rot = 0
                    probe = {"width": w, "height": h, "rotation": rot}
                    use_db_dimensions = True
                    logger.info("[RENDER] 916_vf ai_analysis dimensions (no EXIF): %sx%s", w, h)
            if not use_db_dimensions:
                probe = self._probe_media(input_path)
                w, h = probe["width"], probe["height"]
                rot = probe["rotation"]
        else:
            probe = self._probe_media(input_path)
            w, h = probe["width"], probe["height"]
            rot = probe["rotation"]

        if not use_db_dimensions and rot in (90, 270):
            w, h = h, w
        rot_filters = [] if use_db_dimensions else (
            ["transpose=1"] if rot == 90 else ["transpose=2"] if rot == 270 else ["transpose=2", "transpose=2"] if rot == 180 else []
        )
        rot_prefix = ",".join(rot_filters) + "," if rot_filters else ""

        # 로깅: AI는 DB 기준 세로/가로만
        if use_db_dimensions:
            is_portrait_db = w < h
            logger.info("[ORIENTATION] File: %s, DB only: %sx%s -> %s (no EXIF)", file_id, w, h, "Portrait" if is_portrait_db else "Landscape")
        else:
            if rot in (90, 270):
                logger.info("[ORIENTATION] File: %s, Detected: Vertical(Rotate %s), Applied: Transpose", file_id, rot)
            elif rot == 180:
                logger.info("[ORIENTATION] File: %s, Detected: Horizontal(Rotate 180), Applied: Transpose", file_id)
            else:
                logger.info("[ORIENTATION] File: %s, Detected: Horizontal(Rotate 0), Applied: (none)", file_id)

        ai_analysis = media_file.ai_analysis if media_file else None
        subject_box = self._parse_subject_box(ai_analysis)
        use_ai_focus = use_ai and subject_box is not None

        aspect_src = w / h if h else 0
        aspect_916 = CANVAS_W / CANVAS_H
        if abs(aspect_src - aspect_916) < 0.01:
            simple = (
                f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=decrease,"
                f"pad={CANVAS_W}:{CANVAS_H}:(ow-iw)/2:(oh-ih)/2[vid]"
            )
            return rot_prefix + simple

        # 세로(Portrait): width < height (DB/물리 규격 기준, EXIF 미참조)
        is_portrait = (w < h)
        logger.info(
            "916_vf: file=%s wh=(%s,%s) is_portrait=%s (width<height) use_ai_focus=%s",
            file_id, w, h, is_portrait, use_ai_focus,
        )
        if is_portrait:
            scale = max(CANVAS_W / w, CANVAS_H / h)
            scaled_w = w * scale
            scaled_h = h * scale
            crop_left = (scaled_w - CANVAS_W) / 2.0
            crop_top = (scaled_h - CANVAS_H) / 2.0
            fill_crop = (
                f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
                f"crop={CANVAS_W}:{CANVAS_H}:{int(crop_left)}:{int(crop_top)}"
            )
            if use_ai_focus and subject_box:
                focus_x, focus_y_safe = self._subject_center_safe(
                    w, h, subject_box,
                    scaled_w=scaled_w, scaled_h=scaled_h,
                    crop_left=crop_left, crop_top=crop_top,
                )
                zoompan = self._build_zoompan_ai_ease(focus_x, focus_y_safe)
                return rot_prefix + fill_crop + "," + zoompan + "[vid]"
            return rot_prefix + fill_crop + "," + ZOOMPAN_916 + "[vid]"

        # 가로(landscape): 블러 배경(40:20) + 전경. AI 시 피사체 중심으로 패닝
        blur_chain = (
            f"split[src][dup];"
            f"[dup]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
            f"crop={CANVAS_W}:{CANVAS_H},boxblur={LANDSCAPE_BOXBLUR}[bg];"
            f"[src]scale={CANVAS_W}:-2:force_original_aspect_ratio=decrease[fg];"
        )
        if use_ai_focus and subject_box:
            scale_fg = min(CANVAS_W / w, CANVAS_H / h)
            fg_w = w * scale_fg
            fg_h = h * scale_fg
            x_c = (subject_box[1] + subject_box[3]) / 2.0
            y_c = (subject_box[0] + subject_box[2]) / 2.0
            sub_x = x_c * fg_w
            sub_y = y_c * fg_h
            overlay_x = round(540 - sub_x)
            overlay_y = round(960 - sub_y)
            overlay_x = max(0, min(int(CANVAS_W - fg_w), overlay_x))
            overlay_y = max(0, min(int(CANVAS_H - fg_h), overlay_y))
            blur_chain += f"[bg][fg]overlay={overlay_x}:{overlay_y}[vid]"
        else:
            blur_chain += f"[bg][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2[vid]"
        return rot_prefix + blur_chain

    def _get_caption(self, media_file: MediaFile, use_ai: bool) -> str:
        """자막 텍스트: use_ai면 Gemini caption/summary만 사용(파일명 노출 금지), 아니면 stem."""
        if use_ai and media_file.ai_analysis:
            cap = (media_file.ai_analysis or {}).get("caption") or (media_file.ai_analysis or {}).get("summary")
            if isinstance(cap, str) and cap.strip():
                return cap.strip()[:80]
            return ""
        return Path(media_file.file_path).stem or f"Clip {media_file.order_index + 1}"

    def _create_image_clip(
        self,
        media_file: MediaFile,
        index: int,
        caption: str,
        use_ai: bool = False,
        subtitle_text: str | None = None,
    ) -> Path:
        """
        9:16(1080x1920) 레이아웃으로 이미지를 3초 MP4 클립 생성.
        use_ai=True이고 ai_analysis에 subject_box가 있으면 AI 포커싱/패닝 적용.
        AI 모드에서 upright_path가 있으면 물리 회전된 파일을 사용(EXIF 의존 제거).
        """
        used_upright_file = False
        if use_ai and media_file.ai_analysis and media_file.ai_analysis.get("upright_path"):
            up = self.base_dir / media_file.ai_analysis["upright_path"]
            if up.is_file():
                input_path = up
                used_upright_file = True
                logger.info("[RENDER] Using upright file: %s", up.name)
            else:
                input_path = self.base_dir / media_file.file_path
                logger.warning("[RENDER] upright 파일 없음, 원본 사용: %s", media_file.file_path)
        else:
            input_path = self.base_dir / media_file.file_path
        if not input_path.is_file():
            raise FileNotFoundError(f"미디어 파일 없음: {input_path}")

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._append_log(f"이미지 클립 생성 시작: {media_file.file_path}")
        out_path = self.temp_dir / f"clip_{index:04d}.mp4"

        vf = self._build_916_vf(input_path, media_file=media_file, use_ai=use_ai, used_upright_file=used_upright_file)
        vf = vf.rstrip()
        if vf.endswith("[vid]"):
            vf = vf[:-5]
            if subtitle_text:
                ass_path = self.temp_dir / f"sub_caption_{index:04d}.ass"
                _write_typewriter_ass(subtitle_text, ass_path, CLIP_DURATION_SEC)
                vf += "," + self._build_subtitles_filter(ass_path)
            vf += VF_CFR_IMAGE + "[vid]"
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(input_path),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            vf,
            "-t",
            str(CLIP_DURATION_SEC),
            "-r",
            str(CLIP_FPS),
            *get_video_encoding_args(),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out_path),
        ]
        logger.info("FFmpeg 실행: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.error("FFmpeg stderr: %s", result.stderr)
                logger.error("FFmpeg stdout: %s", result.stdout)
                err_snippet = (result.stderr or result.stdout or "").strip()[:500]
                self._append_log(f"FFmpeg 오류 (exit {result.returncode}): {err_snippet}")
                raise RuntimeError(
                    f"FFmpeg 실패 (exit {result.returncode}): {result.stderr or result.stdout}"
                )
            if not out_path.is_file():
                raise RuntimeError(f"클립 파일이 생성되지 않음: {out_path}")
            return out_path
        except subprocess.TimeoutExpired as e:
            logger.exception("FFmpeg 타임아웃: %s", e)
            self._append_log("FFmpeg 타임아웃 (60초)")
            raise
        except FileNotFoundError:
            logger.exception("FFmpeg를 찾을 수 없습니다. 설치 여부를 확인하세요.")
            raise

    def _create_video_clip(
        self,
        media_file: MediaFile,
        index: int,
        caption: str,
        use_ai: bool = False,
        subtitle_text: str | None = None,
    ) -> Path:
        """
        동영상 MediaFile을 9:16(1080x1920) 레이아웃으로 정규화.
        use_ai=True이면 ai_analysis subject_box 기반 포커싱 적용.
        """
        input_path = self.base_dir / media_file.file_path
        if not input_path.is_file():
            raise FileNotFoundError(f"미디어 파일 없음: {input_path}")

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._append_log(f"동영상 클립 정규화 시작: {media_file.file_path}")
        out_path = self.temp_dir / f"clip_{index:04d}.mp4"

        vf = self._build_916_vf(input_path, media_file=media_file, use_ai=use_ai)
        vf = vf.rstrip()
        if vf.endswith("[vid]"):
            vf = vf[:-5]
            if subtitle_text:
                ass_path = self.temp_dir / f"sub_caption_{index:04d}.ass"
                _write_typewriter_ass(subtitle_text, ass_path, CLIP_DURATION_SEC)
                vf += "," + self._build_subtitles_filter(ass_path)
            vf += VF_CFR_VIDEO + "[vid]"
        cmd = [
            "ffmpeg",
            "-y",
            "-ignore_editlist",
            "1",
            "-i",
            str(input_path),
            "-vf",
            vf,
            "-r",
            str(CLIP_FPS),
            *get_video_encoding_args(),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-af",
            "loudnorm",
            str(out_path),
        ]
        logger.info("동영상 클립 정규화: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("FFmpeg video stderr: %s", result.stderr)
            err_snippet = (result.stderr or result.stdout or "").strip()[:500]
            self._append_log(f"FFmpeg 오류 (exit {result.returncode}): {err_snippet}")
            raise RuntimeError(f"동영상 클립 변환 실패: {result.stderr or result.stdout}")
        if not out_path.is_file():
            raise RuntimeError(f"동영상 클립이 생성되지 않음: {out_path}")
        return out_path

    def _get_clip_durations(self, clip_paths: list[Path]) -> list[float]:
        """각 클립 길이(초) 리스트. 추출 실패 시 기본값 30fps 기준 3초로 방어."""
        out = []
        for p in clip_paths:
            d = self._get_video_duration_sec(p)
            if d is None or d <= 0:
                logger.warning("클립 길이 추출 실패 또는 0: %s → 기본값 %.1f초 사용", p.name, CLIP_DURATION_SEC)
                d = float(CLIP_DURATION_SEC)
            out.append(d)
        return out

    def _fade_duration_for_emotion(self, emotion: str) -> float:
        """감정에 따른 xfade duration. Joy/Excited: 짧고 빠르게(0.4), Peaceful/Sad: 부드럽고 길게(0.8)."""
        if not emotion:
            return 0.6
        e = emotion.strip().lower()
        if e in ("joy", "excited", "energetic", "happy"):
            return 0.4
        if e in ("peaceful", "sad", "calm", "melancholy", "nostalgic"):
            return 0.8
        return 0.6

    def _xfade_transition_for_emotion(self, emotion: str, index: int = 0) -> str:
        """감정에 따른 xfade transition 타입. Excited/Joy: 역동적, Peaceful/Sad: 정적."""
        if not emotion:
            return "fade"
        e = emotion.strip().lower()
        if e in ("joy", "excited", "energetic", "happy"):
            return ["circlecrop", "wipeleft", "slideleft"][index % 3]
        if e in ("peaceful", "sad", "calm", "melancholy", "nostalgic"):
            return ["fade", "dissolve", "pixelize"][index % 3]
        return "fade"

    def _merge_clips_with_xfade(
        self,
        clip_paths: list[Path],
        fade_duration: float = 0.6,
        emotions_per_clip: list[str] | None = None,
    ) -> Path:
        """
        xfade 필터로 클립 사이 부드러운 전환. [인트로(1)] + [본편(N)] = 1+N개.
        emotions_per_clip가 있으면 전환별 감정 기반 duration 적용 (Joy/Excited 짧게, Peaceful/Sad 길게).
        """
        if not clip_paths:
            raise ValueError("병합할 클립이 없습니다.")
        n = len(clip_paths)
        durations = self._get_clip_durations(clip_paths)
        if any(d <= 0 for d in durations):
            logger.warning("일부 클립 길이 0, concat으로 대체")
            return self._merge_clips(clip_paths)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        merged_path = self.temp_dir / "merged.mp4"
        logger.info("클립 병합 중 (xfade): %d개 (1+N=%d) → %s", n, n, merged_path)
        self._append_log(f"{n}개 클립 병합 중 (xfade, 1+{n-1}={n})")

        # 전환별 fade duration 및 transition 타입 (감정 기반). 전환 i는 clip i → clip i+1, incoming emotion = emotions_per_clip[i+1]
        fade_durations: list[float] = []
        transitions: list[str] = []
        for i in range(n - 1):
            incoming_emotion = (emotions_per_clip[i + 1] or "") if emotions_per_clip and i + 1 < len(emotions_per_clip) else ""
            fd = self._fade_duration_for_emotion(incoming_emotion) if incoming_emotion else fade_duration
            fd = min(fd, min(durations[i], durations[i + 1]) * 0.5)
            fade_durations.append(fd)
            trans = self._xfade_transition_for_emotion(incoming_emotion, index=i)
            transitions.append(trans)

        # Video: trim → setpts → format → fps → settb (xfade 직전 CFR 강제)
        parts = []
        for i in range(n):
            parts.append(
                f"[{i}:v]trim=0:{durations[i]:.3f},setpts=PTS-STARTPTS,"
                f"format=yuv420p,fps={CLIP_FPS},settb=AVTB[v{i}]"
            )
        offsets = []
        s = 0.0
        for i in range(n - 1):
            s += durations[i] - fade_durations[i]
            offsets.append(s)
        prev = "[v0]"
        for i in range(1, n):
            fd = fade_durations[i - 1]
            trans = transitions[i - 1]
            out_label = f"[vout]" if i == n - 1 else f"[vx{i}]"
            parts.append(f"{prev}[v{i}]xfade=transition={trans}:duration={fd:.3f}:offset={offsets[i-1]:.3f}{out_label}")
            prev = out_label
        video_filter = ";".join(parts)

        # Audio: concat
        a_parts = [f"[{i}:a]atrim=0:{durations[i]:.3f},asetpts=PTS-STARTPTS[a{i}]" for i in range(n)]
        a_chain = "".join([f"[a{i}]" for i in range(n)]) + f"concat=n={n}:v=0:a=1[aout]"
        audio_filter = ";".join(a_parts) + ";" + a_chain

        filter_complex = video_filter + ";" + audio_filter
        cmd = ["ffmpeg", "-y"]
        for p in clip_paths:
            cmd.extend(["-ignore_editlist", "1", "-i", str(p)])
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            *get_video_encoding_args(),
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "128k",
            str(merged_path),
        ])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error("FFmpeg xfade stderr: %s", result.stderr)
            raise RuntimeError(f"xfade 병합 실패: {result.stderr or result.stdout}")
        if not merged_path.is_file():
            raise RuntimeError(f"병합 파일 미생성: {merged_path}")
        logger.info("클립 병합 완료 (xfade): %s", merged_path)
        self._append_log("클립 병합 완료")
        return merged_path

    def _merge_clips(self, clip_paths: list[Path]) -> Path:
        """
        concat 데뮤저로 클립들을 재인코딩 없이 병합. 순서: [인트로] + [본편].
        """
        if not clip_paths:
            raise ValueError("병합할 클립이 없습니다.")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        concat_path = self.temp_dir / "concat.txt"
        lines = [f"file '{p.resolve().as_posix()}'" for p in clip_paths]
        try:
            concat_path.write_text("\n".join(lines), encoding="utf-8")
        except OSError as e:
            logger.error("concat.txt 쓰기 실패: %s", e)
            raise RuntimeError(f"concat 리스트 저장 실패: {e}") from e
        merged_path = self.temp_dir / "merged.mp4"
        logger.info("클립 병합 중: %s개 → %s", len(clip_paths), merged_path)
        self._append_log(f"{len(clip_paths)}개 클립 병합 중")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_path),
            "-c", "copy",
            str(merged_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("FFmpeg concat stderr: %s", result.stderr)
            raise RuntimeError(f"클립 병합 실패: {result.stderr or result.stdout}")
        if not merged_path.is_file():
            raise RuntimeError(f"병합 파일 미생성: {merged_path}")
        logger.info("클립 병합 완료: %s", merged_path)
        self._append_log("클립 병합 완료")
        return merged_path

    def _make_static_clip_from_video(
        self, source_path: Path, out_path: Path, duration_sec: float = 3.0
    ) -> Path:
        """
        source_path 영상의 첫 프레임만 사용해, duration_sec 동안 움직임 없이 재생하는 정적 클립 생성.
        1080x1920, 30fps, yuv420p, 무음. 아웃로용.
        """
        if not source_path.is_file():
            raise FileNotFoundError(f"정적 클립 소스 없음: {source_path}")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        frame_path = self.temp_dir / "outro_static_frame.png"
        try:
            extract = [
                "ffmpeg", "-y", "-i", str(source_path),
                "-vframes", "1", "-f", "image2", str(frame_path),
            ]
            r1 = subprocess.run(extract, capture_output=True, text=True, timeout=30)
            if r1.returncode != 0 or not frame_path.is_file():
                raise RuntimeError(f"첫 프레임 추출 실패: {r1.stderr or r1.stdout}")
            vf = f"fps=30,scale={CANVAS_W}:{CANVAS_H},format=yuv420p"
            encode = [
                "ffmpeg", "-y", "-loop", "1", "-i", str(frame_path),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", str(duration_sec), "-vf", vf,
                *get_video_encoding_args(),
                "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", str(out_path),
            ]
            r2 = subprocess.run(encode, capture_output=True, text=True, timeout=60)
            if r2.returncode != 0 or not out_path.is_file():
                raise RuntimeError(f"정적 클립 인코딩 실패: {r2.stderr or r2.stdout}")
            return out_path
        finally:
            if frame_path.is_file():
                try:
                    frame_path.unlink()
                except OSError:
                    pass

    def _get_video_duration_sec(self, video_path: Path) -> float:
        """ffprobe로 영상 길이(초) 반환. 실패 시 0.0 (호출측에서 기본값 적용)."""
        try:
            cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0 or not result.stdout.strip():
                logger.debug("ffprobe duration 실패: %s", video_path.name)
                return 0.0
            return float(result.stdout.strip())
        except (ValueError, subprocess.TimeoutExpired) as e:
            logger.debug("duration 추출 예외 %s: %s", video_path.name, e)
            return 0.0

    def _get_cinematic_fontfile_opt(self) -> str:
        """시네마틱 자막용 fontfile= 옵션 (static/fonts 우선, FFmpeg 이스케이프 적용)."""
        for name in (CINEMATIC_FONT_PRIMARY, CINEMATIC_FONT_FALLBACK):
            escaped = get_font_path_escaped_for_ffmpeg(name)
            if escaped:
                return f"fontfile='{escaped}':"
        return ""

    def _get_english_caption_fontfile_opt(self) -> str:
        """영문 감성 자막용 fontfile= 옵션 (앨범용 영문 폰트 우선)."""
        for name in (ENGLISH_CAPTION_FONT_PRIMARY, ENGLISH_CAPTION_FONT_FALLBACK):
            escaped = get_font_path_escaped_for_ffmpeg(name)
            if escaped:
                return f"fontfile='{escaped}':"
        return ""

    def _escape_drawtext(self, raw: str) -> str:
        """FFmpeg drawtext text= 값 이스케이프 (', \\, :)."""
        return (raw or "").replace("\\", "\\\\").replace("'", "'\\''").replace(":", "\\:")

    def _build_subtitles_filter(self, ass_path: Path) -> str:
        """subtitles= 필터 문자열. 경로 내 ', : 이스케이프로 Option not found 방지. fontsdir로 앨범 폰트 로드."""
        p = ass_path.resolve().as_posix().replace("'", "'\\''").replace(":", "\\:")
        fonts_dir = get_fonts_dir().resolve().as_posix().replace("'", "'\\''").replace(":", "\\:")
        return f"subtitles='{p}':fontsdir='{fonts_dir}'"

    def _build_subtitle_drawtext(self, subtitle_text: str) -> str:
        """영문 감성 자막용 drawtext 필터. 하단 15%, 아이보리·그림자, 타이프라이터 없이 전체 노출."""
        label = self._escape_drawtext((subtitle_text or "").strip()[:60]) or " "
        font_opt = self._get_english_caption_fontfile_opt()
        return (
            f"drawtext=text='{label}':{font_opt}fontsize={ENGLISH_CAPTION_FONT_SIZE}:"
            f"fontcolor=0xF9F9F9:shadowcolor=black@0.4:shadowx=2:shadowy=2:"
            f"x=(w-tw)/2:y=h-th-{ENGLISH_CAPTION_Y_OFFSET}"
        )

    def _add_bgm(
        self,
        video_path: Path,
        media_files: list[MediaFile] | None = None,
        use_ai: bool = False,
    ) -> Path:
        """
        감정 기반 BGM 선정(use_ai 시), 더킹(attack 0.5초), 마지막 2초 페이드아웃 적용.
        BGM 없으면 영상만 복사.
        """
        try:
            self.final_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("최종 출력 디렉토리 생성 실패: %s", e)
            raise
        out_path = self.final_dir / "output.mp4"

        if not video_path.is_file():
            fallback = self.temp_dir / "merged.mp4"
            if fallback.is_file():
                logger.warning("BGM 입력 파일 없음, 병합본 사용: %s -> %s", video_path, fallback)
                video_path = fallback
            else:
                raise FileNotFoundError(
                    f"BGM 입력 영상 없음: {video_path}. 병합/오버레이 단계 실패 또는 temp 조기 삭제 가능성."
                )

        if use_ai and media_files:
            emotion = get_dominant_emotion(media_files)
            bgm_path = select_bgm_path(emotion, self.base_dir)
        else:
            bgm_path = self.base_dir / "static" / "audio" / "default_bgm.mp3"

        if not bgm_path.is_file():
            logger.warning("BGM 파일 없음: %s → 영상만 출력", bgm_path)
            try:
                shutil.copy2(video_path, out_path)
            except OSError as e:
                logger.error("영상 복사 실패 (BGM 없음 경로): %s", e)
                raise
            logger.info("최종 출력 (BGM 없음): %s", out_path)
            return out_path

        logger.info("BGM 더킹 합성 중: %s + %s", video_path, bgm_path)
        self._append_log("BGM 더킹 합성 중")
        duration = self._get_video_duration_sec(video_path)
        fade_st = max(0.0, duration - 2.0)
        # 더킹: 말소리/큰 소리 구간에서 BGM을 ~30% 수준으로 부드럽게 감소 (threshold/ratio로 감소량 조절)
        filter_complex = (
            "[1:a]volume=1.0[bgm];"
            "[bgm][0:a]sidechaincompress=threshold=0.02:ratio=12:attack=500:release=300:makeup=1:mix=1[bgm_duck];"
            "[0:a][bgm_duck]amix=2:normalize=1[aout]"
        )
        if fade_st > 0:
            filter_complex += f";[aout]afade=t=out:st={fade_st:.2f}:d=2[aout2]"
            map_audio = "[aout2]"
        else:
            map_audio = "[aout]"

        cmd = [
            "ffmpeg", "-y", "-i", str(video_path), "-i", str(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", map_audio,
            "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("FFmpeg BGM stderr: %s", result.stderr)
            raise RuntimeError(f"BGM 합성 실패: {result.stderr or result.stdout}")
        logger.info("최종 출력 (BGM 포함, 더킹·페이드 적용): %s", out_path)
        self._append_log("최종 출력 저장 완료")
        return out_path

    def _cleanup(self) -> None:
        """storage/temp/{project_id} 폴더 전체 삭제. 없거나 삭제 실패해도 영상 생성은 성공으로 유지."""
        if not self.temp_dir:
            return
        if not self.temp_dir.exists():
            return
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            logger.info("임시 폴더 삭제: %s", self.temp_dir)
            self._append_log("임시 파일 정리 완료")
        except Exception as e:
            logger.warning("임시 폴더 삭제 실패(무시): %s", e)

    def _run(self, use_ai: bool = False) -> Path | None:
        """
        표준 5단계 파이프라인: [1] 큐레이션 [2] 인트로 콜라주 1개 [3] 본편 클립 [4] 자막·BGM [5] 병합.
        use_ai: True면 AI 자막·subject_box Ken Burns·인트로 1개만 적용. 아웃로 없음.
        """
        self._append_log("영상 생성 파이프라인 시작")
        db = SessionLocal()
        try:
            media_files = get_media_files_by_project(db, self.project_id)
            project = get_project(db, self.project_id)
            intro_title = (getattr(project, "title", None) or "").strip() or "Our Precious Memories"
        finally:
            db.close()
        # 1단계: 유니크 리스트만 사용 (video_service Curate에서 중복 90% 제거 후 is_selected=True만 남김)
        media_files = [mf for mf in media_files if getattr(mf, "is_selected", True)]
        if not media_files:
            logger.warning("프로젝트 %s에 미디어 파일이 없습니다.", self.project_id)
            return None

        image_media = [mf for mf in media_files if mf.file_type == "image"]
        missing = [mf for mf in image_media if not mf.ai_analysis]
        if use_ai and missing:
            for mf in missing:
                logger.critical(
                    "[CRITICAL] AI data missing for media_id: %s. Aborting AI render.",
                    mf.id,
                )
            self._append_log("오류: AI 분석 데이터가 없어 렌더링을 중단했습니다. 분석 완료 후 다시 시도해 주세요.")
            db = SessionLocal()
            try:
                update_project_status(db, self.project_id, "FAILED")
            finally:
                db.close()
            return None

        if use_ai:
            logger.info("---------- STARTING AI RENDERING MODE (9:16) ----------")

        # 1+N 구조: 인트로 1개(score 상위 3~4장 콜라주) + 본편 N개(유니크 리스트 전체 각 1클립)
        # 인트로 콜라주에 사용된 사진도 본편 시퀀스에서 반드시 다시 단일 클립으로 등장.
        intro_group: list[MediaFile] = []
        if use_ai:
            intro_group = get_intro_images(media_files)  # 원본 리스트 변형 없음
        main_media_list = list(media_files)  # 유니크 리스트 전체(인트로와 중복 허용)
        expected_clips = 1 + len(main_media_list) if intro_group else len(main_media_list)
        logger.info(
            "본편 클립 수: %d (전체 미디어 %d장). 병합 시 1+N=%d 예상",
            len(main_media_list), len(media_files), expected_clips,
        )
        self._append_log(f"본편 {len(main_media_list)}장 → 총 {expected_clips}개 클립 (1+{len(main_media_list)})")

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        clips: list[Path] = []
        intro_clip_path: Path | None = None

        if use_ai and not intro_group:
            self._append_log("인트로 스킵: 이미지 미디어 없음(또는 score 상위 이미지 없음)")
        if intro_group:
            self._append_log("인트로 콜라주 생성 중 (score 상위 2~3장)")
            logger.info("[AI CLIP] Collage generated (intro, 1+%d)", len(main_media_list))
            summary_intro = (intro_group[0].ai_analysis or {}).get("summary") or ""
            if isinstance(summary_intro, str):
                summary_intro = summary_intro.strip()[:80]
            try:
                intro_path = self.temp_dir / "collage_intro.mp4"
                render_collage_clip(
                    intro_group, self.base_dir, intro_path,
                    summary_text=summary_intro or "함께한 순간",
                    title=intro_title,
                )
                clips.append(intro_path)
                intro_clip_path = intro_path
                self._append_log("인트로 콜라주 생성 완료")
            except Exception as e:
                logger.warning("인트로 콜라주 실패, 스킵: %s", e)
                self._append_log(f"인트로 콜라주 실패: {e}")

        # 자막 노출: 전체 클립의 약 40~50%만 영문 감성 자막 표시 (score 상위 우선)
        subtitle_indices: set[int] = set()
        if use_ai and main_media_list:
            n_subs = max(0, min(len(main_media_list), int(round(len(main_media_list) * SUBTITLE_RATIO))))
            if n_subs > 0:
                sorted_by_score = sorted(
                    range(len(main_media_list)),
                    key=lambda i: float((main_media_list[i].ai_analysis or {}).get("score") or 0),
                    reverse=True,
                )
                subtitle_indices = set(sorted_by_score[:n_subs])

        # 본편 시퀀스: 전체 N장 각각 1클립 (선정된 클립에만 영문 자막 합성)
        for index, mf in enumerate(main_media_list):
            caption = self._get_caption(mf, use_ai)
            subtitle_text: str | None = None
            if use_ai and index in subtitle_indices and mf.ai_analysis:
                raw = (mf.ai_analysis or {}).get("english_caption")
                if isinstance(raw, str) and raw.strip():
                    subtitle_text = raw.strip()[:60]
            if mf.file_type == "image":
                logger.info("이미지 클립 생성 중: [%s] %s", index, mf.file_path)
                clip_path = self._create_image_clip(mf, index, caption, use_ai=use_ai, subtitle_text=subtitle_text)
            elif mf.file_type == "video":
                logger.info("동영상 클립 생성 중: [%s] %s", index, mf.file_path)
                clip_path = self._create_video_clip(mf, index, caption, use_ai=use_ai, subtitle_text=subtitle_text)
            else:
                logger.info("지원하지 않는 타입 건너뜀: order_index=%s type=%s", mf.order_index, mf.file_type)
                continue
            clips.append(clip_path)

        # 아웃로: 인트로 콜라주 첫 프레임만 정적으로 표시 (효과 없음)
        outro_added = False
        if use_ai and intro_clip_path is not None:
            outro_path = self.temp_dir / "collage_outro_static.mp4"
            try:
                self._make_static_clip_from_video(intro_clip_path, outro_path, duration_sec=1.0)
                clips.append(outro_path)
                outro_added = True
                self._append_log("아웃로: 인트로 콜라주 화면 정적 표시")
            except Exception as e:
                logger.warning("아웃로 정적 클립 생성 실패, 스킵: %s", e)
                self._append_log(f"아웃로 정적 클립 실패: {e}")

        if not clips:
            warn_msg = "생성된 클립이 없습니다."
            logger.warning(warn_msg)
            self._append_log(warn_msg)
            return None

        # 병합: [인트로] + [본편 N] + [아웃로(있으면)]. AI 시 감정별 xfade duration
        logger.info("FFmpeg 병합 대상 클립 수: %d (1+%d%s)", len(clips), len(main_media_list), "+1(아웃로)" if outro_added else "")
        if len(clips) >= 2 and use_ai:
            emotions_per_clip = (
                [""] * (1 if intro_group else 0)
                + [(mf.ai_analysis or {}).get("emotion", "") or "" for mf in main_media_list]
                + ([""] if outro_added else [])
            )
            merged = self._merge_clips_with_xfade(clips, emotions_per_clip=emotions_per_clip)
        elif len(clips) >= 2:
            merged = self._merge_clips_with_xfade(clips)
        else:
            merged = self._merge_clips(clips)
        # Phase 4: 자막은 클립별 영문 감성(english_caption)만 사용, 전체의 약 45% 클립에만 노출.
        # 기존 한글 전체 오버레이(_apply_cinematic_overlay) 제거됨 → 병합본 그대로 사용.
        overlay_path = merged
        if not overlay_path.is_file():
            raise FileNotFoundError(f"BGM 입력 영상 없음: {overlay_path}. 병합/오버레이 단계 확인 필요.")
        final_path = self._add_bgm(overlay_path, media_files=media_files if use_ai else None, use_ai=use_ai)
        try:
            self._cleanup()
        except Exception as e:
            logger.warning("정리 단계 실패(무시, 영상은 완료됨): %s", e)

        self._append_log("영상 생성 파이프라인 완료")
        return final_path

    def create_highlight(self, use_ai: bool = False) -> Path | None:
        """
        하이라이트 영상 생성 진입점. use_ai에 따라 AI(Gemini) 분석 결과를 자막에 반영할지 분기.
        """
        return self._run(use_ai=use_ai)
