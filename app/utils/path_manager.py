"""
폰트 등 정적 에셋 경로 유틸. static/fonts/ 절대 경로 반환 및 FFmpeg drawtext용 이스케이프.
OS별 경로(Windows 백슬래시 등) 차이를 고려하여 FFmpeg 필터에서 오류가 나지 않도록 처리.
"""
import os
from pathlib import Path


def get_project_root() -> Path:
    """프로젝트 루트(v4) 절대 경로."""
    return Path(__file__).resolve().parent.parent.parent


def get_fonts_dir() -> Path:
    """static/fonts/ 디렉토리 절대 경로."""
    return get_project_root() / "static" / "fonts"


def get_font_path(font_filename: str) -> Path | None:
    """
    static/fonts/ 내 폰트 파일 절대 경로 반환. 없으면 None.
    """
    path = get_fonts_dir() / font_filename
    if not path.is_file():
        return None
    return path.resolve()


def get_font_path_escaped_for_ffmpeg(font_filename: str) -> str:
    """
    drawtext fontfile= 에 넣을 수 있도록 이스케이프된 경로 문자열 반환.
    - OS 경로를 POSIX 스타일로 통일(Windows \\ -> /)
    - 경로 내 single quote는 FFmpeg 필터에서 안전하도록 이스케이프
    - 파일이 없으면 빈 문자열(엔진에서 시스템 폰트 fallback)
    """
    path = get_font_path(font_filename)
    if path is None:
        return ""
    # POSIX 스타일로 통일하여 FFmpeg/크로스플랫폼 호환
    raw = path.as_posix()
    # FFmpeg filter 값 내 single quote 이스케이프: ' -> '\''
    escaped = raw.replace("'", "'\\''")
    # 옵션 구분자(:)로 파싱되지 않도록 경로 내 콜론 이스케이프 (Windows C:/ 등)
    escaped = escaped.replace(":", "\\:")
    return escaped


# 시네마틱 자막 우선 사용 폰트 파일명
CINEMATIC_FONT_PRIMARY = "NanumPenScript-Regular.ttf"
CINEMATIC_FONT_FALLBACK = "NotoSansKR[wght].ttf"

# 영문 감성 자막 전용 (앨범용, 타이프라이터 스타일). static/fonts/ 에 해당 파일 추가 필요
ENGLISH_CAPTION_FONT_PRIMARY = "SpecialElite-Regular.ttf"
ENGLISH_CAPTION_FONT_FALLBACK = "NotoSansKR[wght].ttf"
