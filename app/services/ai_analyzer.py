"""
AI 미디어 분석기. 전처리 → Gemini 2.5 Flash 분석 → 구조화된 JSON 반환.
render_rule_based 등 기존 엔진 로직을 참조하지 않으며, 미디어 읽기·분석·결과 반환만 담당.
"""
import base64
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from app.utils.media_processor import get_standard_orientation, load_image_upright

logger = logging.getLogger(__name__)

# 물리 회전 저장 시 품질 (원본에 가깝게)
UPRIGHT_JPEG_QUALITY = 95

try:
    import google.generativeai as genai
except ImportError:
    genai = None  # type: ignore[misc, assignment]

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[misc, assignment]

# Gemini 2.5 Flash (안정 버전)
GEMINI_MODEL = "gemini-2.5-flash"
LONG_EDGE_MAX = 1024
JPEG_QUALITY = 85
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 2.0

# 구조화 출력용 시스템 프롬프트: score, emotion, subject_box, description(한국어), english_caption(영문 감성)
SYSTEM_INSTRUCTION = """You are an expert at analyzing photos for short-form vertical (9:16) highlight video production.
Your task is to analyze each image and return exactly one valid JSON object, with no markdown or extra text.

Required JSON keys (strict format):
- "score": number 0-100, image quality/suitability for 9:16 vertical highlight (composition, face visibility, no important crop).
- "emotion": string, one of: Joy, Peaceful, Sad, Excited, Calm, Romantic, Nostalgic, Energetic, or similar single dominant mood in English.
- "subject_box": array of exactly 4 numbers [ymin, xmin, ymax, xmax], normalized 0-1000. Bounding box of the main subject (person/face) in the image. If no clear subject use [250, 250, 750, 750] (center region).
- "description": string, short emotional caption in Korean for video subtitle (max 80 chars, no file names).
- "english_caption": string, a short poetic English phrase matching the photo mood, suitable for album or overlay (e.g. "Golden hour memories", "Unforgettable smile", "Stay forever in this moment"). Max 60 chars.

Output only the JSON object. No code block, no explanation."""

USER_PROMPT = "Analyze this image for 9:16 vertical highlight video. Return only one JSON object with score (0-100), emotion, subject_box [ymin,xmin,ymax,xmax] (0-1000), description (Korean), and english_caption (short poetic English phrase for mood)."

# 로그용: rotation 각도 -> EXIF Orientation 태그
_ROTATION_TO_EXIF_TAG = {0: 1, 90: 6, 180: 3, 270: 8}


class ImagePreprocessor:
    """EXIF 보정 후 세운 이미지 + 긴 축 1024px 리사이즈. 세로/가로 판별 로그."""

    def __init__(self, long_edge_max: int = LONG_EDGE_MAX) -> None:
        self.long_edge_max = long_edge_max

    def run(self, image_path: Path) -> Any:
        """물리적 회전 보정 후 리사이즈된 PIL Image 반환. 실패 시 예외. (저장·메타는 analyze_image에서 처리)"""
        if Image is None:
            raise RuntimeError("PIL이 필요합니다. Pillow를 설치하세요.")
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"이미지 없음: {path}")

        img = load_image_upright(path)
        img = img.convert("RGB")
        w, h = img.size
        long_edge = max(w, h)
        if long_edge > self.long_edge_max:
            scale = self.long_edge_max / long_edge
            new_w = int(round(w * scale))
            new_h = int(round(h * scale))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            w, h = new_w, new_h

        orientation = "portrait" if h >= w else "landscape"
        logger.info(
            "[AI Preprocess] %s -> %dx%d (%s), long_edge=%d",
            path.name, w, h, orientation, max(w, h),
        )
        return img


class FlairyAIAnalyzer:
    """
    전처리 → Gemini 분석 → 예외/재시도가 분리된 객체 지향 분석기.
    DB 저장은 호출측(video_service)에서 수행.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        if genai is None:
            raise ValueError("google-generativeai 패키지가 필요합니다. pip install google-generativeai")
        genai.configure(api_key=self._api_key)
        self._model = genai.GenerativeModel(
            GEMINI_MODEL,
            system_instruction=SYSTEM_INSTRUCTION,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )
        self._preprocessor = ImagePreprocessor(long_edge_max=LONG_EDGE_MAX)

    def _encode_image(self, pil_image: "Image.Image") -> str:
        """PIL 이미지를 JPEG bytes → base64 문자열."""
        buf = io.BytesIO()
        pil_image.save(buf, format="JPEG", quality=JPEG_QUALITY)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """응답 텍스트에서 JSON만 추출해 파싱. 필수 키 보정 및 subject_box 로그."""
        text = (text or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text).strip()
        if not text:
            return self._fallback_result("empty_response")
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                return self._fallback_result("response_not_dict")

            score_raw = data.get("score")
            if isinstance(score_raw, (int, float)):
                score_100 = max(0, min(100, float(score_raw)))
                data["score_100"] = int(score_100)
                data["score"] = score_100 / 100.0  # 하위 호환: 0~1
            else:
                data.setdefault("score", 0.5)
                data.setdefault("score_100", 50)

            data.setdefault("emotion", "")
            data.setdefault("description", "")
            data.setdefault("english_caption", "")
            if isinstance(data.get("description"), str):
                desc = data["description"].strip()[:80]
                data["description"] = desc
                data["caption"] = desc  # 하위 호환
                data["summary"] = desc
            if isinstance(data.get("english_caption"), str):
                data["english_caption"] = data["english_caption"].strip()[:60]

            box = data.get("subject_box")
            if isinstance(box, (list, tuple)) and len(box) == 4:
                try:
                    box = [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
                    data["subject_box"] = box
                    logger.info("[AI Analyze] subject_box (0-1000): %s", box)
                except (TypeError, ValueError):
                    data["subject_box"] = [250, 250, 750, 750]
            else:
                data["subject_box"] = [250, 250, 750, 750]

            return data
        except json.JSONDecodeError:
            return self._fallback_result("invalid_json")

    def _fallback_result(self, reason: str) -> dict[str, Any]:
        return {
            "error": reason,
            "caption": "",
            "summary": "",
            "description": "",
            "english_caption": "",
            "score": 0.5,
            "score_100": 50,
            "emotion": "",
            "subject_box": [250, 250, 750, 750],
        }

    def analyze_image(self, image_path: Path) -> dict[str, Any]:
        """
        이미지 한 장 분석: 물리 회전(EXIF bake) → 전처리 → Gemini 호출(지수 백오프 최대 3회) → 구조화 결과 반환.
        회전이 필요하면 세운 이미지를 _upright 파일로 저장해, 렌더러가 EXIF 없이 올바른 방향을 쓰도록 함.
        """
        path = Path(image_path)
        if not path.is_file():
            return self._fallback_result("file_not_found")

        if Image is None:
            return self._fallback_result("pil_required")

        # 1) 원본 방향·크기 (실패 시 0,0,0)
        try:
            probe = get_standard_orientation(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("get_standard_orientation 실패 %s: %s (upright 저장은 transpose 결과로 판단)", path.name, e)
            probe = {"width": 0, "height": 0, "rotation": 0}
        raw_w, raw_h = probe["width"], probe["height"]
        rotation = probe["rotation"]
        logger.debug("[AI Analyze] %s raw=%sx%s rotation=%s", path.name, raw_w, raw_h, rotation)

        # 2) EXIF 기준으로 픽셀을 물리적으로 세움 (ImageOps.exif_transpose 우선)
        img = load_image_upright(path)
        img = img.convert("RGB")
        w, h = img.size
        upright_path: Path | None = None
        need_bake = rotation != 0 or (raw_w != w or raw_h != h)
        if not need_bake:
            logger.debug("[AI Analyze] %s no bake (raw=%sx%s after=%sx%s)", path.name, raw_w, raw_h, w, h)
        if need_bake:
            upright_path = path.parent / (path.stem + "_upright.jpg")
            try:
                img.save(upright_path, "JPEG", quality=UPRIGHT_JPEG_QUALITY)
            except Exception as e:  # noqa: BLE001
                logger.warning("upright 저장 실패 %s: %s", upright_path, e)
                upright_path = None

        # 3) Gemini용 리사이즈 (1024px). 저장된 결과는 EXIF 없이도 똑바로 선 이미지
        long_edge = max(w, h)
        if long_edge > LONG_EDGE_MAX:
            scale = LONG_EDGE_MAX / long_edge
            img = img.resize(
                (int(round(w * scale)), int(round(h * scale))),
                Image.Resampling.LANCZOS,
            )
        processed_w, processed_h = img.size[0], img.size[1]
        exif_tag = _ROTATION_TO_EXIF_TAG.get(rotation, 1)
        logger.info(
            "[NORMALIZER] File: %s, Original: %sx%s (EXIF %s) -> Physical Rotate Applied -> Processed: %sx%s",
            path.name, raw_w, raw_h, exif_tag, processed_w, processed_h,
        )

        b64_data = self._encode_image(img)
        image_part = {"inline_data": {"mime_type": "image/jpeg", "data": b64_data}}
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = self._model.generate_content([image_part, USER_PROMPT])
                text = (response.text or "").strip()
                result = self._parse_json_response(text)
                result["width"] = w
                result["height"] = h
                if upright_path is not None:
                    result["upright_path"] = str(upright_path.resolve())
                return result
            except Exception as e:
                last_exc = e
                msg = str(e).lower()
                if "429" in msg or "resource_exhausted" in msg or "quota" in msg or "503" in msg or "unavailable" in msg:
                    delay = INITIAL_BACKOFF_SEC * (2**attempt)
                    logger.warning(
                        "Gemini 할당량/일시 오류, %.1fs 후 재시도 (%d/%d): %s",
                        delay, attempt + 1, MAX_RETRIES, path.name,
                    )
                    time.sleep(delay)
                else:
                    logger.exception("Gemini 분석 실패: %s", path)
                    out = self._fallback_result(str(e))
                    out["width"] = w
                    out["height"] = h
                    if upright_path is not None:
                        out["upright_path"] = str(upright_path.resolve())
                    return out

        logger.warning("Gemini 재시도 모두 실패: %s", path)
        out = self._fallback_result(str(last_exc) if last_exc else "max_retries")
        out["width"] = w
        out["height"] = h
        if upright_path is not None:
            out["upright_path"] = str(upright_path.resolve())
        return out
