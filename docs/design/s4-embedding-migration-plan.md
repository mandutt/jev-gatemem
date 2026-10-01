# S4 마이그레이션 설계 — bekko-a8m 전환 (사전 등록 문서)

> 상위: `embed-benchmark-final-report.md` (S3 채택 확정)
> 작성: 2026-10-01. S3 결과 기반 S4 설계 초안. 실행 전 사용자 승인 대기.
> **상태: 설계 완료, 미실행.** 모든 수치/경로는 S3 실측 기반.

---

## 1. 목표

라이브 Mnemosyne DB(`%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db`)의 임베딩을
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`(baseline)에서
`hotchpotch/bekko-embedding-v1-a8m`(이하 a8m)으로 전환한다.

**무중단(라이브 접촉 최소화) + 롤백 가능 + 혼합 모델 벡터 방지**가 설계 제약.

## 2. 현 상태 (2026-10-01 실측)

- 라이브 DB `memory_embeddings`: MiniLM 949건 + bge-small 191건 혼재 (dim 모두 384)
  → **모델 불일치 행이 이미 공존** 중. vec 검색은 model 태그 미참조, 벡터 직접 비교.
- `config.yaml`: `embedding_model: MiniLM`, `embedding_dim: 384`
- a8m: 384-dim, 접두어 불필요, fastembed 기본 카탈로그 미등록(커스텀 등록 필요),
  재인덱스 조건 **배치 4 + 클램프 512** (S3 실측, 배치 상한 초과 시 OOM)

## 3. S4 설계에 반영한 Mnemosyne 업데이트 내성 항목 (2026-10-01 사용자 승인)

> 배경: a8m 등록은 커스텀 패치 기반이므로 Mnemosyne 업데이트가 코어를 덮어쓰면
> 한국어 분류 패치(`typed_memory.py`)와 동일하게 소실 가능. 아래 4항목으로 방어.

### 3-1. a8m 등록을 env 기반이 아닌 확정 코드/스크립트로 고정

- `scripts/reapply_embedding_model.py` (신규) — `reapply_korean_classifier.py` 선례 준수:
  - 설치 venv의 `mnemosyne/core/embeddings.py`에 a8m 모델명/dim을 멱등하게 재적용
  - 등록 방식: fastembed 커스텀 등록(모듈 레벨 패치) — env(`MNEMOSYNE_EMBEDDING_MODEL`)만으로는
    업데이트 시 `.env` 의존이 남고 카탈로그 검증 단계에서 실패할 수 있어 코드 고정이 우선
  - 검증: 적용 후 `python -c "from mnemosyne.core import embeddings; print(embeddings._DEFAULT_MODEL)"`
    → `hotchpotch/bekko-embedding-v1-a8m` 출력 확인
- 업데이트 체크리스트(§8)에 한국어 분류 패치와 **동일 사이클**로 편입

### 3-2. `embedding_dim: 384` 명시 기록 (폴백 우연 일치 제거)

- Mnemosyne `embeddings.py` `_get_embedding_dim()`은 알려진 모델 사전 + 폴백 384.
  a8m은 사전 미등록 모델이라 현재 **폴백이 우연히 384로 일치**하는 상태.
- 조치: `config.yaml` `embedding_dim: 384` 유지 + env `MNEMOSYNE_EMBEDDING_DIM=384`를
  `.env`에 명시 등록 → 사전/폴백 로직 변경과 무관하게 dim 고정
- 검증: 스왑 후 `recall(active).embedding_dimension == 384` 확인 (beam.py active 블록 실측)

### 3-3. model 태그 찍힘 확인 + 스왑 완료 후 model 분포 단일화 검증

- a8m 스왑 전: 커스텀 등록 모델이 `memory_embeddings.model` 컬럼에 실제로 태그되는지 확인
  (안 찍히면 혼합 감지가 불가능 → 이 경우 스왑 전 로직 보강 필요)
- 스왑 완료 후 검증 쿼리:
  ```sql
  SELECT model, COUNT(*) FROM memory_embeddings GROUP BY model;
  -- 기대: a8m 100% (레거시 0건)
  ```
- 레거시( MiniLM/bge ) 행은 스왑 중 전량 재임베딩으로 소멸시켜 **혼합 모델 벡터 0건** 보장

### 3-4. 업데이트 체크리스트 항목 추가

- `HANDOFF_NEXT_SESSION.md` §8 마지막 항목에 추가:
  - [ ] **Mnemosyne 업데이트 시** — ① `typed_memory.py` 한국어 패치 재적용
        ② `reapply_embedding_model.py` a8m 등록 재적용 (동일 사이클, 멱등 스크립트)

## 4. 마이그레이션 절차 (섀도 테이블 + 백그라운드 재임베딩 + 아토믹 스왑)

```
[준비] 스냅샷: VACUUM INTO로 라이브 DB 백업 (롤백 앵커)
   ↓
[1단계] 섀도 테이블 생성: memory_embeddings_a8m (동일 스키마)
   ↓
[2단계] 백그라운드 재임베딩: a8m 전용 프로세스가 working_memory 1,030+행을
        배치 4 / 클램프 512로 순차 임베딩 → 섀도 테이블 기록 (진행 ledger 행수 보고)
   ↓
[3단계] 무결성 검증: 섀도 행수 == 원본 행수, 샘플 gold 회수(S3 gold-50 재사용, MRR ≥ 0.75 게이트)
   ↓
[4단계] 아토믹 스왑: 트랜잭션 내 ①원본 → memory_embeddings_legacy_mlm ②섀도 → memory_embeddings
        ③config.yaml embedding_model 갱신 (동일 트랜잭션은 아님 — 순서: DB 먼저, config 즉시)
   ↓
[5단계] 라이브 검증: 데스크톱 재시작 없이 RPC/core 데몬 재기동 → recall 실측 (gold 쿼리 3건)
   ↓
[롤백 경로] 스왑 직후 문제 → legacy 테이블 역스왑 + config 복원 (1회 트랜잭션)
```

- **레거시 보존 기간**: 스왑 후 7일 유지 → 이상 무 확인 후 삭제 (사용자 승인)
- **JEV 하이브리드 영향**: FTS/BM25 레인은 무영향, vec 레인만 교체 → J1 rerank/gate 파이프라인 무수정
- **core 데몬(`jev-mem-core`)**: 스왑은 데몬 중단 없이 DB 파일 수준에서 수행(WAL 모드, busy_timeout 30s)
  → 진행 중 쓰기 충돌 방지 위해 스왑 트랜잭션은 데몬 idle 시점에 실행

## 5. 리스크 매트릭스 (S3 → S4 반영)

| # | 리스크 | 영향 | 대응 |
|---|---|---|---|
| 1 | 재임베딩 중 라이브 쓰기 유입 | 중 | 섀도 기간 동안 신규 쓰기는 a8m으로 기록되도록 **등록 패치를 재임베딩 시작 전 선적용** + 섀도 완료 시 신규 행 delta 재임베딩 |
| 2 | dim 매핑 폴백 우연 일치 | 중 | §3-2 명시 고정 |
| 3 | 커스텀 등록 소실 (업데이트) | 높음 | §3-1 재적용 스크립트 + §3-4 체크리스트 |
| 4 | 4.0.0 메이저 스키마 변화 | 낮음~중 | §7-12 정책(3.15.1 고정, 4.0.0 stable 확인 후) 유지 |
| 5 | 재임베딩 OOM (배치 상한 초과) | 낮음 | 배치 4 + 클램프 512 하드 고정, 프로세스 분리 |

## 6. 검증 게이트 (스왑 승인 조건)

- [ ] 섀도 행수 == 원본 행수
- [ ] gold-50(S3 세트) MRR ≥ 0.75 (S3 실측 0.772 대비 ±0.02 이내)
- [ ] model 태그 a8m 단일화 (레거시 0건)
- [ ] `recall(active)` embedding_dimension == 384, embedding_model == a8m
- [ ] 라이브 gold 쿼리 3건 회수 + trace 정상 (`write-gate`/`jev` 이벤트 무결)
- [ ] RAM: 스왑 후 core 데몬 Private Commit ≤ 650MB (S3 실측 617MB 기준)

## 7. 다음 단계

1. 본 설계 사용자 승인 (대기)
2. `reapply_embedding_model.py` 작성 + §3-1~3-2 선적용
3. 섀도 재임베딩 실행 (배치 4/클램프 512, 진행 ledger 보고)
4. 검증 게이트 통과 시 스왑 + 라이브 검증
5. 7일 후 레거시 삭제 승인
