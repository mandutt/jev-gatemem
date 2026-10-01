# S4 마이그레이션 설계 v3 — bekko-a8m 전환 (외부 AI 2차 검토 3건 종합 + 재설계)

> 상위: `embed-benchmark-final-report.md` (S3 채택 확정)
> 이력: v1 (초안) → AI 3건 검토 → v2 → AI 3건 2차 검토 → **본 v3 (2026-10-01)**
> **v3는 v2 구조(섀도 테이블 + delta ledger + rowid 수동 재구축)를 폐기하고
> Mnemosyne 공식 `reindex_vectors()` 기반으로 재설계한 것.** 근거는 §0-★.
> **상태: 설계 완료, 미실행.** 실행 전 사용자 승인 대기.
> 검토 원문: `Downloads/{a,b,c}-ai-임베딩 마이그레이션 v2 검토.md`
> 이전 버전 보존: `s4-embedding-migration-plan-v1.md`, `s4-embedding-migration-plan-v2.md`

---

## 0. v2 → v3 재설계 근거

### ★ 핵심 발견: Mnemosyne 공식 `reindex_vectors()` API (beam.py:2394)

2차 검토 전 라이브 코드 실측에서, v1/v2가 수작업으로 설계한 것과 동일한 작업을 하는
**공식 내장 함수가 이미 존재**함을 확인:

> *"Rebuild every vector representation from source text with the ACTIVE embedding model...
> It re-embeds working_memory and episodic_memory and refreshes every store,
> **reusing the same write helpers the normal store path uses so encodings stay consistent.**
> Synchronous and blocking — **run it offline (with any provider/gateway stopped)**. Idempotent."*

커버 저장소: `memory_embeddings`(working float JSON) + `vec_working` + `vec_episodes` +
`episodic_memory.binary_vector` + `vec_facts`(writer 없음 — dim 불일치 방지용 빈 재생성).
**모델 교체 직후 사용이 문서화된 정식 용도**이며, S3 벤치마크에서 배치 4로 1,143행 완주 실측됨.

이 함수 채택으로 v2의 다음 요소 전부 제거:
- 섀도 테이블 (`memory_embeddings_a8m`) — 불필요
- T0 delta ledger (rowid+벡터 축적) — **불필요** (b-AI #3 "rowid 재사용 위험" 소멸)
- cutover 시 vec0 delete+insert 수공예 — **불필요** (DROP+재생성 내장)
- CTAS legacy 복사 (c-AI #2 "CTAS는 PK/인덱스 미보존" 지적) — **불필요**
- 배치 1 vs 4 불변성 우려 (b-AI #6) — 함수가 동일 helper로 단일 경로 사용

### 2차 검토 반영 (v3에 흡수)

| AI | 지적 | v3 반영 |
|---|---|---|
| c | 품질 게이트 기준을 "live 혼합 상태"가 아닌 **S3 실험 baseline**으로 고정 | ✅ §6 게이트 재정의 |
| c | CTAS legacy는 rollback table 부적격 (PK/제약 미보존) | ✅ legacy 테이블 개념 자체 제거 — 롤백은 백업 복원으로 일원화 |
| c | vec0 rollback semantics를 0.1.9에서 실측 리허설 | ✅ 리허설 항목에 포함 (§4-①) |
| c | reopen 후 롤백에 DELETE replay 누락 | ✅ v3 롤백 B에서 delta replay 정의에 DELETE 포함 |
| c | gold 3건 = smoke, 게이트는 gold 50 | ✅ 3층 검증(§7)으로 분리 |
| c | "RAM p95"는 측정 정의 오류 | ✅ warm idle / worst-case peak 지표로 분리 |
| c | model 문자열에 @rev 붙이면 등호 비교 실패 위험 | ✅ 리비전은 별도 ledger metadata로만 기록 (§3-3 수정) |
| c | DB commit과 config commit 사이 crash 상태 머신 미정의 | ✅ migration_state.json 마커 + 기동 가드 (§3-7) |
| c | 1분은 목표치일 뿐 — 리허설로 실측 | ✅ 전체 dry-run 리허설 필수화 (§4-①) |
| b | **vec_facts 누락** | ✅ 실측: **0건 + writer 없음** (beam.py "no writer yet") → §2에 확정 기록. 재임베딩 불요 |
| b | 롤백 A/B가 vec0 구(舊) 벡터를 못 복원 | ✅ 구조 자체 변경 — vec0는 reindex가 DROP/재생성하므로 롤백은 백업 복원만 |
| b | rowid ledger 위험 | ✅ v3에서 ledger 자체 제거 |
| b | 타임스탬프 delta 탐지 누락 가능 | ✅ v3에서 delta 개념 제거 — 재임베딩 자체가 cutover 직후 1회 실행이므로 delta 없음 |
| b | "숨은 인프로세스 경로 불필요" 근거 약함 | ✅ 반영 — 재시작 후 잔존 MiniLM 행 감시 게이트로 방어 (§7) |
| b | vec_weight=0.3이 cutover 변경 목록에 없음 | ✅ 변경 목록 명시 (§4-④) |
| b | 클라이언트 스풀링은 가정일 뿐 실측 필요 | ✅ 데몬 정지 상태 4클라이언트 쓰기 실측 항목 (§4-①) |
| a | vec0 INSERT 시 rowid 명시 바인딩 | ✅ v3에서 수동 INSERT 제거 — 함수 내부 처리 |
| a | cutover 전 `wal_checkpoint(TRUNCATE)` | ✅ 절차에 명시 (§4-③) |
| a | 에이전트 idle 확인 후 cutover | ✅ 표준 절차에 포함 (§4-③) |

**a-AI는 "실행 승인" 판정, c-AI는 "P0 4개 수정 후 승인", b-AI는 "1~7번 반영 + 리허설 결과 첨부 후 승인".**
v3는 위 표대로 전부 흡수했으며, 구조 단순화로 c/b의 P0 다수가 원천 소멸됨.

## 1. 목표

라이브 Mnemosyne DB 임베딩을 MiniLM baseline에서 `hotchpotch/bekko-embedding-v1-a8m`으로 전환.

**v3 설계 제약 (v2 대비 변경):**
- 모델 교체 + 재임베딩은 **Mnemosyne 공식 `reindex_vectors()` 단일 경로**로 수행 (수작업 벡터 조작 금지)
- 재임베딩은 **오프라인(데몬 정지) 상태에서 실행** — 공식 권장 사용법. 무중단 목표 폐기,
  대신 **재임베딩 시간(1,251행 ≈ 40초~2분 실측 규모)을 정지 시간으로 명시하고 사전 리허설로 실측**
- 롤백은 **pre-migration 전체 백업 복원 단일 경로** (legacy 테이블/역스왑 개념 제거)
- 기동 가드로 혼합 모델 상태에서의 서비스 시작 원천 차단

**이 제약 조합의 안전성**: 백업→(정지)→활성화→재임베딩→검증→(실패 시 백업 복원)→기동.
불일치 상태로 서비스가 뜨는 경로가 기동 가드 하나로 봉쇄됨.

## 2. 현 상태 (2026-10-01 라이브 실측, v2 사전조사 + v3 추가 실측)

- **`memory_embeddings`** (일반 테이블, PK memory_id, 인덱스 2개): 1,145건
  - model 분포: MiniLM 954 + bge-small 191 (07-31~08-24 잔재, 이후 유입 없음)
  - source 커버리지: working 1,138 (100%) + orphan 7 / episodic 0
- **episodic 113건**: `memory_embeddings`에 없고 `vec_episodes`에만 존재 (v2 실측 확인)
- **`vec_facts`: 0건, writer 없음** (beam.py 주석 "no writer yet — recreated empty") —
  **b-AI #1 지적에 대한 실측 답: 재임베딩 대상에서 제외 확정.** reindex가 dim 불일치 방지용으로 빈 재생성만 수행
- 주 vec 저장소 = sqlite-vec v0.1.9 가상 테이블 (`vec_working` rowid 기반, `vec_episodes`);
  `memory_embeddings`는 폴백/호환 저장소 — **reindex가 양쪽 모두 갱신** (b-AI 구조 우려 해소)
- working_memory 트리거(wm_ai/au/ad)는 FTS 전용 — 임베딩 테이블과 무관
- `episodic_memory.binary_vector` 컬럼도 재임베딩 대상 (reindex가 갱신)
- config: `embedding_model: MiniLM`, `embedding_dim: 384` / a8m: 384-dim, 접두어 불필요
- a8m 운영 조건: 배치 4 + 클램프 512 (S3 실측)

## 3. 운영 방어 항목 (v2 §3 유지 + 2차 검토 수정)

### 3-1. 등록/활성 분리 (v2 유지)

- `scripts/register_bekko_a8m.py` = fastembed 커스텀 카탈로그 등록
  (jev-mem-core 기동 스크립트에서 mnemosyne import 전 등록 — 패키지 파일 미수정)
- 활성화는 migration 스크립트가 cutover 창에서 config.yaml 변경으로 단 한 번 수행
- 등록 시 토크나이저 **truncation(=512) 고정 포함**

### 3-2. dim 명시 고정 (v2 유지)

- `config.yaml embedding_dim: 384` + `.env` `MNEMOSYNE_EMBEDDING_DIM=384`

### 3-3. model 태그 (c-AI #10 반영 수정)

- `memory_embeddings.model` = `hotchpotch/bekko-embedding-v1-a8m` (기존 컬럼, 등호 비교 호환)
- **리비전은 `model` 문자열에 붙이지 않음** — migration ledger(`migration_state.json`)에
  별도 기록 (`model_revision`) — 모델 무음 교체는 카나리가 잡음

### 3-4. 업데이트 체크리스트 (v2 유지)

- Mnemosyne 업데이트 시: ① 한국어 분류 패치 재적용 ② a8m 등록 재검증(카나리)

### 3-5. 카나리 테스트 (v2 유지)

- 고정 한국어 문장 기준 벡터 vs 실측 벡터 코사인 ≥ 0.999 — 등록 검증·데몬 기동 직후 수행

### 3-6. 오프라인 경로 고정 (v2 유지)

- a8m 가중치 고정 로컬 경로 스테이징 (`%LOCALAPPDATA%/hermes/mnemosyne/models/bekko-a8m`)

### 3-7. 기동 가드 + 상태 마커 (신규 — c-AI #11 / b-AI 기동 가드 반영)

- `migration_state.json` 마커: `PREPARED → DB_COMMITTED(config 포함) → HEALTHY`
- **jev-mem-core 기동 스크립트 가드**: 시작 전
  ① `memory_embeddings` model 분포가 단일하고 config model과 일치하는지
  ② 카나리 코사인 ≥ 0.999인지
  → 불일치 시 **서비스 시작 거부 + 오류 보고** (혼합 상태 서비스 원천 차단)
- 이 가드는 Mnemosyne 업데이트 후에도 혼합 상태 기동을 막는 상시 방어선

## 4. 마이그레이션 절차 v3 (reindex_vectors 단일 경로)

```
[준비]
        ① 백업: VACUUM INTO → backup/s4-pre-migration-<ts>/mnemosyne.db
           + 설정 스냅샷(config.yaml/.env 임베딩 행) + rollback_s4.py 사전 작성
        ② 백업 무결성 게이트: 복제본 open → integrity_check → 행수/ID checksum 대조
        ③ **전체 dry-run 리허설 (복제 DB에서, 격리)** — 아래 전 절차를 복제본에 수행:
           - 데몬 정지 → 활성화 → reindex_vectors(배치 4) → 검증 게이트 → 기동 가드 → 롤백 복원
           - 실측 기록: 재임베딩 총 시간, cutover 창 실측치(목표 ≤60s는 목표일 뿐, 실측 P95로 확정)
           - vec0 rollback semantics: reindex 트랜잭션 의도 실패 → ROLLBACK →
             row count/rowid/벡터 해시가 이전 상태 복귀하는지 실측 (sqlite-vec 0.1.9 직접 검증 — c-AI #5)
           - 데몬 정지 상태에서 Hermes/Codex/pi/OpenCode 4클라이언트 쓰기 시도 →
             스풀링/재시도 동작·유실 0·창 길이 < 클라이언트 타임아웃 실측 (b-AI 클라이언트 검증)
           - 리허설 미통과 시 live 실행 금지 (게이트)
        ④ bge 191건 잔존 경로 최종 확인: mnemosyne import 프로세스/venv 목록화 —
           재시작 후 잔존 MiniLM 행 감시로 2차 방어 (§7)
   ↓
[1단계] 등록 선작업: 카탈로그 등록 + 로컬 가중치 스테이징 + 카나리 검증
        (live는 아직 MiniLM — 활성화 아님)
   ↓
[2단계] Cutover (오프라인 창, 실측 시간으로 확정 — 리허설 값 기준):
        ① 에이전트 idle 육안 확인 (a-AI 운영 권고) → 데몬 정지(jev-mem-core)
        ② 잔여 락 정리: PRAGMA busy_timeout=30000 + wal_checkpoint(TRUNCATE) (a-AI #3)
        ③ 활성화: config.yaml embedding_model=a8m + .env 등록 적용 (등록 활성 단 1회)
        ④ **reindex_vectors(batch_size=4, progress=ledger 콜백)** 실행 —
           모든 저장소를 원천 텍스트에서 a8m으로 전량 재구축
           (bge 191건·orphan 7건·MiniLM 전부 소멸, 이것이 곧 delta 처리)
        ⑤ migration_state.json = DB_COMMITTED (config/model 리비전 기록)
   ↓
[3단계] 검증 (§7 3층 게이트):
        - L1 즉시 smoke: gold 3건, model 분포 단일, trace, 카나리, 기동 가드 통과
        - L2 품질 승인: gold-50 전수 + 하이브리드 (S3 baseline 기준 — §6)
        - L1 실패 → 즉시 롤백(§5)
        - L1 통과 + L2 대기 중 → 데몬 재기동 허용하되, L2 통과 전 마커는 HEALTHY 아님
   ↓
[4단계] 완료: migration_state.json = HEALTHY → 7일 관찰 → 백업 삭제는 사용자 승인
```

**변경 목록 한 줄 명시 (b-AI #7):** `embedding_model`(config), `MNEMOSYNE_EMBEDDING_DIM=384`(.env),
등록 활성(기동 스크립트), `vec_weight=0.3`(하이브리드 파라미터, 채택안 포함 시) —
롤백 시 4항목 모두 원복. truncation=512는 등록 내부 고정(롤백 대상 아님).

## 5. 롤백 경로 (v3 — 단일화, c-AI #2/#4 / b-AI #2 근본 해소)

| 시점 | 방법 |
|---|---|
| **재임베딩 중/직후, 데몬 미기동** | 데몬 정지 상태 유지 → **pre-migration 백업 복원** → config 원복 → 기동 가드 → 재기동. rollback_s4.py 1커맨드 |
| **기동 후 문제 발견** | 데몬 정지 → **백업 복원** → (선택) 그 사이 신규 memory는 MiniLM으로 delta 재임베딩 — **INSERT/UPDATE/DELETE 전부 replay** (DELETE 누락 시 부활 버그 방지 — c-AI #4). 복원 결과는 원래 혼합 상태(MiniLM+bge 191) — **정상 복귀이지 순수 baseline 복귀가 아님**을 명시 |
| **DB 손상 등 재해** | 백업 복원 (동일 앵커) |

- **legacy 테이블/역스왑 경로 완전 제거 근거**: v2 롤백 A/B는 `memory_embeddings`(폴백 테이블)만
  되돌리고 주 저장소인 vec0 구 벡터는 복원 불가(b-AI #2 지적 타당) + CTAS는 PK/인덱스 미보존(c-AI #2).
  백업은 DB 파일 전체이므로 vec0 포함 완전 복원 — 단일 경로가 더 강력.
- 백업 보존: 7일, 삭제는 사용자 승인

## 6. 품질 게이트 기준 정의 (c-AI #1 반영 — v2의 가장 중요한 수정)

- **S3 실험 baseline = migration 품질 참조선** (S3 게이트: hybrid F1 delta ≥ -0.01 등)
- **현재 live 혼합 DB = 운영 연속성 참고용일 뿐, 품질 기준선 아님**
- 판정 구조: `post-migration a8m vs S3 baseline` — "live 혼합 상태보다 나쁘지 않음"으로는 승인 안 함

## 7. 검증 게이트 (3층 — c-AI #8 반영)

**L1 즉시 smoke (cutover 직후, 분 단위):**
- [ ] model 분포 단일 (`SELECT model, COUNT(*)` → a8m 100%, 레거시 0 — bge 191도 0)
- [ ] **잔존 MiniLM/bge 행 감시** — cutover 1시간 후 재확인 (재임베딩 이후 신규 유입 = 숨은 경로 존재 신호 → 즉시 조사, b-AI #5)
- [ ] 카나리 코사인 ≥ 0.999 + 기동 가드 통과
- [ ] gold 3건 회수 + trace 정상(`write-gate`/`jev`)
- [ ] warm idle Private Commit ≤ 650MB (p95 표현 제거 — c-AI #9)

**L2 품질 승인 (마이그레이션 승인 조건):**
- [ ] gold-50 전수 + 하이브리드(vw=0.3) — **S3 baseline 대비 게이트 충족** (hybrid F1 delta ≥ -0.01)
- [ ] 쌍별 비교는 bootstrap CI로 판정 (50쿼리 임계 점측 방지 — b-AI)
- [ ] S3 bekko 벡터 일치: 동일 내용 행 코사인 ≥ 0.999
- [ ] worst-case(긴 문서) peak Private Commit ≤ 650MB (별도 측정, idle과 분리)
- [ ] RAM 650MB는 사전 등록 G1 500MB 대비 완화임을 명시 기록 (b-AI)

**L3 운영 승인 (24h/7d 관찰):**
- [ ] 24h: 잔존 혼합 행 0 + recall 지연/오류 0 + vec0 표본 재임베딩 코사인 ≥ 0.999 (주기적 — b-AI)
- [ ] 7d: 안정 확인 → 백업/마커 정리 승인

**리허설 게이트 (실행 전):**
- [ ] dry-run 전 절차 완주 + 창 시간 실측 기록
- [ ] vec0 rollback 실측 (0.1.9)
- [ ] 4클라이언트 정지 중 쓰기 유실 0 실측
- [ ] 배치 불변성: S3에서 배치 4 완주+품질 게이트 통과 실측으로 커버 (b-AI #6 인용)

## 8. 다음 단계

1. 본 v3 사용자 승인 (대기)
2. 사전 작업: `register_bekko_a8m.py` + `rollback_s4.py` 작성, 가중치 스테이징, 카나리 기준 벡터 저장, 기동 가드 구현
3. 복제 DB 전체 dry-run 리허설 → 실측치(창 시간 등) 기록
4. 리허설 게이트 통과 → live cutover 실행 → L1/L2/L3 게이트
5. 7일 관찰 후 정리 승인
