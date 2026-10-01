# S4 마이그레이션 설계 v4 — bekko-a8m 전환 (v3 외부 검토 3건 종합 반영)

> 상위: `embed-benchmark-final-report.md` (S3 채택 확정)
> 이력: v1 → 1차 검토 → v2 → 2차 검토 → v3 (`reindex_vectors()` 재설계) → **3차 검토 → 본 v4 (2026-10-01)**
> **상태: 설계 완료, 미실행.** 실행 전 사용자 승인 대기.
> 검토 원문: `Downloads/{a,b,c}-ai-임베딩 마이그레이션 v3 검토.md`
> 이전 버전 보존: `s4-embedding-migration-plan-v1.md` / `-v2.md` / `-v3.md`

---

## 0. v3 → v4 핵심 변경 (3차 검토 종합 + 실측 검정)

3차 검토의 지적은 라이브 코드·S3 보고서 대조 실측으로 검정 후 반영했다.

| # | 검토 지적 | 실측 검정 | v4 반영 |
|---|---|---|---|
| P0-A | **정지 시간 산정 오류** — v3의 "40초~2분"은 근거 없음. a8m 재인덱스 807.6초(13.5분) (c/a 공통, 가장 치명적) | **부분 타당**: 807.6s는 클램프 512 적용 **전** 수치. S3 최종 실측 = **클램프 적용 후 278.9초(≈4.6분)** (final report §5). 단, "40초~2분"도 틀렸음(40s는 MiniLM 배치64) | 창 시간을 **"실측 278.9s 기준, 예상 5~8분, 리허설 벽시계 실측치로 최종 확정"**으로 현실화. 에이전트 idle·사용 중단을 사전 운영 통제로 명시, "스풀링이 버텨준다"는 가정 의존 제거 |
| P0-B | **vec0 rollback 테스트 설계 오류** — `reindex_vectors()`는 vec0 DROP/CREATE 후 즉시 commit, batch마다 commit → 전체가 하나의 트랜잭션이 아님. ROLLBACK 복귀 시나리오 성립 안 함 (c) | **타당**: 함수 소스 확인 — batch별 `conn.commit()` 존재. 중간 실패 시 부분 상태 잔존 | 리허설 목적을 **"intentional failure injection → 부분 상태 확인 → 데몬 미기동 유지 → 백업 복원 → 완전 원복 검증"**으로 변경. 백업 복원이 recovery boundary임을 명시 |
| P0-C | **orphan 7건 자동 소멸 가정 오류** — `reindex_vectors()`는 기존 orphan을 삭제하지 않음 (c) | **타당**: 함수 소스에 DELETE 없음 — working/episodic만 overwrite | preflight에서 orphan 7 ID 확정·백업 보존 → reindex 후 **정확히 그 ID만 명시 삭제** → model 분포 게이트. 데이터 손실 아님을 백업으로 검증 가능 |
| P0-D | **`reindex_vectors()` 성공 결과 맹신 금지** — embed None 시 `break` 후 `status=reindexed` 찍힘, 처리량 완전성 미검증 (c) | **타당**: 소스 확인 — break 경로 존재 | **외부 completeness validator 필수화**: planned( dry-run 카운트 ) vs actual( 저장소별 카운트/커버리지 ) 전수 대조 (§7-L2) |
| P1-E | **롤백 B가 행 복원과 재계산을 혼동** — 백업 복원하면 신규 memory 원문이 사라져 delta 재임베딩 대상이 없음 (b) | **타당 + 더 나은 경로 발견**: 공식 API가 있으므로 | **롤백 B 재설계**: config/.env 원복 → 데몬 정지 상태에서 **`reindex_vectors()`를 MiniLM으로 재실행** (~40s 규모) — 모든 행 보존, **순수 MiniLM 상태 복귀**(혼합 복귀 우려도 해소). 백업 복원은 A(재임베딩 중/직후)와 재해 C에만 |
| P1-F | 배치 불변성은 "인용"으로 부족 — 재인덱스(배치4) vs 라이브 쓰기(배치1) 공간 일치 검증 필요 (b) | **기존 실측 존재**: `p0_batch_invariance.json` — S2에서 bekko/koen 배치 1/4/16 min_cos 0.99999+ 실측 완료. b-AI가 몰랐던 데이터 | 리허설 게이트에 **동일 시험의 재실행(복제 DB·현재 등록 경로 기준)** 명시 + 기존 S2 실측 결과 인용 병기. 인용만으로 닫지 않음 |
| P1-G | **vec_weight=0.3 동시 변경 여부 확정** — 모델 교체와 ranking 변경을 섞으면 원인 분리 불가 (c) | **실측**: 현재 운영 vec_weight = **0.5** (env 미설정, Mnemosyne 기본값). S3의 0.3은 권장안일 뿐 production 확정 아님 (final report §5도 "현행 설정과 대조 필요" 명시) | **이번 migration은 vec_weight 0.5 유지** — 변수 분리. 0.3 튜닝은 **별도 change(S5)**로 분리, migration 후 데이터 안정화 후 재평가 |
| P1-H | **L2 품질 게이트를 데몬 재기동 전에 완료** — 기동 후 L2 실패 시 롤백 B 필요 → 데이터 손실 경로 (b) | 타당 | 절차 변경: reindex 직후 **격리 하니스로 L1+L2 전부 완료 → 통과 시에만 기동**. 기동 후 검증은 확인용. 롤백 경로가 A만으로 수렴 |
| P1-I | **reindex 직전 활성 모델 fail-closed 검증** — 등록 실패 시 폴백 모델로 전체 재구축 "성공" 위험 (b) | 타당 | ④ 직전 같은 프로세스에서 assert: `active model == a8m`, `dim == 384`, 카나리 코사인 ≥ 0.999 → 실패 시 reindex 미시작 |
| P1-J | 상태 마커에 REINDEXING 누락 — config 변경과 DB_COMMITTED 사이 공백 (b) | 타당 | 마커 상태 머신: `PREPARED → REINDEXING → VALIDATED → HEALTHY`. 가드는 PREPARED/REINDEXING에서 기동 거부. 복구 규칙: 중단 시 **재실행 우선(멱등), 2회 실패 시 백업 복원** |
| P1-K | 기동 가드가 vec0를 안 봄 — memory_embeddings.model만으론 vec0 상태 미증명 (b/c) | 타당 | 가드 강화: ① vec_working/vec_episodes 카운트 == expected(dry-run 계획치) ② declared dim == 384 ③ vec type == int8 ④ **표본 재임베딩 대조**(각 3~5행, 코사인 ≥ 0.999, 부팅 시 ~1-2초) ⑤ `embedding_meta` 행 기록 후 config 대조 |
| P1-L | 정지 대상은 jev-mem-core 하나뿐 — 다른 DB writer 존재 가능 (b) | 타당 | cutover 절차: 정지 프로세스 명시 목록화 → 정지 후 **잔여 연결 0 확인** (`wal_checkpoint(TRUNCATE)` busy 0 + `-wal` 파일 비어있음 + 짧은 exclusive lock 성공) |
| P1-M | 품질 비교 기준 데이터 불일치 — S3 baseline은 9/30 스냅샷, 라이브는 이후 변화 (b) | 타당 | 리허설 복제본에서 **동일 데이터로 MiniLM 전량 재임베딩 vs a8m 직접 대조** + 판정 규칙 수치 고정: 쌍별 차이 bootstrap 95% CI 하한 ≥ -0.03 AND 점추정 ≥ -0.01 |
| P1-N | DELETE replay는 타임스탬프로 역추적 불가 (a) | v4 롤백 B 재설계(P1-E)로 소멸 — delta replay 개념 제거 | — |
| P1-O | 리허설이 라이브 config를 건드릴 위험 — 경로 전역 (b) | 타당 | 리허설 스크립트 시작 시 **DB·config 경로가 라이브와 다름 assert** + 데이터 디렉터리 env 분리 (S3 벤치 선례) |
| P1-P | 백업 복원 시 WAL/SHM 처리 (c, GitHub #707 인용) | 타당 | rollback_s4.py에 명시: 모든 writer 종료 확인 → `.db/.db-wal/.db-shm` 처리 → 복원 후 `integrity_check` + `journal_mode` + 실제 recall( sqlite-vec 로드 상태 ) 확인 |
| P1-Q | 진행 가시성 + 타임아웃 (b) | 타당 | reindex progress 콜백 → 행수 진행률·ETA 로그 + **상한(리허설 실측 ×2) 초과 시 중단 → 롤백** |
| P1-R | 라이브 쓰기 경로 smoke 누락 — L1이 읽기만 검증 (b) | 타당 | L1에 추가: working/episodic 각 1건 테스트 쓰기 → 태그·vec 적재·벡터 일치 확인 → 삭제 → **삭제가 vec0 행까지 정리하는지** 확인 (고아 벡터 방지) |
| P1-S | 백업의 vec0 내용 검증 — integrity_check는 가상 테이블 내용 미보장 (b) | 타당 | 백업 무결성 게이트에 vec0 행수 + 표본 벡터 해시 추가, 복원 리허설에서 sqlite-vec 로드 상태로 vec 쿼리 실제 실행 |
| P1-T | 버전 고정 (c) | 타당 | migration_state.json에 Mnemosyne/core·Python·ORT·sqlite-vec 버전 기록 → 재현성 확보 |

**판정 분포**: c="구조 승인, P0 4개 수정 후 실행 승인" / b="리허설 착수 승인, 1~9번 반영 후 결과 보고" / a="조건부 최종 승인(리허설 착수)".
v4는 위 전체를 흡수. 미해결 외부 질문(c/b 공통 — reindex 중간 실패 시 transaction boundary)은 리허설 항목 P0-B로 확정 답을 얻도록 설계.

## 1. 목표

라이브 Mnemosyne DB 임베딩을 MiniLM baseline에서 `hotchpotch/bekko-embedding-v1-a8m`으로 전환.

**v4 설계 제약 (v3에서 확정·현실화):**
- 모델 교체 + 재임베딩은 **Mnemosyne 공식 `reindex_vectors()` 단일 경로** (수작업 벡터 조작 금지)
- **오프라인 cutover**: 재임베딩은 데몬 정지 상태에서 실행. 창 시간 = **S3 클램프 적용 실측 278.9s 기준, 예상 5~8분, 리허설 벽시계 실측으로 최종 확정**
- **에이전트 완전 대기가 사전 운영 통제**: cutover 동안 모든 에이전트(Hermes/Codex/pi/OpenCode) 사용 중단 — 스풀링 의존 가정 폐기 (P0-A)
- **L1+L2 게이트를 기동 전 완료** — 기동은 검증 통과 후에만 (P1-H)
- 롤백: A(기동 전)=백업 복원 / B(기동 후)=**config 원복 + MiniLM reindex 재실행** / C(재해)=백업 복원
- 이번 migration은 **vec_weight 0.5 유지** (변수 분리 — P1-G)

## 2. 현 상태 (2026-10-01 라이브 실측)

- `memory_embeddings`: 1,145건 (MiniLM 954 + bge-small 191, 후자는 07-31~08-24 잔재)
  - source 커버리지: working 1,138 (100%) + **orphan 7** / episodic 0
- episodic 113건: `vec_episodes`(vec0)에만 존재 / `vec_facts`: **0건 + writer 없음** (beam.py 주석 실측) → 재임베딩 제외 확정
- 주 vec 저장소 = sqlite-vec v0.1.9 가상 테이블; `memory_embeddings`는 폴백/호환 저장소
- config: `embedding_model: MiniLM`, `embedding_dim: 384` / **운영 vec_weight = 0.5 (기본값)** / a8m: 384-dim, 접두어 불필요
- a8m 재인덱스 실측: **클램프 512 + 배치 4 = 278.9s** (S3, 1,143행) / 배치 불변성: 배치 1/4/16 min_cos 0.99999+ (S2 `p0_batch_invariance.json`)
- `reindex_vectors()` 특성 (소스 실측): batch별 commit(비원자) / embed None 시 break 후 status=reindexed / orphan 미삭제 / dry_run 지원

## 3. 운영 방어 항목 (v3 유지 + 수정)

### 3-1. 등록/활성 분리
- `scripts/register_bekko_a8m.py` = fastembed 커스텀 카탈로그 등록 (import 전 등록 방식, 패키지 파일 미수정)
- 활성화는 migration 스크립트가 config.yaml 변경으로 단 1회 / 등록 시 truncation(=512) 고정 포함

### 3-2. dim 명시 고정
- `config.yaml embedding_dim: 384` + `.env` `MNEMOSYNE_EMBEDDING_DIM=384`

### 3-3. model 태그 (v3 확정 유지)
- `memory_embeddings.model` = `hotchpotch/bekko-embedding-v1-a8m` (등호 비교 호환)
- 리비전은 `migration_state.json`의 `model_revision`에 별도 기록 — `model` 문자열에 미부착

### 3-4. 업데이트 체크리스트
- Mnemosyne 업데이트 시: ① 한국어 분류 패치 재적용 ② a8m 등록 재검증(카나리) ③ 기동 가드 통과 확인

### 3-5. 카나리 테스트
- 고정 한국어 문장 기준 벡터 vs 실측 코사인 ≥ 0.999 — 등록 검증·reindex 직전(P1-I)·데몬 기동 가드

### 3-6. 오프라인 경로 고정
- a8m 가중치 고정 로컬 경로 스테이징 (`%LOCALAPPDATA%/hermes/mnemosyne/models/bekko-a8m`)

### 3-7. 기동 가드 + 상태 마커 (v3에서 강화 — P1-J/K)
- `migration_state.json`: `PREPARED → REINDEXING → VALIDATED → HEALTHY` + 버전 기록
  (Mnemosyne/core, Python, ORT, sqlite-vec — P1-T)
- **jev-mem-core 기동 가드** — 시작 전 전부 확인, 실패 시 서비스 시작 거부:
  ① `memory_embeddings` model 분포 단일 + config model 일치 (provenance 검사)
  ② **vec_working/vec_episodes 카운트 == 마커의 planned 카운트** (storage integrity)
  ③ vec0 declared dim == 384 + vec type == int8
  ④ **표본 재임베딩 대조**: vec_working/vec_episodes 각 3~5행 재임베딩 → 저장 벡터와 코사인 ≥ **0.995 (int8 양자화 노이즈 바닥 실측 ≈0.9958; fp32 JSON 대조 시에만 ≥ 0.999)** (부팅 시 ~1-2초)
  ⑤ 카나리 코사인 ≥ 0.999
  ⑥ `embedding_meta`(model, revision, dim, 시각)와 config 대조
- 가드는 PREPARED/REINDEXING 상태에서도 기동 거부 (crash 시 혼합/불완전 상태 서비스 차단)

## 4. 마이그레이션 절차 v4

```
[준비]
        ① 백업: VACUUM INTO → backup/s4-pre-migration-<ts>/mnemosyne.db
           + 설정 스냅샷 + rollback_s4.py 사전 작성(WAL/SHM 절차 포함 — P1-P)
        ② 백업 무결성 게이트: integrity_check + 행수/ID checksum
           + vec0 행수·표본 벡터 해시 + 복원 리허설(sqlite-vec 로드 상태로 vec 쿼리 실측 — P1-S)
        ③ preflight: orphan 7 ID 확정·기록(백업 보존 — P0-C)
           + dry_run=True로 planned 카운트 확정(1,251행 가정 하드코딩 금지)
           + mnemosyne import 프로세스/venv 목록화 → 정지 대상 명시 (P1-L)
        ④ 전체 dry-run 리허설 (복제 DB, 격리):
           - 스크립트 시작 시 DB·config 경로가 라이브와 다름 assert + env 분리 (P1-O)
           - 데몬 정지 → 활성화 → fail-closed assert(P1-I) → reindex_vectors(배치4, progress 콜백)
             → **벽시계 시간 실측** (예상 5~8분 기준, 실측치가 창 길이의 유일한 근거)
           - intentional failure injection → 부분 상태 확인 → 백업 복원 → 완전 원복 검증
             (P0-B — SQLite ROLLBACK 테스트 아님, 백업 복원이 recovery boundary임을 실측)
           - 배치 불변성 재검증: 샘플 20행 배치 1/4/16 코사인 ≥ 0.999
             (S2 p0_batch_invariance.json 0.99999+ 실측 존재 — 현재 등록 경로로 재확인 — P1-F)
           - 동일 데이터 대조: 복제본에서 MiniLM 전량 재임베딩 vs a8m (P1-M)
           - L1+L2 게이트 전체를 기동 전 실행 (P1-H)
           - 리허설 미통과 시 live 실행 금지
   ↓
[1단계] 등록 선작업: 카탈로그 등록 + 가중치 스테이징 + 카나리 검증 (live는 아직 MiniLM)
   ↓
[2단계] Cutover (오프라인 창, 리허설 실측치 기준):
        ① 에이전트 완전 대기 확인(운영 통제) → 정지 대상 프로세스 전부 정지
           → 잔여 연결 0 확인: wal_checkpoint(TRUNCATE) busy 0 + -wal 비어있음 + exclusive lock 성공 (P1-L)
        ② fail-closed assert: 활성 모델 == a8m, dim == 384, 카나리 코사인 ≥ 0.999
           → 실패 시 reindex 미시작, config 즉시 원복 (P1-I)
        ③ 활성화: config.yaml embedding_model=a8m + .env 적용
        ④ reindex_vectors(batch_size=4, progress 콜백) 실행
           - 타임아웃 가드: 리허설 실측 ×2 초과 시 중단 → 롤백 A (P1-Q)
        ⑤ orphan 7건 명시 삭제 (preflight 확정 ID만 — P0-C)
        ⑥ migration_state.json = VALIDATED 준비 + 버전 기록
   ↓
[3단계] 검증 (기동 전 — P1-H):
        - 외부 completeness validator (P0-D): planned vs actual 전수 대조 —
          working 임베딩 수 == planned, vec_episodes rowid 커버리지 100%,
          binary_vector 커버리지 100%, vec_working missing/orphan 0, model=a8m, dim=384, vec_type=int8
        - L1 smoke + L2 품질 게이트(격리 하니스, S3 baseline 기준 — §6) 전부 통과
        - 통과 시에만 migration_state.json = HEALTHY → 데몬 기동 → 가드 통과 → 서비스 개시
        - 실패 시 → 롤백 A (백업 복원)
   ↓
[4단계] 기동 후 확인 (확인용 — 롤백 경로 아님):
        - gold 3건, trace 정상, 라이브 쓰기 smoke(쓰기→태그·vec·벡터 일치→삭제→고아 확인 — P1-R)
        - 잔존 MiniLM/bge 행 감시 (1시간 후 재확인 — 숨은 경로 신호)
        - L3 운영 승인: 24h 잔존 혼합 0 + vec0 주기 표본 대조 / 7d 안정 → 백업 정리 승인
```

## 5. 롤백 경로 (v4 — P1-E 재설계)

| 시점 | 방법 |
|---|---|
| **A. 기동 전 (재임베딩 중/직후, 검증 실패 포함)** | 데몬 정지 상태 유지 → **pre-migration 백업 복원** → config 원복 → 기동 가드 → 재기동. rollback_s4.py 1커맨드 |
| **B. 기동 후 문제 발견** | 데몬 정지 → **config/.env 원복(MiniLM) → `reindex_vectors()` 재실행** (~40s 규모) → 검증 → 재기동. **모든 행 보존, 순수 MiniLM 상태 복귀** — 백업 복원 불필요, delta replay 개념 없음 (공식 API 멱등성 활용) |
| **C. 재해(DB 손상 등)** | 백업 복원 (A와 동일 절차) |

- 백업 보존: 7일, 삭제는 사용자 승인
- v3의 "백업 복원 후 delta 재임베딩" 경로는 원문 소실 문제(b-AI #2)로 폐기

## 6. 품질 게이트 기준 정의 (v3 확정 유지 + P1-M 구체화)

- **품질 참조선 = S3 실험 baseline** / 현재 live 혼합 DB는 운영 연속성 참고용
- 리허설 복제본에서 **동일 데이터로 MiniLM 전량 재임베딩 vs a8m 직접 대조** — 데이터 변화 교란 제거
- 판정 규칙 수치 고정: 쌍별 차이 **bootstrap 95% CI 하한 ≥ -0.03 AND 점추정 ≥ -0.01** (hybrid F1)
- **vec_weight = 0.5 유지** (현재 운영값) — 모델 교체와 ranking 튜닝의 변수 분리.
  0.3 튜닝은 별도 change(S5)로 migration 후 데이터 안정화 후 재평가 (P1-G 실측 반영)

## 7. 검증 게이트 (3층 + 리허설)

**리허설 게이트 (live 실행 전 필수):**
- [ ] dry-run 전 절차 완주 + 벽시계 창 시간 실측 기록
- [ ] failure injection → 백업 복원 → 완전 원복 실측 (P0-B)
- [ ] 배치 불변성 재검증 (1/4/16 코사인 ≥ 0.999; S2 실측 0.99999+ 참조)
- [ ] 동일 데이터 MiniLM vs a8m 대조 + 판정 규칙 적용
- [ ] 리허설 격리 assert 통과 (라이브 경로 무접촉)

**L1 즉시 smoke (기동 전, 절차 §4-3):**
- [ ] completeness validator 전 항목 통과 (P0-D)
- [ ] model 분포 단일 (a8m 100%, bge 191·orphan 7 포함 레거시 0)
- [ ] 카나리 코사인 ≥ 0.999 + 기동 가드 전 항목 통과
- [ ] warm idle Private Commit ≤ 650MB (G1 500MB 대비 완화 명시 기록)
- [ ] worst-case(긴 문서) peak Private Commit 별도 측정 ≤ 650MB

**L2 품질 승인 (기동 전 완료 — P1-H):**
- [ ] gold-50 + 하이브리드(vw=0.5) — S3 baseline 대비 §6 판정 규칙 충족
- [ ] S3 bekko 벡터 일치: 동일 내용 행 코사인 ≥ 0.999

**L3 운영 승인 (24h/7d):**
- [ ] 24h: 잔존 혼합 행 0 + recall 지연/오류 0 + vec0 주기 표본 대조 통과
- [ ] 라이브 쓰기 smoke 통과 + 고아 벡터 0
- [ ] 7d: 안정 확인 → 백업/마커 정리 승인

## 8. 다음 단계

1. 본 v4 사용자 승인 — **리허설 착수 승인 완료 (2026-10-01), 리허설 전 항목 PASS** → 결과 보고: `s4-rehearsal-report-20261001.md`
2. 사전 작업: `register_bekko_a8m.py` + `rollback_s4.py` + 기동 가드 작성, 가중치 스테이징, 카나리 기준 벡터 저장
3. 복제 DB 전체 dry-run 리허설 → 실측치(창 시간, failure 복원, 배치 불변성, 동일 데이터 대조) 기록
4. 리허설 결과 보고 → live cutover 최종 승인 → 실행 → L1/L2 → L3 관찰
5. 7일 관찰 후 정리 승인
