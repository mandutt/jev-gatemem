# tigerless-labs/agent-memory 검토 (2026-10-10)

## 0. 요약 (TL;DR)

| 축 | 판정 |
|---|---|
| 백그라운드 Manage 레이어 (merge/supersede/split/delete 제안+reasoner 판정) | ⏸️ **보류 등록** — 우리 Honcho 보류(백그라운드 합성)의 **구체 구현체**. 우리 코퍼스 2,085행으로 시기상조 판단 유지하되, 구현 참고로 가치 |
| 읽기 횟수 기반 가중치 boost (access_log → weight) | ⏸️ **보류 등록** — 우리 recall_count 891/2,085(43%) 채움 실측 → 재검토 여지. 단 stage104 `_adjusted` 기각 축과 교차 |
| RRF k=60 · 시점 반개구간 · 파일 SoT · 검색 무LLM | ✅ **정합** — 외부 독립 구현 일치 (agentmemory·Honcho와 함께 표준성 지지) |
| 가치 기반 망각 (idle decay / weight floor 0.05) | ⏸️ 보류 — 우리 시간 축 유병률 실측(시간 참조 1.3%)과 충돌 여지, 발동률 낮아 후순위 |
| 삭제는 proposal로만 (pending 승인) | ✅ 실측 정합 — 우리 fail-open 원칙과 일치 |

**직접 이식 사항 없음. 코드 변경 없음.**

---

## 1. 대상

- 저장소: [tigerless-labs/agent-memory](https://github.com/tigerless-labs/agent-memory) (3.4k★)
- 설치: MCP 어댑터 (capture/transcript/hook_entry, Claude Code/Codex 공용)
- 스택: Python, SQLite(FTS5·vector_files 테이블), Markdown 파일 SoT
- 벤치: README 자체 보고 (LongMemEval R@5 96.6% raw/98.4% hybrid — **자체 보고+세션 단위 verbatim 전제, 우리 실측과 분리 표기**)

## 2. 주장

> "plain Markdown as the source of truth, local ranked retrieval, and an independent sleep-time Manage layer. No API key."

- Markdown 파일이 진실 (인덱스는 재구축 가능한 캐시, `rm -rf .index/ && mem rebuild` 검증)
- 검색은 로컬 (FTS5/BM25 + 벡터 RRF 융합), 읽기 경로 LLM 호출 없음
- **sleep-time Manage 레이어**: 수면 시 합병/대체/분할/삭제 제안 생성 → reasoner 판정 → 적용, 삭제는 승인 필요
- 가치 기반 망각 (읽기 횟수 boost + idle decay)

## 3. 소스 대조 (실측)

### 3.1 RRF 융합 (recall.py)

```python
RRF_K = 60
RRF_SOURCE_COUNT = 2
# score = Σ 1/(RRF_K + rank) / maximum, maximum = 2/(60+1)
```

- **우리 RRF k=60 (stage 내 `_rrf_score`)과 정확히 동일** ✅
- agentmemory(k=60)·Honcho(k=60)와 함께 후보 풀 표준성 지지

### 3.2 Manage 레이어 (manage.py, 752줄)

- 제안 종류: `PROPOSAL_MERGE` / `PROPOSAL_SUPERSEDE` / `PROPOSAL_SPLIT` / `PROPOSAL_DELETE` / abstract 재작성
- `_review`: reasoner가 JSON-Lines verdict(accept/reject) 반환 → `parse()` → accepted 수 caps 적용 → `decide()` → `_apply()`
- **caps**: `max_merges_per_sleep=3` · `max_supersedes_per_sleep=5` · `max_splits_per_sleep=2` · `max_deletes_per_sleep=3` · `max_boosts_per_sleep=3` (config.py ManageConfig)
- **삭제 적용 방식**: `_delete` → `store.delete()` → `marked <name> invalid` (실제 삭제가 아니라 invalid 표시, 기록 보존) — **우리 fail-open 원칙과 일치** ✅
- split/merge는 reasoner가 새 본문을 쓰고, 라이브러리는 시간·identity·evidence 계산 — "reasoner는 메뉴에서만 선택" 설계
- trigger: `trigger_min_hours=24` AND `trigger_min_sessions=3`

### 3.3 가치 기반 망각 (manage.py::_write 中)

```python
if self._idle_days(record, last_access, now) >= self._config.weight.decay_after_days:
    after -= self._config.weight.decay_step  # decay_step=0.1, after 30일 idle
# reads 기반 boost: max_boosts_per_sleep=3, boost_step=0.5
```

- weight: initial 1.0 · floor 0.05 · ceiling 5.0
- **읽기 횟수 = access_log 테이블에서 집계, 마지막 접근 시각으로 decay**

### 3.4 벡터 (vector_index.py)

- **brute-force cosine (전체 스캔), SQLite blob(f32 배열) 저장**
- 우리 sqlite-vec(vec0)와 같은 "작은 규모에선 전체 스캔" 접근 — **Vec1 추적 후보와 같은 자리** (tigerless도 ANN 미사용)
- `vector_enabled=False` 기본값 (벡터는 옵트인)

### 3.5 파일 SoT / record (record.py, memory_md.py)

- 1 memory 파일 = 1 validity interval (`valid_from`/`invalid_at`/`superseded_by`), old 파일은 history로 보존
- `MEMORY.md` = 루트 인덱스 (1줄/메모리), 8KB 예산, 120줄 캡, weight 정렬 → **우리 `_render` rows[:5] 노출과 유사한 '인덱스 한정 상주 주입'**

## 4. 우리 대비 축 비교

| 축 | tigerless | 우리 (jev-mem) | 판정 |
|---|---|---|---|
| 저장 | Markdown 파일 (인덱스는 캐시) | SQLite 단일 DB (ACID) | 우리 구조 우월 (트랜잭션·복구) |
| 쓰기 | 경계 증류 (배치, watermark, repair) | G-qual/G-AS 게이트 + 턴 단위 | 우리 게이트가 실측 검증됨 |
| 검색 | FTS5 BM25 + 벡터 RRF(k60) | FTS + vec + imp 3-lane RRF | **정합 (RRF k=60)** |
| Manage | sleep-time 제안+reasoner | supersede 113행·valid_until 159행 (write-time) | **우리 write-time이 우월** (sleep-time은 비동기 지연) |
| 망각 | idle decay+읽기 boost (weight) | valid_until 필터·τ=0.3·canary | ⏸️ 재검토 여지 |
| read-time 시점 | `as_of` 파라미터 | `valid_until > now` SQL 필터 | **정합 (반개구간)** |
| 삭제 | invalid 표시 (보존) | fail-open 원칙 (KEEP) | 정합 |

## 5. 0콜 실측 (DB 프로브)

```sql
-- working_memory 2,085행
recall_count > 0      : 891 (42.7%)   ← 읽기 횟수 축 채움 실측
recall_count 분포     : 상위 56·49·47… (메모리 반복 활용)
consolidated_at 채움  : 595
superseded_by 채움    : 113
valid_until 채움      : 159
pinned               : 0
```

- **우리도 recall_count를 수집하고 있다** (891/2,085 = 43%) — 다만 **검색 랭킹에 미사용** (stage104 `_adjusted` 기각 이후)
- tigerless의 읽기 boost 레버 = 우리 recall_count를 랭킹에 쓰는 **가장 간단한 구조** (access_log 대신 recall_count 컬럼 존재)

## 6. 판정

| 항목 | 판정 | 근거 |
|---|---|---|
| ① 백그라운드 Manage (merge/supersede 제안) | ⏸️ **보류 등록** | 우리 Honcho 보류(백그라운드 합성)와 동일 레버. 코퍼스 2,085행 시기상조 (OptMem/Honcho 보류와 동일 논리). 단 **구현 지침으로 가치**: reasoner 메뉴 제한·caps·invalid 표시 |
| ② 읽기 횟수 부스트 (recall_count 활용) | ⏸️ **보류 등록** | 우리 recall_count 43% 채움 실측 → '가장 간단한 랭킹 레버'로 재검토 여지. 단 stage104 `_adjusted`(기각) 축과 교차 → 별도 실험이라면 3-run 회귀 필요 |
| ③ RRF·시점 필터·삭제 보존 | ✅ 정합 | 외부 독립 구현 일치 |
| ④ idle decay (시간 축) | ⏸️ 보류 | 우리 시간 유병률 실측(상대시간 참조 1.3%·MemPalace 5/374)과 충돌 여지, 발동률 낮아 후순위 |
| ⑤ 벡터 전체 스캔 | ✅ 정합 | 우리와 같은 '작은 규모 = brute-force' 접근, Vec1 추적과 같은 자리 |

**직접 이식 사항 없음. 코드 변경 없음.**

## 7. 재현 경로

- 소스 미러: `reviews_tigerless/src/` (config.py·distill.py·vector_index.py·injection.py·schema.py·record.py·database.py·access_log.py·archive.py·ledger.py·manage.py·recall.py·reasoning.py)
- README 원문: `reviews_tigerless/survey-sources/tigerless-labs_agent-memory.md`, `tigerless-full.md`
- DB 프로브: §5 (라이브 mnemosyne.db, 0콜)

## 8. 결론

- **직접 반영 없음** — 우리 구조(write-time supersede·게이트·RRF)가 핵심 축에서 동일하거나 우월
- **보류 등록 2건**: ① 백그라운드 Manage 구현체 참고 (Honcho 보류와 병합) ② recall_count 활용 랭킹 (stage104 기각 축과 교차, 코퍼스 규모 시 재검토)
- 외부 벤치 수치(LongMemEval R@5)는 자체 보고+모델 고정 조건 — 실측과 분리 표기