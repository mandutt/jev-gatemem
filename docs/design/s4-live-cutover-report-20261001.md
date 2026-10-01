# S4 라이브 컷오버 리포트 — 2026-10-01

## 결과: ✅ 성공 (최종 상태 100% `bench/bekko-a8m` 단일 모델)

## 타임라인 (실측)

| 시각 | 단계 | 결과 |
|---|---|---|
| 15:45:27 | 사전 백업 `VACUUM INTO` | `s4-pre-migration-20261001-154527.db` (18.0MB, integrity ok) + config/env 스냅샷 |
| 15:45~ | 라이브 preflight | connection busy 0, orphan 7 식별 |
| — | 데몬 정지 | pythonw 프로세스 종료, health 000 확인 |
| 15:46 | `live_step2_reindex.py` | **37.3s**, working 1,152 + episodic 113 재인덱스, orphan 7 삭제 |
| 15:52~15:58 | 데몬 재기동 3회 실패 | warmup failed: "Could not load bench/bekko-a8m" (원인 아래) |
| 15:53 | MiniLM 오염 사건 | 데몬이 fallback MiniLM으로 기동 → 첫 turn 1건 MiniLM 태그로 저장 |
| 15:55 | `live_fixup.py` | 오염 행 포함 전체 재인덱스 **54.7s**, 1,153행 → 100% a8m |
| 15:58 | 데몬 기동 성공 | a8m warmup 성공, 라이브 쓰기 → `bench/bekko-a8m` 태그 실측 확인 |
| 15:59 | 검증 행 정리 | 테스트 1건 삭제(vec_working 포함), 1,153 단일 모델 복원 |

## 사건 1: 데몬 모델 미스매치 (MiniLM fallback)

**증상**: `.env`를 a8m으로 수정했음에도 재기동 데몬이 MiniLM으로 로드. 첫 라이브 turn이 MiniLM 태그로 저장됨 (1행 오염).

**원인 2중**:
1. 데스크톱 부모 프로세스 env에 수정 전 MiniLM 값이 상주 → 자식 상속 (client.py auto-start 경로)
2. `MNEMOSYNE_FASTEMBED_CACHE_DIR` 미설정 시 커스텀 별칭(`bench/bekko-a8m`)이 fastembed 캐시에서 해석 불가 → warmup 실패 → fallback MiniLM으로 서빙 지속

**해결**:
- jev-mem venv에 `sitecustomize.py` 설치: (a) `bench/bekko-a8m` 커스텀 등록, (b) tokenizer clamp(512), (c) `TextEmbedding.__init__` 강제 `cache_dir` 주입 (setdefault 아님 — mnemosyne이 cache_dir kwarg를 명시 전달하므로 강제가 필요), (d) `HF_HUB_OFFLINE=1`
- 데몬 기동 env에 `MNEMOSYNE_EMBEDDING_MODEL=bench/bekko-a8m` + `MNEMOSYNE_FASTEMBED_CACHE_DIR=<bench>/fe-cache` 명시

## 사건 2: 데몬 warmup 실패 → fallback 미탐

**교훈**: 데몬은 warmup 실패 시 **에러 로그 1줄 + fallback 모델로 계속 서빙**한다. 운영 가드가 `memory_embeddings.model` 분포만 보면 늦음. 라이브 쓰기 1건의 모델 태그가 유일한 실측 증거.

**권고 (P1, 미착수)**: 데몬 `/v1/status`에 `embedding_model` 필드 노출 + 기동 가드가 warmup 실패 시 fallback 대신 **기동 중단(fail-fast)** 전환.

## 사건 3 (경미): sqlite_vec 미로드 쿼리 실패

vec0 가상 테이블 조회 시 `no such module: vec0` — sqlite_vec extension 로드 후 정상. 리허설 R-스크립트들은 이미 로드하고 있었으므로 문서화 수준의 사항.

## 최종 상태 (15:59 실측)

```
memory_embeddings.model 분포 : bench/bekko-a8m 1,153 (100%)
vec_working                  : 1,153
vec_episodes                 : 113
binary_vector                : 113
integrity_check              : ok
orphan                       : 0
spool 잔여                   : 0
ingest_ledger 테스트 잔여    : 0
```

## 롤백 경계 (미사용, 보존)

- 백업: `%LOCALAPPDATA%/hermes/mnemosyne/backups/s4-pre-migration-20261001-154527.db` + `.meta.json`
- config/env 스냅샷: `s4-config-snapshot-20261001-154527/`
- 7일 후(2026-10-08) 검증 안정화 확인 후 삭제 권고

## 재인덱스 시간 실측 요약 (a8m, batch 4)

| 실행 | 행 수 | 시간 |
|---|---|---|
| 리허설 R3 | 1,259 | 33.8s |
| 라이브 step2 | 1,265 (orphan 7 제외 후) | 37.3s |
| fixup (오염 복구) | 1,153 | 54.7s |

※ v4 계획서의 ~5분 추정 대비 실측 40~55s. cold cache 시 더 걸릴 수 있으나 maintenance window는 **2분 이내**로 확정 가능.
