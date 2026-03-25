from pathlib import Path

from PIL import Image

CANVAS_W = 1080
CANVAS_H = 1920


def ensure_fhd_portrait(input_path: Path, output_path: Path) -> Path:
    """
    이미지를 1080x1920 검은 배경에 비율 유지(center-fit)로 배치해 JPEG로 저장한다.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(input_path) as im:
        src = im.convert("RGB")
        src_w, src_h = src.size
        if src_w <= 0 or src_h <= 0:
            raise ValueError(f"유효하지 않은 이미지 크기: {src.size}")

        scale = min(CANVAS_W / float(src_w), CANVAS_H / float(src_h))
        new_w = max(1, int(round(src_w * scale)))
        new_h = max(1, int(round(src_h * scale)))
        resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (0, 0, 0))
        off_x = (CANVAS_W - new_w) // 2
        off_y = (CANVAS_H - new_h) // 2
        canvas.paste(resized, (off_x, off_y))
        canvas.save(output_path, format="JPEG", quality=96, subsampling=0, optimize=True)

    return output_path
