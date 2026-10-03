# Run O — Abstain-choice A/B (금지/대기 상태 기록)

**상태: BLOCKED — TypeSafe API 크레딧 0원 (HTTP 402 Payment Required, 2026-10-02 확인).**
실측 데이터는 `abstain_run_O_raw.json`(100쿼리 전부 `err`, JEV 호출 196/196 실패) — 판정 없음.

## 목적
무답 쿼리 오주입(운영 골든셋 4/10)을 score+threshold(토큰 2배) 없이 잡는 싼 실험:
choice 질문에 abstain 라벨 `c40`을 추가해 JEV가 "어느 후보도 답이 아님"을 고르게 한다.

## 프로토콜 (충전 후 재실행)
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
- 판정 기준:
  - **무답**: abstain 전환율 (baseline 오주입 4건 중 몇 건이 none이 되는가)
  - **gold**: gold-pick 유지율 (baseline gold-pick이 abstain에서 none으로 flip되는 비율 = 오탐 비용)
  - 토큰 증가량 (usage.input_tokens delta), 지연 p50/p95
- 검증: `run_o_dry_validate.py` — baseline 질문 dict가 daemon `_jev_choice`와 구조 동일 + abstain criteria 스키마 OK (pool=29, payload 18.9KB, 2026-10-02 dry-run 통과)

## 설계 배경 (실측 근거)
- JEV choice는 쿼리당 1콜; abstain은 criteria 1줄 추가만으로 토큰 +α (vs score 방식 listwise는 state+문서 질문 중복으로 +50~100%)
- Jev 점수는 배치-상대적(풀 55: 0.600 vs 전체 419: 0.767, 2026-10-01) → threshold 기반 필터는 검증 전 채택 금지
- 기존 결론: 무답 오주입은 "lift된 무관 후보"가 문제 → abstain 라벨이 정답을 건드리지 않고 중립적으로 오주입을 제거하는지가 실험 질문

## 파일
- `run_o_abstain.py` — 실험 러너 (JEV 직접 호출, stage1 pool 재사용)
- `analyze_abstain_O.py` — 리포트 (metrics/transition/token delta)
- `run_o_dry_validate.py` — 페이로드 구조 검증 (JEV 0회)
- `abstain_run_O_raw.json` — 2026-10-02 실행의 실패 raw (402, 재실행 시 덮어씀)