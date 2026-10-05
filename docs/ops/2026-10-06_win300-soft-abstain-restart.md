# 운영 데몬 재시작 기록 — win-300 + soft abstain gate 반영

- **날짜/시각**: 2026-10-06 00:30~00:32 (KST)
- **커밋**: (커밋 후 기입 — `gateway/j1_pipeline.py` win-300 전면 + abstain_p soft gate)
- **실측 근거**: STAGE25_PROBABILITY_20261006.md + stage26/27
  - op hit@3 72→77(+5), hit@5 74→80, abstain 9→3
  - noans: hard 22→16 FP (τ=0.3), **독립 easy 셋 0 FP**
  - JEV 콜 1콜/쿼리 유지, 일반 LLM 미사용

## 변경 내용 (gateway/j1_pipeline.py)

1. `_SOFT_ABSTAIN_TAU = 0.3` (env `JEV_SOFT_ABSTAIN_TAU` 오버라이드)
2. `_jev_choice`: `probabilities`/`confidence` 파싱 → `(idx, abstain_p, probs)` 반환 (기존 파기)
3. `jev_rerank`: excerpt 전면 "쿼리 윈도우 300자"(800자 분기 제거) + `abstain_p > 0.3`이면 빈 컨텍스트 + trace에 `abstain_p` 로깅
4. `build_state`: state excerpt도 300자 윈도우로 통일

## 수행 절차

1. 프로세스 스냅샷: pythonw 15692, 29560 (데몬 트리)
2. 정지: `tools/stop_jev_daemon.ps1` → TREE_STOPPED, 잔여 0
3. 재스폰: `pythonw.exe -m jev_mem_core --serve` (백그라운드)
4. 검증:
   - `/v1/health` → `{"status": "ready", "version": "0.2.0"}` (47821)
   - trace 로그에 `abstain_p` 필드 출현 = 새 코드 반영 확인
   - S8 쿼리: `idx=6 abstain_p=0.02` → gold pick (정상 lift)
   - noans 쿼리: `idx=25 abstain_p=0.57` → `abstain` 이벤트 (soft gate 발동, 빈 컨텍스트)

## 반영 확인

- trace `jev` 라인 `abstain_p=` 필드 존재 (구코드엔 없던 필드)
- soft gate: abstain_p>0.3 → abstain 이벤트 발생 (noans 방어)

## 관찰 계획

- shadow 배치(`query_log`/`shadow_log`)로 prefetch 품질 변화 추적
- 경고선: noans 오주입 증가 / op-90 지표 회귀 시 롤백
- 롤백 포인트: 이 커밋 revert

## 관련 파일

- `STAGE25_PROBABILITY_20261006.md` (probability 분석)
- raw: `data/stage25_choice_probability.json`, `data/stage26_win300_final.json`, `data/stage27_easy_noans_verify.json`
- 러너: `stage25_choice_probability.py`, `stage26_win300_final.py`, `stage27_easy_noans_verify.py`, `stage28_smoke_live.py`