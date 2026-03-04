"""
폰트 등 정적 에셋 자동 다운로드. static/fonts/ 생성 후 Google Fonts에서 폰트 다운로드.
실패 시 시스템 기본 폰트 사용(엔진에서 fallback 처리).
사용: python scripts/setup_assets.py
"""
import logging
import os
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "static" / "fonts"

FONT_URLS = {
    "NanumPenScript-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/nanumpenscript/NanumPenScript-Regular.ttf",
    "NotoSansKR[wght].ttf": "https://github.com/google/fonts/raw/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf",
    # Phase 4-B: Classic Serif, Handwriting, Typewriter
    "PlayfairDisplay[wght].ttf": "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    "DancingScript[wght].ttf": "https://github.com/google/fonts/raw/main/ofl/dancingscript/DancingScript%5Bwght%5D.ttf",
    "SpecialElite-Regular.ttf": "https://github.com/google/fonts/raw/main/apache/specialelite/SpecialElite-Regular.ttf",
}


def download_font(url: str, dest: Path, timeout: int = 60) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Flairy-Setup/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as e:
        logger.warning("다운로드 실패 %s: %s", dest.name, e)
        return False


def main() -> None:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("static/fonts 디렉토리 준비: %s", FONTS_DIR)

    for filename, url in FONT_URLS.items():
        dest = FONTS_DIR / filename
        if dest.is_file():
            logger.info("이미 존재: %s", filename)
            continue
        logger.info("다운로드 중: %s", filename)
        if download_font(url, dest):
            logger.info("저장 완료: %s", dest)
        else:
            logger.warning("실패 시 엔진에서 시스템 기본 폰트를 사용합니다.")

    logger.info("폰트 세팅 완료. 엔진은 static/fonts/ 우선, 없으면 시스템 폰트를 사용합니다.")


if __name__ == "__main__":
    main()
