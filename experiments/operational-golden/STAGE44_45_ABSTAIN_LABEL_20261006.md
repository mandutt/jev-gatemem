# abstain 라벨 문구 실측 종합 — stage44~45 (2026-10-06, 스냅샷 기준)

> **상태: 판정 보류** — 채택/기각은 추후 다른 AI 검토 후 결정 (사용자 결정)
> 스냅샷: `snapshots/mnemosyne_snapshot_20261006.db` / noans: 50건 (hard 45 + fresh 5)

---

## 1. 실험 설계

- 대상: op 90 + noans 50 (스냅샷 기준), choice 1콜, pool 60, win-300 excerpt, soft gate τ=0.3
- 위치: cN (마지막 abstain 라벨 — stage44에서 위치 무효과 실측)
- 문구 조건:
  - **current** (현행): "No candidate is usable evidence for answering the question"
  - **improved** (세 AI 공통 제안): "No candidate contains the specific fact, value,
    version, or decision the question asks for — same-topic mention alone is not evidence"
  - **v3**: improved + explanation 포괄 수용
  - **v4**: improved + WHY/원인 질문 조건부 수용

## 2. 결과 요약

### stage44: 위치 × 지시문 2×2 (560콜, err 0)
| 조건 | hit@3 | abstain | noans FP |
|---|---|---|---|
| cN_current (현행) | 78 | 3 | 27 |
| c0_current | 78 | 3 | 25 |
| cN_slot | 77 | 3 | 25 |
| c0_slot | 78 | 3 | 26 |

→ **위치/지시문 무효과** (기각). abstain 결정은 라벨 위치와 무관.

### stage45: 문구 비교 (동일 세션 current vs improved, 280콜, err 0)
| 문구 | hit@1 | hit@3 | abstain | noans FP |
|---|---|---|---|---|
| **current** | 75 | **78** | 3 | 27 |
| **improved** | 73 | **76** | 5 | **22** |
| v3 (235콜) | — | 76 | — | 24 |
| v4 (140콜) | 73 | 76 | 6 | 23 |

- **improved**: noans FP **-5** (27→22), op hit@3 **-2** (78→76) → 건수 순 +3
  - op 손실 2건: "코덱스 앱이 PC 느려지게 한 원인?", "마우스 버벅임 원인 조사 결과?"
    — **원인(WHY) 질문**을 abstain으로 오판 (current에선 둘 다 hit)
  - noans 개선 5건: skip_shadow 누락?, consolidation 중복 버그?, 주석 영어 규칙?,
    테스트 생략 커밋 규칙?, 로그 한국어 규칙? — **시점/규칙 질문**을 정확히 차단
- **v3 (explanation 포함)**: noans 방어 약화 (24) + 코덱스 구제는 rank 4 (hit@3 아님) → 기각
- **v4 (WHY 조건부)**: abstain 6건 (오히려 증가), 코덱스 여전히 abstain → 기각
  - "explanation/cause" 문구 추가로도 JEV의 원인 질문 abstain을 바꾸지 못함 (구조적 한계)

## 3. "원인 질문 감지 예외" 검증 (0콜, 임베딩 분류)

- 설계: 쿼리 임베딩을 원인 질문 시드 10개 vs 사실/시점 질문 시드 10개 프로토타입과 비교,
  margin(cause_sim - fact_sim) > 임계값 → 원인 질문 → current 문구 사용
- **결과: 변별력 없음**
  - margin 양수(원인 분류)가 **124/140 (89%)** — 한국어 질문 임베딩의 공통 구조로 거의
    모든 질문이 원인 질문으로 분류됨
  - op 손실 2건 margin: **+0.036, +0.055** vs noans 개선 5건 margin: **+0.007~+0.051**
    → **분포 겹침, 임계값 분리 불가**
  - 시드 단어 방식은 "그 단어를 안 쓴 원인 질문"에 여전히 취약 (사용자 우려 확인)
- 더 정교한 분류(별도 모델/few-shot JEV)는 일반 LLM 금지 원칙 또는 콜 증가에 걸림
- **판정: 임베딩 원인 질문 감지 — 기각** (실측 변별력 부족)

## 4. 실험 품질 메모 (재현 시 주의)

- **JEV API env**: 실험은 반드시 EXPLABS_API_KEY가 SET된 터미널에서 실행 (execute_code
  셸은 env 없음 → `_jev_client`가 typesafe URL 폴백 → 401). 실행 전 `echo $EXPLABS_API_KEY` 확인.
- **503 재시도**: stage44의 current 46건 503 실패 → 이번 러너에 503 1회 재시도 추가.
  raw 신뢰도는 err=0 조건 전제.
- **러너 env 없이 execute_code에서 검증 시도 시 401 → 해당 결과는 폐기 (실험 데이터 아님)**.

## 5. 결정 대기 사항 (다른 AI 검토용)

1. **improved vs current trade-off**: noans -5 FP vs op -2 정답
   - 실 운영 무답 비율 u=22.5%에서 harm-가중 판정은? (op 손실 2건은 "답 있는 질문을
     빈 컨텍스트로" = 사용자 직접 피해 / noans FP 1건은 "무관 메모리 노출" = 오염 위험)
2. **원인 질문 오판의 근본 해법**: JEV가 WHY 질문에서 "specific fact" 문구 때문에
   abstain하는 구조 — 라벨 문구가 아닌 다른 해법(지시문 구조, 후처리)이 있는가?
3. 만약 improved 채택 시: op -2를 감수할지, 아니면 abstain_p soft gate τ 조정으로
   원인 질문 abstain을 줄일 여지가 있는지

## 6. 파일

- 러너: `stage44_abstain_pos_2x2.py`, `stage45_abstain_label_snapshot.py`
- raw: `data/stage44_abstain_pos_2x2.json`, `data/stage45_abstain_label_snapshot.json`
  (current+improved 최종), `data/stage45_v4_snapshot.json` (v4 단독)
- 로그: `data/stage45_run{1..5}.log` (run2의 current는 503 무효, run5가 최종 정상)
- 기준선: 스냅샷 noans FP 25~27 (stage44), 27 (stage45 current)