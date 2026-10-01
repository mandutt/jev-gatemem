# S4 마이그레이션 설계 v2 — bekko-a8m 전환 (외부 AI 3건 검토 종합 반영)

> 상위: `embed-benchmark-final-report.md` (S3 채택 확정)
> v1: 2026-10-01 초안 (`s4-embedding-migration-plan-v1.md` 보존) → 외부 AI 3건(a/b/c) 검토 → 본 v2 (2026-10-01 종합 반영)
> **상태: 설계 완료, 미실행.** 실행 전 사용자 승인 대기.
> 검토 원문: `Downloads/{a,b,c}-ai-s4 임베딩 마이그레이션 수정 필요 항목.md`

---

## 0. v1 → v2 핵심 변경 (3 AI 종합)

| # | v1 설계 | 문제 (검토 지적) | v2 수정 |
|---|---|---|---|
| P0-1 | 재임베딩 전 등록 패치 선적용 → 신규 쓰기 a8m | **재임베딩 기간 내내 live DB에 3개 모델 벡터 혼합 → vec 검색 품질 붕괴** (c/b/a 공통, c-AI "반드시 수정") | **등록(register)과 활성(activate) 분리.** 재임베딩 중 live 데몬은 baseline 유지, a8m은 migration worker만 사용 |
| P0-2 | working_memory 1,030행만 재임베딩 | **episodic 113건 누락 → 영구 소실** (a/b 지적, 라이브 실측으로 확인) | 대상 = working 1,138 + **episodic 113** 전수. 단, episodic은 `memory_embeddings`에 없고 `vec_episodes`에만 존재 (§2 실측) |
| P0-3 | "무중단" + 데몬 중단 없이 WAL 스왑 | DB 트랜잭션 원자성 ≠ 앱 무중단. DB/config 2-phase crash 불일치, 스왑-재기동 사이 쿼리가 구모델로 a8m 테이블 오염 (c/b/a 공통) | **짧은 maintenance window cutover**: 데몬 정지 → 스왑 → config 적용 → 재기동 (수십 초~1분) |
| P0-4 | 테이블 rename 스왑 | vec0 가상 테이블 rename 불안전 + rename 시 트리거/뷰 참조 따라감 + 인덱스 이름 충돌 (b/c 지적, 라이브 스키마 실측으로 확인) | `memory_embeddings`는 **단일 트랜잭션 내용 교체**(CTAS 보존 → DELETE → INSERT SELECT), vec0 테이블은 **delete+insert 재구축** |
| P0-5 | 롤백 = legacy 역스왑 단일 경로 | cutover 후 신규 a8m 행은 legacy에 없음 → 역스왑 시 벡터 소실 (c/b 지적) | 롤백 3단계 정의 (§6): 즉시 역스왑 / reopen 후 delta 재임베딩 / 재해 복구 백업 |

## 1. 목표

라이브 Mnemosyne DB(`%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db`)의 임베딩을
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`(baseline)에서
`hotchpotch/bekko-embedding-v1-a8m`(이하 a8m)으로 전환한다.

**제약: 재임베딩 중 live embedding space 무혼합 + cutover는 짧은 정지 창 + 시점별 롤백 경로 보장.**

## 2. 현 상태 (2026-10-01 라이브 실측 — v2 사전조사)

- **`memory_embeddings`** (일반 테이블, PK memory_id, 인덱스 2개): 1,145건
  - model 분포: MiniLM 954 + bge-small 191
  - source 커버리지: **working 1,138 (100%, 누락 0) + orphan 7** / episodic 0
  - **bge 191건 원인 특정**: 생성 시점 07-31~08-24에 국한, 전부 working 소속 →
    당시 활성 모델이 bge였던 시기의 잔재. 08-24 이후 bge 유입 없음 →
    b-AI가 우려한 "숨은 인프로세스 경로" 가설은 불필요. 단, 스왑 시 전량 재임베딩으로 소멸 확인.
- **episodic 113건의 임베딩은 `memory_embeddings`에 없고 `vec_episodes`(vec0 가상 테이블)에만 존재**
  → v1이 "memory_embeddings 행수 = 재임베딩 대상"으로 착각한 원인 (a/b-AI 지적의 실측 확인)
- **주 vec 저장소 = sqlite-vec 가상 테이블** (`vec_working` rowid 기반, `vec_episodes`, `vec_facts`).
  `memory_embeddings`는 폴백/호환 저장소 → **S4는 양쪽 모두 갱신해야 함**
  (Mnemosyne `_store_working_embedding`이 두 저장소에 동시 기록하는 구조)
- vec0 테이블: sqlite-vec v0.1.9, **rename 불가, delete+insert만 가능** (v1 rename 계획 폐기 근거)
- working_memory 트리거(wm_ai/au/ad)는 FTS 전용 — memory_embeddings와 무관
  (rename 참조 오염 리스크 없음을 실측 확인했으나, 인덱스 충돌 회피 위해 여전히 내용 교체 채택)
- config: `embedding_model: MiniLM`, `embedding_dim: 384`
- a8m 운영 조건: 배치 4 + 클램프 512 (S3 실측, 상한 초과 시 OOM)

## 3. 업데이트 내성 항목 (v1 §3 유지 + c/b-AI 보강)

### 3-1. 등록/활성 분리 (v1의 "패치로 _DEFAULT_MODEL 고정" 폐기 — c-AI #9 반영)

- `scripts/register_bekko_a8m.py` = **커스텀 모델 카탈로그 등록만**.
  패키지 파일 수정 대신 **jev-mem-core 기동 스크립트에서 mnemosyne import 전 등록** 방식 지향
  (b-AI #10-3 — 업데이트가 덮어쓸 파일 감소 + 카탈로그 검증 실패 회피).
  인프로세스 경로는 §2 bge 원인 실측상 활성 경로가 아니므로 core 데몬 경로만 커버로 충분.
- `config.yaml` = active 모델 선택 (cutover 시점에만 변경)
- `scripts/reapply_embedding_model.py` = 등록 상태 검증 + 카나리 테스트(§3-5) 역할
- **활성화는 마이그레이션 스크립트가 cutover 창에서 단 한 번 수행** — v1의 "재임베딩 전 선적용" 폐기
- 등록 시 토크나이저 **truncation(=512) 고정 포함** (a-AI #3 — 라이브 경로 긴 문서 OOM 방지)

### 3-2. dim 명시 고정 (v1 유지)

- `config.yaml embedding_dim: 384` + `.env` `MNEMOSYNE_EMBEDDING_DIM=384` — 폴백 우연 일치 의존 제거
- 검증: 스왑 후 `recall(active).embedding_dimension == 384` 실측

### 3-3. model 태그 + 리비전 (b-AI #10 반영)

- `memory_embeddings.model` = `hotchpotch/bekko-embedding-v1-a8m` 태그 확인 (v1 유지)
- 모델 파일 리비전을 태그에 포함 검토 (`@<rev 8자>`) — 모델 무음 교체 감지. 태그 파서 영향 확인 후 채택

### 3-4. 업데이트 체크리스트 (v1 유지)

- Mnemosyne 업데이트 시: ① `typed_memory.py` 한국어 패치 재적용 ② a8m 등록 재검증(카나리) — 동일 사이클

### 3-5. 카나리 테스트 (b-AI #10 반영)

- 고정 한국어 문장의 기준 벡터를 사전 저장 → 등록 검증·데몬 기동 직후 코사인 ≥ 0.999 확인
- `_DEFAULT_MODEL` 문자열 출력만으로는 등록 소실/접두사/클램프 누락을 잡지 못함

### 3-6. 오프라인 경로 고정 (a-AI #6 반영)

- a8m 가중치를 고정 로컬 경로(`%LOCALAPPDATA%/hermes/mnemosyne/models/bekko-a8m`)에 스테이징,
  HF 네트워크/캐시 클린업 의존 제거

## 4. 마이그레이션 절차 v2 (Shadow + T0 delta + 짧은 cutover 창)

```
[준비] 전체 백업 (재해 복구 앵커):
        ① VACUUM INTO → %LOCALAPPDATA%/hermes/mnemosyne/backup/s4-pre-migration-<ts>/mnemosyne.db
        ② 설정 스냅샷: config.yaml / .env 임베딩 행 / 등록 패치 상태
        ③ 무결성 게이트: 복제본 open → PRAGMA integrity_check → 핵심 테이블 행수·ID checksum 대조
        ④ 복원 리허설: 백업본에서 recall 1건 실측 (b-AI #9)
        ⑤ rollback_s4.py 사전 작성·검증 (a-AI #7) — 커맨드 한 줄 복원
        ⑥ sqlite_schema 프리플라이트 (c-AI #10) — 실측 완료(§2): 트리거 0, 뷰 0,
           vec0 의존은 별도 가상 테이블 → 교체 방식 확정 가능
   ↓
[1단계] 등록 선작업: a8m 카탈로그 등록 + 로컬 가중치 스테이징 + 카나리 검증.
        **live 데몬 active 모델은 MiniLM 유지** (등록만, 활성화 아님 — P0-1)
   ↓
[2단계] T0 스냅샷 기록: 재임베딩 대상 ID 집합 + content 해시 + 시퀀스.
        대상 = working_memory 전체(1,138) + episodic_memory 전체(113) — 원천 텍스트 기준 전수
        **레거시 벡터 참조 금지 — content 원문에서 a8m 벡터 신규 생성** (a-AI #5)
   ↓
[3단계] 섀도 재임베딩 (migration worker 전용, a8m):
        - memory_embeddings_a8m (동일 스키마)에 JSON 기록
        - vec_working/vec_episodes는 vec0라 사전 적재 불가 →
          rowid+벡터를 ledger에 축적, cutover 창에서 delete+insert (vec0 특성)
        - **이 기간 live 데몬은 baseline 그대로** — 검색/쓰기 품질 무영향
        - 배치 4 + 클램프 512, S3와 동일 양자화 경로(int8 quantize) 재사용 — b-AI #7
        - 진행 ledger 행수 주기 보고
   ↓
[4단계] 섀도 검증 (cutover 전, full metric set — c-AI #7):
        - Source coverage: 대상 ID 집합 == 섀도 ID 집합 (missing 0, orphan 0, duplicate 0)
        - 모델/차원: a8m 100%, 384D 100%, blob 길이·dtype 기대값 일치
        - 내용 정합: source_text_hash == 현재 원문 해시 (migration 중 변경 행 탐지)
        - S3 벡터 일치: S3 bekko 벡터와 동일 내용 행 코사인 ≥ 0.999 (b-AI #8)
        - gold-50 + 하이브리드: 라이브(혼합 현재 상태)와 섀도를 같은 쿼리로 쌍별 비교 (b-AI #8)
        - RAM: 최악 케이스(2만자 문서 단건) 라이브 경로 실측 ≤ 650MB (b-AI #6)
   ↓
[5단계] Cutover (짧은 maintenance window, 수십 초~1분 — P0-3):
        ① 데몬 쓰기 drain/freeze → 코어 데몬(jev-mem-core) 정지
        ② delta 반영: T0 이후 생성/수정/삭제 행을 a8m으로 처리 (수 초)
           delta = created_at/updated_at 기반 ID 추적, INSERT/UPDATE/DELETE 전부 (c-AI #5)
        ③ 단일 트랜잭션 DB 교체:
           - memory_embeddings: CTAS로 legacy 보존(memory_embeddings_legacy_mlm)
             → DELETE 전체 → 섀도 INSERT SELECT (rename 미사용 — P0-4)
           - vec_working/vec_episodes: ledger의 rowid+벡터로 delete+insert
           - orphan 7건: 원천 소실 행은 제거 (원천 없는 벡터 무의실)
        ④ config.yaml embedding_model 갱신 + 등록 활성화 (DB 먼저, config 즉시)
        ⑤ 데몬 재기동 → health check (config/DB model 일치, dim, 카나리, RAM, recall smoke)
        ⑥ 통과 시 write reopen
   ↓
[검증] 라이브 실측: gold 쿼리 3건, model 분포 a8m 단일(레거시 0), trace 정상,
        vec_weight=0.3 하이브리드 동작, RAM p95 ≤ 650MB
```

- **J1/JEV 파이프라인 무수정**: FTS/BM25 레인 무영향, vec 레인만 교체
- **에이전트 클라이언트 동작**: cutover 창(수십 초) 중 에이전트 요청은 client의 스풀링/재시도 경로로 대기 — 창 길이 제한의 이유

## 5. 리스크 매트릭스 (v2)

| # | 리스크 | 영향 | 대응 |
|---|---|---|---|
| 1 | 재임베딩 중 live space 혼합 | 높음 | **폐기 완료(P0-1)** — live는 baseline 유지, a8m은 worker만 |
| 2 | DB/config crash 불일치 | 중 | cutover를 단일 maintenance 절차로 묶고 health check 게이트 (P0-3) |
| 3 | episodic/vec0 누락 | 높음 | 대상 정의를 원천 테이블 전수로, vec0는 delete+insert (P0-2/4) |
| 4 | 커스텀 등록 소실 (업데이트) | 높음 | §3-1 등록 스크립트 + §3-5 카나리 + §3-4 체크리스트 |
| 5 | 재임베딩 OOM | 낮음 | 배치 4 + 클램프 512 — worker·라이브 모두 (§3-1 truncation 고정) |
| 6 | 백업 자체 결함 | 낮음 | 무결성 게이트 + 복원 리허설 |
| 7 | dim 폴백 우연 일치 | 중 | §3-2 명시 고정 |
| 8 | 4.0.0 메이저 스키마 변화 | 낮음~중 | §7-12 정책 유지 (3.15.1 고정) |
| 9 | 라이브 경로 긴 문서 OOM | 중 | 등록 시 truncation=512 고정 + 최악 케이스 RAM 게이트 (b-AI #6) |

## 6. 롤백 경로 (시점별 3단계 — P0-5, c-AI #6 / b-AI #9 반영)

| 시점 | 방법 |
|---|---|
| **A. cutover 직후, write reopen 전** | legacy 테이블 역스왑 + config 복원 + 데몬 재기동 (rollback_s4.py 1커맨드) |
| **B. reopen 이후 (신규 a8m 행 존재)** | legacy 역스왑 후 **신규/변경 행을 MiniLM으로 delta 재임베딩** (~40초). 복원 결과는 원래 혼합 상태(MiniLM+bge)임을 명시 |
| **C. 재해(DB 손상 등)** | pre-migration 전체 백업 복원 (완전 앵커) |

- legacy 테이블 + 전체 백업은 스왑 안정 확인(7일)까지 보존, 삭제는 사용자 승인
- legacy = "빠른 되돌림 shortcut", 백업 = "재해 복구 앵커" — 역할 구분 명시

## 7. 검증 게이트 (스왑 승인 조건, v2)

- [ ] 백업 무결성 게이트 통과 (integrity_check + 행수/ID checksum + 복원 리허설)
- [ ] Source coverage: 대상 ID 집합 == 섀도 ID 집합 (missing/orphan/duplicate 0) — working+episodic 포함
- [ ] 내용 정합: source_text_hash 일치 (stale embedding 0)
- [ ] 모델/차원: a8m 100%, 384D 100%, blob dtype·길이 기대값 일치
- [ ] S3 벡터 일치: 동일 내용 행 코사인 ≥ 0.999
- [ ] gold-50 + 하이브리드 쌍별 비교: 섀도가 라이브 혼합 상태 대비 열화 없음 (MRR은 보조 지표)
- [ ] 최악 케이스(긴 문서) 라이브 RAM ≤ 650MB
- [ ] 카나리 벡터 코사인 ≥ 0.999
- [ ] 라이브 gold 쿼리 3건 회수 + trace 정상 + 하이브리드(vec_weight 0.3) 동작

## 8. 다음 단계

1. 본 v2 사용자 승인 (대기)
2. 사전 작업: `register_bekko_a8m.py` + `rollback_s4.py` 작성, 가중치 로컬 스테이징, 카나리 기준 벡터 저장
3. 섀도 재임베딩 실행 (T0 기록, 진행 ledger 보고)
4. §7 게이트 통과 → cutover 창 실행
5. 7일 관찰 후 legacy/백업 삭제 승인
