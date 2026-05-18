# Flairy v4.0

AI 기반 하이라이트 영상 생성 엔진.

## 주요 기능

- **AI 기반 이미지 분석** — Gemini를 활용한 감정·요약·영문 자막 생성
- **9:16 시네마틱 렌더링** — FHD 세로 포맷, Ken Burns·블러·EXIF 보정
- **스마트 콜라주** — score 상위 이미지로 인트로 콜라주 자동 구성
- **타이프라이터 영문 자막** — ASS 단일 필터, 하단 15% 배치
- **지능형 BGM 매칭** — 감정 기반 BGM 선정 및 더킹

## 실행 방법

```bash
pip install -r requirements.txt
```

`.env` 파일을 프로젝트 루트에 두고 다음 변수를 설정한다.

- `DATABASE_URL` — PostgreSQL 연결 문자열 (예: `postgresql://user:pass@localhost:5432/flairy_v4`)
- `GEMINI_API_KEY` — Google Gemini API 키 (AI 분석·자막용)

```bash
uvicorn app.main:app --reload --port 8000
```

## 운영·성능 튜닝

프로덕션에서는 보통 **Gunicorn + systemd**(예: `flairy_v4.service`)로 실행합니다. 워커 수·타임아웃은 유닛 파일의 `--workers`, `--timeout` 등으로 조정합니다.

동시 부하 점검 절차·관측 명령은 [docs/OPERATIONS.md](docs/OPERATIONS.md)를 참고하세요.

아래는 애플리케이션이 읽는 환경 변수 예시입니다(실제 값은 배포 환경의 `.env`를 따르며, 비밀값은 문서에 넣지 마세요).

| 변수 | 설명 | 예시 |
|------|------|------|
| `VIDEO_ACCEL_TYPE` | FFmpeg 하드웨어 가속 모드 | `auto`, `vaapi`, `none` |
| `HIGHLIGHT_MERGE_MODE` | 하이라이트 구간 병합 방식 | `xfade` |
| `FLAIRY_GPU_MAX_SESSIONS` | GPU 동시 세션 상한 | `3` |
| `FLAIRY_GPU_SEMAPHORE_TIMEOUT_SEC` | GPU 슬롯 대기 초(초과 시 CPU 폴백 등) | `2` |
| `FLAIRY_TEMP_DIR` | 임시 파일 경로(미설정 시 기본 경로) | `/dev/shm/flairy` |
| `VIDEO_RENDER_MAX_WORKERS` | 렌더 관련 워커 상한 | `4` |
