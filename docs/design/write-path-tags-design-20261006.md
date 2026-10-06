# A Q5 설계안: Write-path 태그 보강 (상위 맥락 태그)

- 상태: **설계 초안 (2026-10-06)** — 승인 대기
- 배경: stage46 support_set 재감사 결과 **retrieval miss 10건** 확정
  (gold는 직접 답·코퍼스 존재·pool 60 미진입). rerank가 아니라 lane 검색 문제.
- 예시: "전환 전 어떤 문제 있었지?" ↔ gold "supermemory 0-byte 유실(전환 사유)" —
  어휘 중첩 0 (FTS 미검출), 임베딩도 "전환"⇄"supermemory" 의미 링크 생성 실패.

## 1. 문제 정의

| miss 사례 | 쿼리 키워드 | gold의 실질 주제 | 실패 lane |
|---|---|---|---|
| [11] 전환 전 문제 (dependent) | 전환 | supermemory→mnemosyne 마이그레이션 | FTS 0, vec 낮음 |
| [4] 구현 확인 규칙 | 구현/확인 | evidence-based 원칙 (사용자 지침) | FTS 0 (영문 gold) |
| [5] evidence 규칙 | evidence | Evidence-based only (영문) | FTS 0 (한글 쿼리) |
| [9] Exa 안 씀 | Exa | tavily 채택, Exa mojibake | vec 낮음 (사유 질문) |
| [10] 18080 프록시 | 18080/프록시 | camelai-serial-proxy | FTS는 잡았을 것 — 60컷 밖? |

**근본 원인**: 메모리 내용(본문)은 정확하지만 **"상위 맥락"(전환, 마이그레이션, 채택 사유,
결정 배경)이 FTS 인덱스에 없음**. 쿼리는 맥락으로 접근하지만 저장은 본문으로만 되어
어휘·의미 다리가 없음.

## 2. 설계: 저장 시 "주변 대화 맥락"을 태그로 부착 (write-path)

### 2.1 원칙

1. **JEV/G-qual 게이트 통과 시점에만** 부착 (일반 LLM 금지 원칙 — 부가 호출 없음)
2. **0콜/0원**: 직전 사용자 발화·직전 assistant 응답 요약은 **이미 메모리에 존재**
   (같은 턴의 user·asst 발화가 방금 저장됨) — 이를 재사용
3. **내용 무변경**: content는 그대로, `metadata_json`에 태그만 추가
4. **후방 호환**: 기존 FTS 테이블 구조 불변 — FTS 인덱스는 content 기반이므로
   태그는 **별도 검색 보조**로 동작 (아래 2.3)

### 2.2 부착 내용 (`metadata_json.tags`)

저장 턴의 **직전 N턴(≤3)의 사용자 발화에서 추출한 명사성 키워드**:

```
tags: ["전환", "supermemory", "마이그레이션", "메모리", "설치"]
```

- 추출 규칙: 기존 `_tokenize`(한글 2자+ 블록, 영문 3자+) 재사용,
  **불용어(stopwords) 제거 후 빈도 상위 5개**
- 직전 턴(같은 세션)의 user 발화에서만 (assistant 발화 제외 — 태그 오염 방지)
- 최신 턴부터 역순 누적, 총 ≤10개

### 2.3 검색 연동 (lane 보조)

**FTS 확장 없이** SQLite `LIKE` 보조 lane으로 추가:

```
tags_lane (신규, LANE_TAGS_BUDGET=10):
  SELECT id FROM working_memory
  WHERE metadata_json LIKE '%"tags":%' AND (
    metadata_json LIKE '%<tag1>%' OR ... OR '%<tag5>%')
  ORDER BY rowid DESC LIMIT 10
```

- 조회 시에도 쿼리에서 같은 키워드 추출 (기존 `_query_tokens`)
- build_lane_pool의 **6번째 lane**으로 추가 (FTS/vec/imp/graph + tags)
- RRF merge에 포함 — gold가 tags lane으로 pool 60 안에 진입 가능
- **비용**: LIKE 스캔은 SQLite에서 수백 ms 수준 (1,700행) — `_imp_search`와 동급.
  메모리 10만 행까지는 무시 가능; 그 이상이면 FTS5 별도 인덱스로 승격 (후속 과제)

### 2.4 토큰/비용 영향

| 항목 | 영향 |
|---|---|
| JEV 콜 | **0** (게이트 기존 응답 재사용) |
| 저장 지연 | +1ms 미만 (키워드 추출 로컬) |
| DB 크기 | metadata_json에 tags 배열 (행당 ~100바이트) |
| 검색 지연 | +수십 ms (LIKE 보조 lane) |

## 3. 예상 효과 (0콜 검증 가능)

- stage46의 10건에 대해 **쿼리 키워드 ↔ gold의 직전 턴 발화 키워드** 교집합을
  스냅샷에서 계산 → tags lane이 몇 건을 pool로 복구하는지 **0콜 사전 검증**
  (검증 후 구현 — 실측 우선 원칙)

## 4. 구현 범위 (승인 후)

| 파일 | 변경 |
|---|---|
| `jev_mem_core/store.py` | `_remember_with_meta`에 `context_tags` 파라미터 + `tags` 메타 추가 |
| `jev_mem_core/pipeline.py` | 저장 시 직전 턴 user 발화에서 키워드 추출 → store에 전달 |
| `gateway/j1_pipeline.py` | `_tags_lane_search()` + build_lane_pool 6번째 lane |
| 문서 | HANDOFF + 실측 문서 갱신 |

## 5. 리스크

| 리스크 | 대응 |
|---|---|
| 태그 오염 (무관 키워드) | 직전 3턴·user 발화 한정 + 빈도 상위 5개 + 태그는 lane 보조일 뿐 JEV가 최종 판단 |
| LIKE 스캔 성능 | 예비: 10만 행에서 FTS5 별도 컬럼 승격 (설계 동일, 인덱스만 변경) |
| 기존 recall 회귀 | tags lane은 **추가** — 기존 lane 순위를 밀어내지 않음 (RRF 결합) |
| 프라이버시 | 태그는 기존 발화 내용의 부분집합 — 새 정보 아님 |

## 6. 검증 계획

1. **0콜 사전 검증**: 스냅샷에서 10건의 tags lane 복구율 측정 (다음 단계)
2. 회귀: op-90 hit@3 유지 + pool_recall 상승 확인 (스냅샷 기준)
3. [11] 문맥 의존 건은 prefetch 쿼리 개선(최근 턴 키워드 결합)과 별도 처리

## 7. 판정 기준

- tags lane으로 retrieval miss 10건 중 **≥5건 pool 복구** → 채택
- <3건 → 기각 (검색 측 문제가 아님)
- 3~4건 → shadow 운영 데이터와 함께 판정

---

## 8. 0콜 사전 검증 결과 — **기각 확정** (2026-10-06)

### 실측
- 스냅샷 기준, retrieval miss 10건의 gold에 대해 "직접 대화 태그" 시뮬레이션:
  gold의 session_id + 저장 이전 user 발화 3개에서 키워드 추출 → 태그 후보 구성
  → 쿼리 토큰과 교집합 계산
- **결과: 태그 lane 복구 가능 0/10** — 쿼리 토큰과 직전 대화 태그의 교집합 0건

### 원인 분석
1. **시간적 분리**: gold 저장(07-31~08-25)과 평가 쿼리(그 후)는 다른 시점 —
   "저장 직전 대화"는 그 순간의 주제(프록시, model_override 등)일 뿐, 미래 질문
   ("전환 문제?", "Exa 왜 안 써?")과 다리가 없음
2. **핵심 가정 붕괴**: 설계의 "직전 대화에 질문의 다리가 되는 키워드가 있다"는
   전제가 실제 miss 10건엔 성립하지 않음 (gold는 summary성 기록이고, 쿼리는
   완전히 다른 관점/시점에서 접근)
3. [10] 18080 프록시: 세션 정보 없음 → 태그 후보 자체 부재

### 판정
- **A Q5 write-path 태그 — 기각** (구현 전 0콜 검증이 구한 사례)
- miss 10건의 근본 원인은 "저장 당시 맥락 부재"가 아니라 **검색 쿼리와 gold의
  표면 어휘·개념 단절** (의역/상위 개념 접근) — write-path로 해결 불가
- 남은 대안:
  - **read-path 쿼리 확장** (로컬 0콜: 쿼리 임베딩의 top-N 유사 메모리에서 단어 주입)
  - 또는 **구조적 상한 수용** (pool_recall 87.8%는 현 lane 구조의 실질 상한 —
    Run M에서 이미 "vec-rank 예외 레버 소진" 확인, stage40 evidence-span도 기각)
- [11] 문맥 의존 건은 prefetch 쿼리에 최근 턴 키워드 결합 (B Q5) — 별도 후보

---

## 9. read-path 쿼리 확장 0콜 검증 — **기각 확정** (2026-10-06)

### 설계
쿼리 임베딩 → 코퍼스 top-20 유사 메모리 → 그 메모리의 빈도 상위 단어 8개를
쿼리에 주입 → 확장 쿼리로 4-lane 재검색 → gold pool 복구 여부 측정 (0콜).

### 결과: **2/11 복구** (판정 기준 ≥5 미달)
- ✅ 복구 2건: "camelAI 라우팅", "TimeoutExpired"
- ❌ 9건: 확장 단어가 경로(Users/mandu), 메타 단어(ASSISTANT/codex), 범용어
  (현재/요약/세션)로 오염 — gold와 어휘·개념 단절은 쿼리 확장으로도 극복 불가

### 판정
- **read-path 쿼리 확장 — 기각** (단순 빈도 주입은 노이즈만 추가)
- 더 정교한 확장(불용어 강화 등)도 개선 여지 제한적 — 근본은 쿼리-골드 의미 단절
- **최종: 구조적 상한 수용** — pool_recall 87.8% (79/90; 문맥 의존 [11] 제외 시
  실질 80/89 = 89.9%)를 현 lane 구조의 상한으로 확정
- miss 11건 정리: 진짜 retrieval miss 10건 (수용) + 문맥 의존 1건 (B Q5 후보)