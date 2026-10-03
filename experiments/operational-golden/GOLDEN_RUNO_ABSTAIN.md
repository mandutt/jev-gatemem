# Run O — Abstain-choice A/B (실측 완료 2026-10-03)

## 상태: 실측 완료 + 구현 적용 (라이브 데몬 반영, 커밋 예정)

- 2026-10-02 최초 실행: **BLOCKED** — TypeSafe 크레딧 0 (HTTP 402). raw: 100쿼리 전부 err.
- 2026-10-03: 크레딧 충전 + API 키 교체 후 **재실행 성공** (JEV 200콜, err 0).
- 실측 데이터: `abstain_run_O_raw.json` (100쿼리 × A/B, 2026-10-03 덮어씀).

## 목적

무답 쿼리 오주입(운영 골든셋 10/10 lift-to-wrong)을 score+threshold(토큰 2배) 없이 잡는 싼 실험:
choice 질문에 abstain 라벨 `c<N>`("No candidate is usable evidence...")을 추가해
JEV가 "어느 후보도 답이 아님"을 고르게 한다.

## 실측 결과 (n=98: gold 88 + 무답 10, err 0)

| 지표 | baseline | abstain | Δ |
|---|---|---|---|
| 무답 오주입 | 10/10 (100%) | **0/10 (0%)** | **-10건 (완전 해결)** |
| gold 정답 유지 | 59/88 | **59/88** | **0 손실** |
| gold wrong→none | — | 17건 | 전건 정화 |
| 토큰 | 기준 | **+34.6 tokens/콜 (+1.0%)** | 사실상 무비용 |
| 지연 | p50 235ms / p95 308ms | p50 228ms / p95 291ms | 변화 없음 |

### 판정

1. **무답 10/10 abstain** — 오주입 구조적 제거. Hermes 답변 계층의 "무답 lift" 문제 소스가 사라짐.
2. **gold 59/59 보존** — abstain 옵션이 "정답 있으면 고르고, 없을 때만 none"을 정확히 학습. **0건 false abstention**.
3. **gold wrong→none 17건 실사: 17/17 정화** — 전부 `gold_in_pool=False`
   (gold가 애초에 pool 40에 없음 = Pool Recall 미달의 기존 구조적 한계). 정답 상실 0건.
   abstain은 "답이 없을 때"만 발동.
4. 토큰 +1%, 지연 동일 — score+threshold(+50~100%) 대비 압도적으로 경제적.

## 구현 (gateway/j1_pipeline.py, gateway/gateway.py, jev_mem_core/pipeline.py)

- `JEV_ABSTAIN` env (기본 ON; '0'/'false'/'off' 등 비활성)
- `_jev_choice`: criteria에 abstain 라벨 추가 + instructions에 abstain 안내
- `jev_rerank`: **`(rows, abstained)` 튜플 반환** (기존 단일 list → 호출부 전부 수정)
  - abstain 선택 시 `(pool, True)` — lift 없음
- `gateway.py` / `pipeline._rerank`: abstained=True면 **빈 결과 반환** → prefetch가 "메모리 없음" 컨텍스트
- 단위 검증 (fake client): abstain ON/OFF/lift/failure 4분기 통과
- 라이브 검증: 무답 쿼리 → 빈 context (`"## Mnemosyne Context"` 내용 0),
  gold 쿼리 → 정상 context. 로그 `Jev choice: idx=22 pool=22` = abstain 선택.

## 프로토콜 (재실행 시)

```bash
cd C:/Users/mandu/hermes-made/jev-memory-middleware
/c/Users/mandu/AppData/Local/jev-mem/venv/Scripts/python.exe \
  experiments/operational-golden/run_o_abstain.py    # 100쿼리 x A/B 병렬, ~2-5분
/c/Users/mandu/AppData/Local/jev-mem/venv/Scripts/python.exe \
  experiments/operational-golden/analyze_abstain_O.py
```

- 데이터: `golden_final_v2.json` (45 gold x literal/paraphrase + 10 무답 = 100쿼리)
- 각 쿼리: 동일 stage1 pool(40)에 대해 baseline choice vs abstain choice를 **병렬 POST** (JEV 1콜/arm, 데몬·DB 불변)
- 개별 분류: gold / wrong / none(abstain) / no_pick / err
- 검증: `run_o_dry_validate.py` — baseline 질문 dict가 daemon `_jev_choice`와 구조 동일 + abstain criteria 스키마 OK (pool=29, payload 18.9KB, 2026-10-02 dry-run 통과)

## 설계 배경 (실측 근거)

- JEV choice는 쿼리당 1콜; abstain은 criteria 1줄 추가만으로 토큰 +α (vs score 방식 listwise는 state+문서 질문 중복으로 +50~100%)
- Jev 점수는 배치-상대적(풀 55: 0.600 vs 전체 419: 0.767, 2026-10-01) → threshold 기반 필터는 검증 전 채택 금지
- 기존 결론: 무답 오주입은 "lift된 무관 후보"가 문제 → abstain 라벨이 정답을 건드리지 않고 중립적으로 오주입을 제거하는지가 실험 질문

## 파일

- `run_o_abstain.py` — 실험 러너 (JEV 직접 호출, stage1 pool 재사용)
- `analyze_abstain_O.py` — 리포트 (metrics/transition/token delta)
- `run_o_dry_validate.py` — 페이로드 구조 검증 (JEV 0회)
- `audit_abstain_17.py` — gold wrong→none 17건 실사 (전건 정화 확인)
- `abstain_run_O_raw.json` — 2026-10-03 실측 raw (재실행 시 덮어씀)