# stage47e: head-150 + 겹침-150(non-overlap) 병합 — 전 지표 개선 (2026-10-06)

stage47d(단순 head+겹침)가 WHY gold에서 겹침 구간이 head와 겹쳐 동어반복 abstain이 된
문제를 해결: **겹침 후보 시작이 head(150) 안이면 건너뛰고 head 이후 최대 겹침 선택**.

## 결과 (3조건 동일 세션 420콜, err 0)

| cond | hit@1 | hit@3 | abstain | noans FP |
|---|---|---|---|---|
| cur (current 라벨 + 300→150 절단) | 73 | 77 | 7 | 21 |
| imp150 (improved + win150) | 69 | 77 | 7 | 13 |
| **imphbn (improved + head150+겹침150 non-overlap)** | **75** | **79** | **6** | **14** |

## 핵심 쿼리 (모든 이전 문제 케이스 해결)

| 쿼리 | cur | imp150 | imphbn |
|---|---|---|---|
| gemini 별칭 | rank 1 | rank 9 ❌ | **rank 1** ✅ |
| codex CLI 메모리 | rank 1 | rank 5 ❌ | **rank 1** ✅ |
| 코덱스 WHY | abstain ❌ | rank 3 | **rank 1** ✅ |
| 마우스 WHY | abstain ❌ | abstain ❌ | **rank 1** ✅ |

- WHY 2건(코덱스·마우스)을 **rank 1로 구제** — cur/imp150 모두 실패한 케이스까지 해결
- head 정답(gemini/codex) 보존 — win150의 구조적 약점 해결
- op paired: imphbn만 hit +3, cur만 hit -1 (gold50 기준선)
- noans paired: FP→abstain 11건, 오주입 5건

## ⚠️ 양면성 — op↔noans 뒤집힘

코덱스·마우스·pi 프록시는 **op 쿼리에서는 hit, noans 쿼리에서는 FP**로 뒤집힘
(같은 주제의 gold 유/무 쿼리가 셋에 공존). op에서 정답을 찾는 성질이 noans에서
오주입으로 이어짐 = JEV가 이 주제에 "답 존재"를 과신하는 경향. 3-run 확인 필요.

## 진행 이슈 기록

- stage47e 첫 실행(proc_083588855c5c)이 **조용히 kill**됨 (백그라운드 세션 출력
  버퍼만 있고 파일 리다이렉트가 없어 세션 정리 시 사라짐 — 원인은 게이트웨이 세션
  정리로 추정). **교훈: 장기 러너는 stdout을 파일로 리다이렉트하고 notify 패턴
  걸 것** (재실행은 stage47e_run.log로 정상 완료).
- 스모크 1쿼리 200 확인 후 전체 실행.

## 판정

- **imphbn이 지금까지 win150 계열 중 유일하게 전 지표 개선** — 채택 후보
- 단 1-run → **핵심 6쿼리 3-run majority 재검증 필요** (36콜):
  코덱스/마우스/gemini/codex/pi프록시(op) + gold50 기준선
- 채택 시 `j1_pipeline.py` excerpt 로직 교체 (러너 로컬 함수 → 운영 반영)

## raw

- `data/stage47e_head_overlap_non.json` (420 레코드)
- 러너: `stage47e_head_overlap_non.py`, 로그: `stage47e_run.log`