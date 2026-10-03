# failopen archived(재판정 skip) 행 recall 누출 — 원인·수정·검증 완료 (2026-10-03, f5aa4ef)

## 한 줄 요약

재판정으로 skip 처리된(archived) 기억 24건이 **live recall 경로에서 실제로 제외되지 않고 있었다** — 2중 결함(A: 컬럼 누락, B: lane 필터 부재)이 겹친 상태였고, 둘 다 수정 + 백필 + 라이브 E2E 검증 완료.

## 발견 경위

P3a 완료 후 sync-path 점검 중 발견:
- P3 자동 재판정이 마지막으로 처리한 `feaf9c350d32f613`(skip)이 /v1/prefetch 결과에 계속 나타남
- 추적 결과 두 개의 결함이 겹쳐 있었음

## 결함 A — skip 승격 시 `valid_until` 컬럼 미기록

**recall 제외 필터(beam.py)는 metadata가 아니라 컬럼을 본다:**

```sql
-- beam.py: `valid_until IS NULL OR valid_until > ?`
wm.superseded_by IS NULL AND (wm.valid_until IS NULL OR wm.valid_until > ?)
```

- P3 `jev_mem_core/recover.py` `_apply_verdict`와 `tools/jed_failopen_rejudge_v2.py`(v2 CLI 경로)가 skip 시 `metadata.valid_until`만 갱신 → **컬럼은 NULL 유지** → 이 행들은 recall에서 전혀 걸러지지 않음
- P1 apply(`jed_failopen_p1_apply.py`)와 403 apply는 처음부터 컬럼을 기록했음 — **P3 경로만 누락** (신규 writer 검증 시 '컬럼까지 반영되는가'가 필수 체크 항목이라는 교훈)

**수정:**
- `recover.py._apply_verdict` / `rejudge_v2._apply_verdict`: `UPDATE working_memory SET metadata_json=?, valid_until=?` — skip 분기에서 컬럼 동시 기록
- 기존 24건 백필: `datetime.now().isoformat(timespec="seconds")` 형식으로 컬럼 채움 (0건 NULL 확인)

## 결함 B — FTS/imp/graph lane + hydration에 temporal 필터 부재

컬럼을 채운 뒤에도 archived 행이 pool에 남는 현상 재확인. 코드 추적 결과:

| 레인/경로 | temporal 필터 | 비고 |
|---|---|---|
| vec lane (`_wm_vec_search`) | ✅ 있음 | 기본 `where_sql`에 `superseded_by IS NULL AND (valid_until IS NULL OR valid_until > ?)` |
| FTS lane (`_fts_search_working`) | ❌ 없음 | mnemosyne 코어 — 수정 불가 |
| imp lane (`j1_pipeline._imp_search`) | ❌ 없음 | middleware 소유 |
| graph lane (`j1_pipeline._graph_lane_search`) | ❌ 없음 | middleware 소유 |
| hydration (`j1_engine.hydration_get`, `get_hydrated`) | ❌ 없음 | pool의 **단일 choke point** |

실측(baseline): `'좋아 진행해줘'` pool 81→아카이브 3건 포함, `'이어서…'` pool 123→아카이브 1건 포함.

**수정 (choke point 우선):**
1. `core/j1_engine.hydration_get` — hydration이 pool의 모든 행을 경유하므로 여기서 `superseded_by IS NULL AND (valid_until IS NULL OR valid_until > ?)` 강제 (데몬 + embedded 공용 경로)
2. `backends/mnemosyne.get_hydrated` — backend 경로 동일 강제 (gateway.py `_retrieve_j1` 경유)
3. `gateway/j1_pipeline._imp_search` / `_graph_lane_search` — defense in depth

함정: `valid_until` 비교는 **문자열 비교** — `datetime.now().isoformat()`(마이크로초 포함) 형식 유지 필수. `timespec="seconds"`나 `Z` 접미사 혼용 시 문자열 순서가 어긋나 조용히 새는 회귀가 발생할 수 있다.

## 검증

### 회귀 테스트 (신규): `tools/jed_failopen_archived_recall_regress.py`

live DB read-only, JEV 호출 0회. 4개 축 8체크:
1. 아카이브 24건 전부 `hydration_get()` → None (배제)
2. FTS raw lane 누출 벡터 확인 → hydration 후 0
3. `build_lane_pool` probe 2종 archived 0
4. positive control: 비아카이브 hydration 5/5 성공, imp/vec lane 반환 정상

**수정 전: FAIL 4건(아카이브 24/24 누출) → 수정 후: 8/8 전부 통과.**

### 과잉 필터 검증

필터로 pool에서 빠진 6건의 원인 전수 확인: superseded 5 + 재판정 skip 1 — **전부 정당한 제외**, 정상 행 손실 0.

### 라이브 E2E (데몬 재기동 후)

데몬을 새 코드로 재기동(HKCU 키 인라인 spawn, 트리 30512→11600→22492) 후 `/v1/prefetch` 실호출:

| 쿼리 | pool | archived in pool | archived in final | JEV |
|---|---|---|---|---|
| '정지된 것 같은데, 이어서 해줄 수 있어?' | 56 | **0** | **0** | 200 OK, idx=8 |
| '좋아 진행해줘' | 49 | **0** | **0** | 200 OK, idx=0 |

- daemon 로그 `Jev choice: idx=8 latency=291ms pool=56` / `idx=0 latency=257ms pool=49` = JEV 실호출 정상
- `rejudge batch: claimed=0` = P3 워커 정상
- Error/InvalidStateError 0건

### 기존 스위트 회귀

- `jed_failopen_p3a_verify.py` 20/20 ✅
- `jed_failopen_p3a_syncpath_verify.py` 7/7 ✅
- DB sanity: fail_open 잔여 0, skip 24건 전부 valid_until 컬럼 기록(0 NULL), incidents 전부 closed

## 검증 함정 (재현 시 주의)

1. **`core.out.log` vs `core.log`**: 구 데몬 종료 후 `core.out.log`의 mtime이 멈춰 '데몬 정지'로 오진 — 현행 로그는 `logs/core.log`. 로그가 정지한 것처럼 보이면 파일을 확인하라.
2. **curl `--data-binary @`에 Windows 절대경로**: MSYS 경로(`$TMPDIR/...`)는 네이티브 curl이 못 읽는다(`error encountered when reading a file`). `C:/Users/...` 형식으로.
3. **E2E 최강 증거는 `options.pool_ids=true`**: `meta.pool_ids`/`meta.final_ids`에 archived id 0건 확인 (데몬 재기동 후 실호출).

## 변경 파일

| 파일 | 변경 |
|---|---|
| `jev_mem_core/recover.py` | skip 시 valid_until 컬럼 기록 |
| `tools/jed_failopen_rejudge_v2.py` | 동일 |
| `core/j1_engine.py` | hydration_get에 temporal 필터 |
| `backends/mnemosyne.py` | get_hydrated에 temporal 필터 |
| `gateway/j1_pipeline.py` | _imp_search·_graph_lane_search 필터 + datetime import |
| `tools/jed_failopen_archived_recall_regress.py` | 신규 회귀 테스트 |
| `tools/stop_jev_daemon.ps1` | pythonw 이름 가드(직전 커밋 미포함분) |
| `jev_mem_core/server.py` | skip_staged 2포맷 집계 + open_incidents DB SoT(직전 미포함분) |

커밋: `f5aa4ef` — `fix(failopen): archived(skip) rows leaked into live recall — column write + lane filters`

## 남은 것 (미결)

- rejudged 마커 포맷 2종(`rejudged:skip` 태그형 vs `"rejudged": "skip"` JSON형) — 신규 기록부 단일 포맷 통일 미실시 (카운트 쿼리는 2포맷 모두 검사하도록 수정됨)
- `_cjk_like_search`(mnemosyne 코어 FTS 폴백) 경유 행은 hydration 필터로 최종 배제되지만, 코어 수정 없이는 raw 단계 배제 불가 — 현 구조로 충분(검증됨)
