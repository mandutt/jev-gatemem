# 백필 실행 보고: 2026-10-09 11:47 ~ 10-10 18:00 갭 구간

- 작성: 2026-10-11 (재주입 완료 후)
- 실행자: Hermes (게이트웨이 세션)
- 상태: ✅ 완료 — 375건 저장, 벡터 100% 보유, prefetch 회수 검증 통과
- 관련 스킬: `jev-memory-middleware` (reference: `references/plugin-verification.md` §backfill)

---

## 1. 배경 — 갭 발생

사용자: "어제부터 오늘까지 jev-mem 데몬이 꺼져서 세션 채팅을 메모리에 기록하지 못한 시간대가 있어.

그 시간대의 세션 채팅기록을 다시 읽어서 메모리에 주입할 수 있을까?"

**갭 확정 (0콜 진단, trace + DB 대조)**

| 항목 | 값 |
|---|---|
| 마지막 write-gate (10-09) | `jev_trace_20261009.log` 마지막 라인 `2026-10-09T11:47` |
| 첫 write-gate (10-10) | `jev_trace_20261010.log` 첫 라인 `2026-10-10T18:33` |
| trace pool/gate 이벤트 공백 | `2026-10-10T01:04 ~ 17:59` (데몬 다운 구간) |
| 갭 구간 | **2026-10-09 11:47 ~ 10-10 18:00 KST (약 30h)** |
| 영향을 받은 세션 | 16개 (대화 세션 15 + cron 1) |

상세: trace 시간대별 분포는 `experiments/operational-golden/data/backfill_20261011/*.md` 표 참조.

원인(기록상): 게이트웨이가 Hermes tools python으로 기동되는 회귀로 `mnemosyne_hermes`
부재 → provider 로드 실패 → 데몬 자동기동 기회 상실 (2026-10-10 재부팅 사고 보고의 재발;
`docs/ops/` 및 SKILL.md의 ★python 환경 불일치 항목 참조).

---

## 2. 실행 과정 (실측 로그)

### 2.1 준비

- 백업 2건 생성 (전 과정의 마지막 보루):
  - `AppData/Local/hermes/mnemosyne/data/mnemosyne.db.backup-before-backfill` (38,576,128 B)
  - `AppData/Local/hermes/state.db.backup-before-backfill` (593,993,728 B)
- 정본 스크립트: `experiments/operational-golden/backfill_session_memories.py`
  - 커밋 `3bc26c1`: venv 하드코딩 2곳을 제거하고 Hermes installs glob 탐색 폴백으로 교체.
    (기존 `hermes-agent/venv` 경로는 10-10 실측으로 존재하지 않음)

### 2.2 1차 실행 — 실패 (281행 벡터 누락)

- 실행 python: **Hermes venv** `installs/315db7b763fb0d0a/environments/099e00aba7aa4e9494cf6ab86490e67a/venv`
- 증상: `remember: embedding storage failed for '<id>' (RuntimeError): Failed to load embedding
  model hotchpotch/bekko-embedding-v1-a8m: Model ... is not supported in TextEmbedding.`
  → 행은 저장되지만 벡터(memory_embeddings/vec_working)가 **0건**
- 1차 완료: 281행 저장 (dry-run 세션 + 2건 검증 세션 포함; 1개 세션은 dry-run만)

### 2.3 원인 규명 (0콜 ↔ 1콜)

| 확인 | 결과 |
|---|---|
| Hermes venv(099e00a) fastembed | bekko 미지원 (37개 모델, `list_supported_models()`에 없음) |
| jev-mem 데몬 venv fastembed | bekko 지원 (`bench/bekko-a8m`, 38개) |
| 운영 게이트웨이 venv | `installs/.../099e00a` (문서상 동일) |
| 그러나 **라이브 저장 임베딩은 정상**(`memory_embeddings.model='bench/bekko-a8m'`, 2,151건) | |
| **핵심** | 운영 저장은 **데몬(RPC, port 47821)이 수행** — 데몬 venv
  (`%LOCALAPPDATA%/jev-mem/venv`, sitecustomize가 `bench/bekko-a8m` 등록 + 캐시 강제)라서 정상 |
| 데몬 로그 | `core.out.log`에 `gateway.j1_pipeline: Jev choice ...` — 파이프라인이 데몬 프로세스에서 실행됨을 실측 |
| 데몬 venv의 mnemosyne `_default_db_path()` | `C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db` (Hermes 실 DB) |

**결론**: 저장(임베딩 포함)은 반드시 데몬 venv(`%LOCALAPPDATA%/jev-mem/venv`)에서 수행해야 한다.
Hermes venv의 fastembed는 bekko 커스텀 등록이 없어 `_get_model()`이 실패하고,
`_store_working_embedding` 호출부가 예외를 삼켜 "행 저장은 성공 + 벡터만 누락"의 반쪽 저장이 된다.

벡터 누락의 실질 영향: `_wm_vec_search`는 `memory_embeddings` 폴백을 쓰므로 vec lane 자체는
동작하나, Hermes venv로 재백필하면 fallback 0건 → vec lane 0건 → pool 구성이 반쪽.

### 2.4 1차 실행 롤백

- 삭제 대상: `metadata_json`의 `backfilled_at`이 `2026-10-11%` 이면서
  `memory_embeddings`에 없는 행 = 281건 전부
- 이전 백필(2026-10-05, 31건)은 `backfilled_at`이 10-05라 보존 확인
- 삭제: `DELETE FROM working_memory WHERE id IN (...)` (with 벡터 테이블 정리) — 총 1,402 변경

### 2.5 2차 실행 — 성공 (375건)

- 실행 python: **데몬 venv** `%LOCALAPPDATA%/jev-mem/venv/Scripts/python.exe`
- 시작부 자기 검증: `fastembed.TextEmbedding.list_supported_models()`에 `bekko` 포함 확인 후 진행
- 재주입 절차: `backfill_session_memories.py`와 동일 — 실 JEV 게이트
  (`write_gate.evaluate`/`evaluate_assistant`)로 KEEP만 저장, 임베딩은 `BeamMemory.remember` 경유

| 세션 | KEEP/저장 |
|---|---|
| 20261008_124838_4e6768 | 28 |
| 20261009_121159_a1889f86 | 89 |
| 20261009_170102_23af68 | 77 |
| 20261009_202405_a3547d | 14 |
| 20261009_204758_9c4effac | 6 |
| 20261009_210137_5c8cd152 | 3 |
| 20261009_213132_71a5b708 | 4 |
| 20261009_215051_ab0ffc99 | 43 |
| 20261010_000744_6cc8edd4 | 2 |
| 20261010_001402_e6a182c5 | 2 |
| 20261010_002027_a9264deb | 2 |
| 20261010_002807_ed5c5339 | 28 |
| 20261010_112326_8e4f2320 | 8 |
| 20261010_143419_985ebd | 63 |
| 20261010_211831_9a13e3 | 6 |
| cron_1f064a795460_20261009_093030 | 0 (assistant 1건 SKIP) |
| **합계** | **375** (user 187 / assistant 188, turn-final 규칙) |

---

## 3. 검증 결과

### 3.1 벡터 커버리지 (0콜)

```
오늘 재백필 행: 375
memory_embeddings 벡터 보유: 375 / 375
모델 태그: ['bench/bekko-a8m']          ← 운영과 동일 모델
전체 working_memory 2508 / 벡터 보유 2527 (100%)
```

### 3.2 prefetch 회수 (실 JEV 호출, 5쿼리)

| 쿼리 | 회수 |
|---|---|
| granite 임베딩 모델 검토한 적 있어? | ✅ `[2026-10-11T01:02] [ASSISTANT] granite 임베딩 모델은 실측 결과 전 변형이 모두 실패...` (1위) |
| agentmemory 프로젝트 분석 결과 | ✅ `[2026-10-11T01:06] agentmemory (rohitg00) 검토 결과...` |
| RX580 GPU 경로 램 점유 양자화 대안 | ✅ `llama.cpp의 ModernBERT 지원 상태와 로컬 GPU 경로... GPU + 양자` |
| sift 저장소 반영 사항 | 상위 5 노출에 재백필 행 없음 (중복/도배 행에 밀림 — 검색 동작 정상 범위) |
| hippo-memory와 jev-mem 비교 | 상위 5 노출에 재백필 행 없음 (동일) |

검증 도구: `data/backfill_20261011/backfill_recall_check2.py` (데몬 RPC `/v1/prefetch`, port 47821)

---

## 4. 산출물

| 항목 | 경로 |
|---|---|
| 정본 스크립트 | `experiments/operational-golden/backfill_session_memories.py` (커밋 3bc26c1, push 완료) |
| 2차 실행 로그 | `data/backfill_20261011/backfill_rerun_daemon.log` |
| 검증 스크립트·출력 | `data/backfill_20261011/backfill_verify3.py` / `backfill_recall_check2.py` |
| 1차 실패 로그 | `%TMPDIR%/backfill_gap_run.log` (스크래치) — 증상 재현용 |
| 백업 | `mnemosyne.db.backup-before-backfill` / `state.db.backup-before-backfill` (Hermes data dir) |
| 이 문서 | `docs/ops/2026-10-11_backfill-30h-gap-report.md` |
| 스킬 | `jev-memory-middleware` SKILL.md (실행 venv 선택 교훈) + reference `plugin-verification.md` §backfill |

---

## 5. 재발 방지 체크리스트

1. **백필 실행 전 python 선택 확인**
   `%LOCALAPPDATA%/jev-mem/venv/Scripts/python.exe -c "from fastembed import TextEmbedding; print(any('bekko' in m['model'] for m in TextEmbedding.list_supported_models()))"`
   → `True`일 때만 실행 (Hermes installs venv는 False — 사용 금지)
2. **백필 후 벡터 검증**
   `SELECT COUNT(*) FROM working_memory WHERE metadata_json LIKE '%backfill:2026101%'` 와
   `SELECT COUNT(DISTINCT memory_id) FROM memory_embeddings` 교차 — 100% 보유 확인
3. **갭 탐지**: trace `write-gate` 라인 첫/마지막 타임스탬프 대조 (일별 로테이션 `jev_trace_YYYYMMDD.log`)
4. **재발 원인(게이트웨이 python 회귀)**: 재부팅/업데이트 후 `Hermes_Gateway.cmd`의 python 경로 확인
   (tools python이면 `mnemosyne_hermes` 부재 → provider 로드 실패)