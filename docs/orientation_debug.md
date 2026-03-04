# 세로 사진 방향/렌더 진단 (rule vs AI)

## 확인 절차 요약

| 순서 | 항목 | 방법 |
|------|------|------|
| 1 | AI/rule 프로젝트 파일 확장자 | `python scripts/check_orientation_deps.py <project_id> [project_id2]` |
| 2 | EXIF 미적용 로그 | 서버 로그에서 아래 검색 |
| 3 | 916_vf 로그 | 서버 로그에서 아래 검색 |
| 4 | 의존성 | `python scripts/check_orientation_deps.py` (인자 없음) |

## 로그 검색 문자열 (확인 절차 2, 3)

- **EXIF 미적용**  
  서버(uvicorn) 로그에서 다음 메시지를 검색한다.  
  `EXIF orientation 미적용: path=... (reason: ...)`  
  - `reason`이 `pillow_heif 또는 piexif 미설치`이면 HEIC EXIF 미적용 원인.
  - 출력 위치: [engine/video_engine.py](engine/video_engine.py) `_probe_media()` 내부, `logger.info("EXIF orientation 미적용: ...")`.

- **916_vf (rotation / is_portrait)**  
  서버 로그에서 다음 메시지를 검색한다.  
  `916_vf: file=... raw_wh=(W,H) rotation=... -> logical_wh=(...) is_portrait=...`  
  - 세로 사진인데 `rotation=0`, `is_portrait=False`이면 EXIF 미반영 상태.
  - 출력 위치: [engine/video_engine.py](engine/video_engine.py) `_build_916_vf()` 내부.

## 의존성 설치

HEIC에서 EXIF를 읽으려면 `pillow-heif`, `piexif`가 필요하다.

```bash
pip3 install pillow-heif piexif
# 또는
python3 -m pip install -r requirements.txt
```

설치 후 `python scripts/check_orientation_deps.py`로 import 가능 여부 확인.
