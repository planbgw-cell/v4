"""
미디어(이미지) EXIF 회전 로직 단일화.
Rule-based와 AI 엔진이 동일한 회전 기준을 쓰도록, 회전 정보와 "세운" 이미지 로딩을 한 곳에서 제공.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 이미지 확장자: EXIF Orientation 적용 대상
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".bmp", ".tiff", ".tif")

# EXIF Orientation (274) → 표시용 회전 각도
_ORIENTATION_TO_ROTATION = {1: 0, 2: 0, 3: 180, 4: 0, 5: 90, 6: 90, 7: 270, 8: 270}

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None  # type: ignore[misc, assignment]
    ImageOps = None  # type: ignore[misc, assignment]

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pillow_heif = None  # type: ignore[misc, assignment]

try:
    import piexif
except ImportError:
    piexif = None  # type: ignore[misc, assignment]
    logger.warning("piexif 미설치. JPEG EXIF 회전 감지 안정화를 위해 pip install piexif 권장.")


def _exif_orientation_to_rotation(orient: int) -> int:
    return _ORIENTATION_TO_ROTATION.get(orient, 0)


def _orientation_from_piexif(data: dict) -> int | None:
    """piexif 딕셔너리에서 Orientation 값 추출. 0th → Exif → Interop 순."""
    for key in ("0th", "Exif", "Interop"):
        if key in data and isinstance(data[key], dict):
            orient = data[key].get(274, data[key].get(0x0112, None))
            if orient is not None and 1 <= orient <= 8:
                return int(orient)
    return None


def _get_rotation_from_exif(path: Path, suffix: str) -> int:
    """
    삼중 방어: (1) piexif로 JPEG 직접 파싱, (2) Pillow getexif, (3) 호출측 load_image_upright에서 exif_transpose.
    반환: 0|90|180|270. 실패 시 0.
    """
    path = Path(path)
    orient_raw: int | None = None
    method = "none"

    # 1순위: JPEG인 경우 piexif로 0th/Exif/Interop IFD에서 274 직접 읽기
    if suffix in (".jpg", ".jpeg", ".jpe") and piexif is not None:
        try:
            data = piexif.load(str(path))
            orient_raw = _orientation_from_piexif(data)
            if orient_raw is not None:
                method = "piexif"
        except Exception as e:  # noqa: BLE001
            logger.debug("piexif 로드 실패 %s: %s", path.name, e)

    # HEIC/HEIF: pillow_heif + piexif
    if orient_raw is None and suffix in (".heic", ".heif"):
        if pillow_heif is not None and piexif is not None:
            try:
                heif_file = pillow_heif.open_heif(str(path))
                if heif_file:
                    img = heif_file[0]
                    exif_bytes = img.info.get("exif") if hasattr(img, "info") else None
                    if exif_bytes:
                        data = piexif.load(exif_bytes)
                        orient_raw = _orientation_from_piexif(data)
                        if orient_raw is not None:
                            method = "piexif_heic"
            except Exception as e:  # noqa: BLE001
                logger.debug("HEIC EXIF 예외 %s: %s", path.name, e)

    # 2순위: Pillow getexif
    if orient_raw is None and Image is not None:
        try:
            with Image.open(path) as img:
                exif = img.getexif() if hasattr(img, "getexif") else {}
                orient_raw = exif.get(274, exif.get(0x0112, 1))
                if orient_raw is not None and 1 <= orient_raw <= 8:
                    method = "pillow"
                else:
                    orient_raw = 1
        except Exception as e:  # noqa: BLE001
            logger.debug("Pillow EXIF 예외 %s: %s", path.name, e)

    if orient_raw is None or not (1 <= orient_raw <= 8):
        orient_raw = 1
    rotation = _exif_orientation_to_rotation(orient_raw)
    logger.info(
        "[EXIF_DEBUG] File: %s, Method: %s, Orientation: %s, Target_Rotate: %s",
        path.name, method, orient_raw, rotation,
    )
    if piexif is None and suffix.lower() in (".jpg", ".jpeg"):
        logger.debug("piexif 미설치 시 JPEG EXIF 감지가 불안정할 수 있음. pip install piexif 권장.")
    return rotation


def get_standard_orientation(path: Path) -> dict:
    """
    이미지 파일의 표준 방향 정보. EXIF 반영 후 논리 크기·회전.
    반환: {"width": int, "height": int, "rotation": 0|90|180|270}.
    회전 90/270이면 호출측에서 width/height 스왑해 논리 크기로 사용.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise ValueError(f"지원하지 않는 이미지 확장자: {suffix}")

    if Image is None:
        raise RuntimeError("PIL이 필요합니다. Pillow를 설치하세요.")

    with Image.open(path) as img:
        w, h = img.size  # raw pixel dimensions
    rotation = _get_rotation_from_exif(path, suffix)
    return {"width": w, "height": h, "rotation": rotation}


def load_image_upright(path: Path):
    """
    이미지를 열어 EXIF Orientation에 따라 물리적으로 올바른 방향으로 회전한 뒤 반환.
    AI 전처리 등 "세운" 이미지가 필요할 때 사용.
    반환: PIL.Image (호출측에서 convert("RGB") 등 추가 처리).
    """
    path = Path(path)
    if Image is None or ImageOps is None:
        raise RuntimeError("PIL이 필요합니다. Pillow를 설치하세요.")
    img = Image.open(path).copy()
    return ImageOps.exif_transpose(img)
