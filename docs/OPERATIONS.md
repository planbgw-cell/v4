# Flairy v4 운영 및 부하 점검

## 동시 렌더링 부하 테스트 (Stress)

목표: 여러 사용자가 동시에 AI 하이라이트를 생성할 때 서버가 안정적으로 동작하는지 확인합니다.

### 준비

- 서로 다른 프로젝트 ID가 최소 4개 필요합니다(각각 업로드·미디어 READY 완료 상태 권장).
- 관리자 또는 세션 쿠키가 있는 클라이언트에서 `POST /api/projects/{project_id}/generate` 호출.

### 빠른 재현 (예시 스크립트)

프로젝트 UUID와 인증이 필요하면 스크립트를 수정해 사용합니다.

```bash
./scripts/stress_generate.sh https://your-host:8000 "$(cat cookie.txt)"
```

### 관측 명령

터미널 1:

```bash
journalctl -u flairy_v4.service -f
```

확인할 로그 키워드:

- `GPU_SLOT_ACQUIRED` / `GPU_SLOT_RELEASED`
- `GPU_SLOT_UNAVAILABLE` → CPU 폴백 또는 대기
- `FALLBACK_CPU`
- `ACCEL_TYPE: VAAPI`

터미널 2:

```bash
watch -n2 'df -h /dev/shm; echo; free -h'
```

렌더 종료 후 FFmpeg 잔류 확인:

```bash
pgrep -afc ffmpeg || true
```

### 기대 동작

- `FLAIRY_GPU_MAX_SESSIONS`(예: 3)에 맞춰 동시 GPU 슬롯이 제한된다.
- `/dev/shm`(임시 디렉터리로 사용 시) 여유가 바닥나지 않는다.
- 장시간 남는 `ffmpeg` 프로세스(좀비)가 없다.

---

## 코드 배포 후 재시작 (필수)

Python 모듈(`video_engine` 등)은 **gunicorn 워커 재시작 전까지 메모리에 구버전이 남습니다.** `git pull`만으로는 렌더 파이프라인이 갱신되지 않을 수 있습니다.

```bash
./scripts/deploy_restart.sh
# 또는: git pull && sudo systemctl restart flairy_v4.service
```

배포 후 로그에서 `filter concat 병합 중`, `[ConcatAudit] PASS` 문구로 Admin 17+ 병합 경로 적용 여부를 확인하세요.

---

운영 환경변수 요약은 루트 [README.md](../README.md)의 **운영·성능 튜닝** 절을 참고하세요.
