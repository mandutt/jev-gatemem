# STAGE101b: 조건부 α 탐색 — 운영 신호 분리 시도 (2026-10-08, 0콜)

## 배경

stage101 실측: fusion α=0.7이 op +2/+3·abstain −2, noans FP +1. flip 8건(cu 승리 3건 · fu 승리 5건).
조건부 α로 cu 승리 3건(현행 RRF가 더 나은 쿼리)을 살리면서 fu 승리 5건(fusion 이득)을 유지할
**운영에서 관찰 가능한 신호**를 0콜로 탐색.

## 탐색 결과 (모두 0콜, 데몬 venv + sqlite-vec 로드)

### 후보 신호 1: adjusted top-1의 lane 구성 (imp-only 여부)
- flip 8건 **전부** top-1이 동일한 행(`d1c905` 프로필 규칙, imp_rank=2) — cu/fu 승리 구분 불가
- noans FP 3건 중 2건만 top1_imp_only, noans 전체 29/50이 top1_imp_only → FP 구분 불가
- **기각**

### 후보 신호 2: 쿼리 어휘 (규칙/말투/원칙)
- flip 8건 중 '한국어 말투 규칙 뭐지?' 1건만 해당 — opencode/데스크톱(cu 승리) 누락
- **기각** (stage64~66 도메인 오버핏 기각과 동일 결론)

### 후보 신호 3: gold의 lane rank (vec_rank/fts_rank)
- fu 승리 5건: gold vec_rank 1~2 (키리스 2, 코덱스 1, 마우스 1, KoDialog 1, CAMOFOX 2)
- cu 승리 3건: gold vec_rank 5(한국어 말투), 1(opencode), 36(데스크톱)
- **변별력 있으나 gold는 운영에서 관찰 불가(사후 정보)** → 운영 반영 불가
- 단, opencode(vec=1인데 cu 승리)은 fusion이 fts norm 0 gold를 fts rank 20~22 후보에게 밀린 케이스 — 'vec 1위'여도 fusion이 항상 좋은 건 아님

## 추가 발견: 프로세스 간 재현 비결정성

- 동일 프로세스 내 build_pool/fusion_reorder는 완전 결정적 (3회 반복 일치)
- **프로세스 간에는 pool 순서가 ±1~2 rank 달라짐** (opencode fusion gold rank: 파일 6 vs 재현 3)
  - 원인: fastembed ONNX 세션이 프로세스마다 재로드, 부동소수점 연산 순서 차이로 sim 소폭 변동 추정
  - `valid_until` 경계 행은 0건 — 시간 필터 아님
- **영향**: 0콜 재현 기반 조건부 설계는 이 노이즈에 민감. stage101 실측 자체(해당 시점 pool로 JEV 호출)는 유효
- **flip 8건은 8/8 재현 일치** (큰 차이 쿼리라 노이즈에 강건) — stage101 결론(+2/+3) 견고

## 결론

- **운영 가능한 조건부 신호 없음** → 조건부 α 설계 불가 (0콜 탐색 한계)
- 남은 선택지: ① α=0.7 전면 채택 (op +2/+3·abstain −2, noans +1) ② α=0.5 실측(추가 200콜, noans 방어 확인) ③ 보류
- **판정: 사용자 결정 대기**

## 산출물

- 본 문서 (STAGE101B)
- stage101_fusion07_raw.json (400콜 실측 raw, 커밋 39afa7b)
- stage101_fu_gold_rank_repro.json (fu gold rank 재현 — 프로세스 간 노이즈 감안 필요)