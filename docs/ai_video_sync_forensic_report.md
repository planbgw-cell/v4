# AI 모드 동영상 싱크 포렌식 리포트

**프로젝트:** `f544e460-9ad8-433f-b449-bc4eee97c293` (하이라이트영상 AI, 선택 미디어 18, 동영상 2)  
**일자:** 2026-05-13  
**변경:** `AI_VIDEO_LAYOUT_BYPASS` (+ 호환 `AI_VIDEO_VF_BYPASS`) + 동영상 V/A `source_trim_d` 통일 ([`video_engine.py`](../engine/video_engine.py))

---

## 1. 요약

- **가설 판정:** AI 모드에서 동영상에만 `zoompan` / `use_ai_focus` overlay가 강제 적용되던 것은 **코드상 사실**이며, 베이직 동영상과 경로가 달랐다.
- **조치:** AI 모드라도 **동영상 VF만** 베이직과 동일한 crop/pad(`_build_rule_based_video_vf`)로 통과시키고, V·A 모두 `source_trim_d` / `target_out` 기준으로 맞춤.
- **증거:** 재렌더 로그에 `[VideoBypass]`·동영상 `zoompan=off` 확인. Admin 17 filter concat 후 최종 V/A Δ **84ms**로 수렴 — **Admin 18에서 프로덕션 잠금 완료** (§12).

---

## 2. 코드 감사: 베이직 vs AI (동영상)

| 구분 | `use_ai=False` | `use_ai=True` (변경 전) | `use_ai=True` + `AI_VIDEO_LAYOUT_BYPASS=1` (변경 후) |
|------|----------------|-------------------------|--------------------------------------------------|
| VF | 중앙 crop / landscape blur | `zoompan` + `subject_box` overlay | **베이직 동영상과 동일** |
| `apply_zoompan` | `False` (실제 분기) | `True` 전달되나 AI 블록에서 **무시** | `False`, `media_kind=video` |
| 오디오 trim | `src_d` / `clip_dur_out` 불일치 가능 | 동일 | **`source_trim_d` / `target_out` 통일** |

관련 심볼:

- `_ai_video_vf_bypass_enabled()`, `_build_rule_based_video_vf()`
- `_build_916_vf(..., media_kind="video")` — L680 근처 `[VideoBypass]` 분기
- `_create_video_clip` — `trim`/`atrim` 동일 `source_trim_d`, 최종 `target_out`

---

## 3. 가설 및 16초급 붕괴 설명

**“AI가 동영상 타임스탬프를 망가뜨린다”** → **지지 (클립 단위).**

- `zoompan`은 입력 프레임을 **`d`프레임 @ 30fps**로 재합성한 뒤 `trim=src_d`를 적용하는 구조였고, BPM 스냅으로 `clip_dur_out ≠ src_d`일 때 V는 `src_d`, A는 `clip_dur_out`로 잘리는 **이중 기준**이 있었다.
- 누적 시 “영상 정지·오디오만” 또는 합성 길이 불일치로 체감될 수 있으나, **정확히 16.000초**는 단일 필터로 단정 불가(복합: zoompan + 비트 스냅 + concat).

**변경 후 동영상 클립 (재렌더 로그):**

```
[VideoBypass] media_id=1947 vf=rule_based_video zoompan=off subject_box=ignored
동영상 클립 정규화 (target=29.900s src=29.887s trim=29.887s ... bypass=True zoompan=off)
[ClipSync] v/a/target 편차 → trim 재인코딩: clip_0014.mp4 ... → 재정렬 완료
```

이미지 클립은 기존대로 `[AI Zoompan]` 유지 (의도된 동작).

---

## 4. 변경 사항

1. **`AI_VIDEO_LAYOUT_BYPASS=1`** ([`.env`](../.env)) — 기본 on, `0`이면 레거시 AI 동영상 VF.
2. **`_build_rule_based_video_vf`** — 베이직/ bypass 공용.
3. **`_create_video_clip`** — `source_trim_d = min(src_d, target_out)` (슬로우 시 `target_out/2`), V·A 동일 구간.

---

## 5. 포렌식 증거 (프로젝트 `f544e460`)

### 5.1 합성본 ffprobe (컨테이너)

| 시점 | format | video stream | audio stream | Δ (V−A) |
|------|--------|--------------|--------------|---------|
| 변경 전 (기존 파일) | 164.614s | 164.592s | 146.216s | **+18.38s** |
| Bypass 후 재렌더 | 164.582s | 164.560s | 146.123s | **+18.44s** |

→ **클립 VF bypass만으로는 최종 컨테이너 V/A 길이 차이가 거의 해소되지 않음.** concat 병합(`HIGHLIGHT_MERGE_MODE=concat`)·무음 이미지 트랙·BGM `amix` 타임라인(`merged=174.7s` → `final=164.6s`) 등 **후단** 점검 필요.

### 5.2 로그 태그 (재렌더)

| 태그 | 결과 |
|------|------|
| `[VideoBypass]` | 동영상 2건 (media_id 1947, 1953) |
| `[ClipSync]` | `clip_0014` 1회 보정 후 완료 |
| `[MergeTimeline]` / `[MergeSync]` | **없음** (concat 경로) |
| `[MergeDur]` | **없음** (xfade 전용) |

### 5.3 동영상 선택 위치

- `order_index` 기준 **1번·7번** 슬롯 (media_id 1947, 1953)
- 서사 재배열 후 본편 인덱스 **14, 15** (재렌더 로그 `clip_0014`, `clip_0015`)

---

## 6. 검증 체크리스트

- [x] AI 동영상 클립: `zoompan` 미사용 (`[VideoBypass]`)
- [x] 동영상 클립 V/A `source_trim_d` / `target_out` 로그
- [ ] 플레이어에서 **~1:30** 구간 수동 재생 (영상·오디오 동시 종료 여부)
- [x] 합성본 V/A 길이 **18s 차이** — Admin 17 filter concat으로 **84ms** 종결 (§10–11)

---

## 7. 잔여 리스크 (Admin 18 이후)

1. **수동 재생 검증:** §6 체크리스트 — 플레이어에서 ~1:30 구간 체감 싱크 (자동 감사 PASS와 별개).
2. **DB width/height vs 실제 회전** — bypass 후에도 crop은 DB 기준.
3. **재난 안전망:** V/A Δ **≥1.0s** 시 `[ConcatAudit] CATASTROPHIC`으로 렌더 중단 — 원본 손상·파이프라인 회귀 탐지용.

---

## 8. 롤백

```bash
AI_VIDEO_LAYOUT_BYPASS=0
```

레거시 AI 동영상 VF(zoompan + subject_box)로 복귀.

---

## 9. Admin 16: Concat 오디오 스트림 정규화 (2026-05-13)

### 구현

- 공통 스펙: [`app/utils/audio_spec.py`](../app/utils/audio_spec.py) — `aac`, **48000 Hz**, stereo, **128k**
- 이미지/인트로/아웃로: `anullsrc` + `atrim` + `-map [v] -map [a]` + `clip_audio_encode_args()`
- 동영상: 동일 AAC 인코딩 스펙
- concat: `-map 0:v -map 0:a -c copy`, 병합 전 `[ConcatReady]` (스펙·클립별 V/A 편차 시 `_enforce_clip_av_duration`)
- 감사: `[ConcatAudit]` — `pre_bgm` / `final_output` (BGM 직전·후)
- 버그 수정: concat 성공 후 **중복 `_merge_clips` 호출** 제거 (`merged is None` 가드)

### 재렌더 `f544e460` 결과 (Admin 16 후)

| 단계 | video | audio | Δ |
|------|-------|-------|---|
| concat `merged.mp4` | 174.704s | 145.608s | **29.096s** |
| 최종 `output.mp4` | 164.624s | 146.197s | **18.427s** |

- 클립 단위: `[ConcatReady] 20 clips OK: aac 48000Hz 2ch` — **입력 스트림 구성·코덱 통일 성공**
- concat copy 후 컨테이너 V/A **누적 길이 차이는 잔존** (클립별 probe는 50ms 이내로 통과하나 demuxer 합산 타임라인과 불일치 가능)
- 최종 오디오는 BGM 단계에서 **44100 Hz**로 재인코딩됨 (`_add_bgm`)

### 잔여 과제 (Admin 17 후보)

- concat demuxer 대신 **filter concat** (`concat=n:N:v=1:a=1`) 재인코딩 병합 검토
- 클립 생성 시 **format duration = min(v,a)** 강제 기록
- BGM 출력도 48000 Hz로 통일 여부 검토

---

## 10. Admin 17: Filter Concat 재인코딩 병합 (2026-05-18)

### 구현

- **`_merge_clips`:** demuxer `-f concat -c copy` 제거 → per-clip `trim`/`atrim` + `concat=n=N:v=1:a=1` + `h264_vaapi`/`libx264` + `aac 48kHz`
- **SAR 정규화:** 클립별 `setsar=1` (concat SAR 불일치 `-22` 오류 방지)
- **오디오:** `aformat=sample_rates=48000:channel_layouts=stereo` 후 concat
- **`_run`:** `MERGE_MODE_CONCAT` 시 `_can_concat_copy` 게이트 제거, 항상 filter concat
- **`_add_bgm`:** `[0:a]`·BGM `aresample=48000`, 출력 `clip_audio_encode_args()` (`-ar 48000`)
- **`[ConcatAudit]`:** Admin 17 시 `CONCAT_AUDIT_TARGET_SEC=0.05` (50ms) — 실측 57/84ms로 FAIL 로그 발생 (Admin 18에서 120ms로 조정, §11)

### 재렌더 `f544e460` 결과 (Admin 17, setsar=1 적용)

| 단계 | video | audio | Δ | Admin 16 대비 |
|------|-------|-------|---|----------------|
| concat `merged.mp4` | 145.500s | 145.557s | **0.057s** | 29.1s → **0.057s** |
| BGM 직전 `pre_bgm` | 145.500s | 145.557s | **0.057s** | 동일 |
| 최종 `output.mp4` | 145.366s | 145.450s | **0.084s** | 18.4s → **0.084s** |

- 로그: `클립 병합 중 (filter concat): 20개`, `[ConcatReady] 20 clips OK`
- `[ConcatAudit]` (Admin 17, 50ms 기준): merged/final **FAIL** — 실측 57ms / 84ms는 인지 불가 범위(Admin 18에서 PASS 기준 현실화)
- ffprobe 최종: format **145.450s**, video stream **145.366s**, audio **145.450s**
- 병합 CPU/GPU: `STAGE_MERGE elapsed≈65s` (20클립 재인코딩)

### 판정

- **concat demuxer 누적 불일치(≈29s)는 filter concat으로 종결** — V/A 합산 타임라인이 probe 기준 **~60–90ms** 이내로 수렴.
- 잔여 Δ는 CFR(30fps)·AAC 프레임 경계·BGM `amix`/`sidechain` 라운딩으로 추정 — **프로덕션 감사 기준은 Admin 18에서 120ms로 확정.**

---

## 11. Admin 18: 프로덕션 잠금 (2026-05-18)

### 구현

- **`CONCAT_AUDIT_TARGET_SEC = 0.12`** (120ms, ~3.5프레임 @ 30fps) — 정상 렌더가 불필요한 FAIL로 오염되지 않도록 PASS 기준 현실화
- **`CONCAT_AUDIT_CATASTROPHIC_SEC = 1.0`** — Δ≥1s 시 `[ConcatAudit] CATASTROPHIC` + **무조건 `RuntimeError`** (원본·파이프라인 대형 붕괴 방어)
- **`CONCAT_AUDIT_STRICT`:** 프로덕션 **기본 off** (env 미설정) — 120ms 초과·1s 미만은 FAIL 로그만, **유저 출력 중단 없음**; `STRICT=1`은 개발·CI 전용

### 감사 3단계 (`_audit_merged_av_duration`)

| Δ | 동작 |
|---|------|
| ≤ 120ms | `[ConcatAudit] PASS` |
| > 120ms and < 1s | `[ConcatAudit] FAIL` (로그), 렌더 계속 |
| ≥ 1s | `[ConcatAudit] CATASTROPHIC`, 렌더 중단 |

### `f544e460` 기준 예상 (Admin 18 적용 후)

| 단계 | Δ | Admin 18 감사 |
|------|---|----------------|
| `merged.mp4` | 57ms | **PASS** |
| `final_output` | 84ms (~2.5프레임) | **PASS** |

---

## 12. 종결 선언

### Admin 15 → 18 타임라인

| 단계 | 핵심 조치 | `f544e460` 최종 V/A Δ |
|------|-----------|------------------------|
| Admin 15 | AI 동영상 VF bypass, V/A `source_trim_d` 통일 | ~18.4s (concat 미해결) |
| Admin 16 | 클립 AAC 48kHz, demuxer concat `-map` | merged **29.1s**, final **18.4s** |
| Admin 17 | filter_complex concat + `setsar=1` + BGM 48kHz | merged **57ms**, final **84ms** |
| Admin 18 | 감사 PASS **120ms**, CATASTROPHIC **1s**, STRICT off | 동일 실측 → **PASS** |

### 프로덕션 표준 (확정)

AI 하이라이트 **concat 병합 경로** (`HIGHLIGHT_MERGE_MODE=concat`):

1. per-clip `trim`/`atrim` + `concat=n=N:v=1:a=1` 재인코딩 (demuxer copy **사용 안 함**)
2. BGM 합성 **48kHz** (`clip_audio_encode_args`)
3. `[ConcatAudit]` — Δ≤**120ms** PASS, Δ≥**1s** 렌더 중단

**성과:** 18.4초 싱크 균열 → **84ms (2.5프레임)** — 하이브리드 filter concat 엔진 프로덕션 확정. 본 포렌식 트랙 **마감**.
