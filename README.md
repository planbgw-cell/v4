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
