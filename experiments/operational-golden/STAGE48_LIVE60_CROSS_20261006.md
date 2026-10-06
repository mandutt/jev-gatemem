# stage48: 라이브 60쿼리 교차 검증 — abstain 무력 발견 (2026-10-06)

라이브 trace에서 수집한 실사용 쿼리 60건(사용자 판정 포함)을 스냅샷에서 재실측해
교차표 확보. 목적: u_true·실제 FP율·abstain 동작 검증.

## 실행 이력 (버그 3건 수정)

1. **게이트 기본값 버그**: `_filter_and_rank` 기본값 (2, 0.30)이 gateway/러너 경로에
   남아있어 짧은 쿼리 pool 0~5 → abstain 93%. core는 완화(1, 0.0)였으나 gateway 미반영.
   **기본값을 (1, 0.0)으로 통일** (commit 예정).
2. **trace 재수집 버그**: load_queries가 실행 시점 trace에서 쿼리를 재수집 → 실험 쿼리가
   섞여 60건 선택이 달라짐. **시트 쿼리 하드코딩으로 고정**.
3. **row_factory 누락 버그**: 러너 `sqlite3.connect` 후 row_factory 미설정 → FTS 결과가
   tuple이라 pool 2~9. **row_factory=Row 추가로 pool 60 복원**.

## 최종 결과 (시트 60건 고정, row_factory 수정, 게이트 완화)

| cond | pick | abstain | err |
|---|---|---|---|
| cur | **59/60** | 0/60 | 1 |
| imp | 59/60 | 1/60 | 0 |

## 사용자 판정 교차 (cur)

| | pick | abstain |
|---|---|---|
| 답 있음 (35) | 35 | 0 |
| 답 없음 (22) | **22** | **0** |
| maybe (3) | - | - |

- **recall (답 있음 노출) = 100%** (35/35)
- **noans FP율 = 100%** (22/22 전부 오주입)
- **abstain 0건 — abstain 라벨이 라이브에서 완전 무력**
- abstain_p 분포: min 0.00, median 0.00, max 0.16 — **JEV가 모든 라이브 쿼리에
  abstain 확률 ~0 부여**

## 해석 — 심각한 발견

- **op-90 골든셋에서는 abstain이 작동** (hit@3 78, abstain 3)했으나, **실제 라이브
  쿼리에서는 abstain이 전혀 작동하지 않음** (0/60).
- 이유: 라이브 사용자 질문은 대부분 "유사 메모리가 존재" → JEV가 항상 뭔가를 고름.
  사용자가 "답 없음"이라 한 22건도 **유사 메모리를 답으로 오인** (JEV는 답이
  "없다"를 거의 선택 안 함).
- **즉 현재 abstain 라벨은 골든셋 하드 noans에서만 유효하고, 실무답 질문(유사
  이웃 존재)에서는 무력** — noans 방어가 실제 운영에서 거의 0%라는 뜻.
- improved 라벨도 abstain 1/60뿐 — 라벨 문구 변경으로는 해결 안 됨.

## 결론

1. **회수(recall)는 100%로 우수** — 답 있는 질문은 전부 노출.
2. **noans 방어는 사실상 0** — 실무답 질문 22건 전부 오주입. 이건 사안 1(improved
   라벨)보다 근본적: abstain 메커니즘 자체가 라이브에서 무력.
3. 다음 단계 후보: ① soft gate τ 재검토(abstain_p가 0이면 무의미) ② abstain 라벨
   프롬프트 재설계(라이브 질문에서도 abstain 선택 유도) ③ noans FP를 실측 데이터로
   수용. **u_true=38.6% 실측과 합치면, 라이브 트래픽의 ~39%에서 오주입이 발생 중.**

## raw

- `data/stage48_live60_cross.json` (최종, 120 레코드)
- 러너: `stage48_live60_cross.py` (시트 쿼리 하드코딩, row_factory 포함)
- 시트: `live60_label_review.html`
- 사용자 판정: 위 JSON (1~60)

## 후속 검증 (2026-10-06, stage49a/b) — 본 실측의 유효성 확정

3종 AI 검토에서 B AI가 본 리플레이의 측정 오염(자기참조 누수·win-300 증폭)을 의심 →
0콜 진단 + 시점 일관 3조건×3-run(540콜)으로 **모두 기각, 본 결론(abstain 무력) 최종 확정**.
상세: `STAGE49A_LEAK_DIAGNOSIS_20261006.md`, `STAGE49B_TIMECONSIST_20261006.md`,
종합: `RECALL_ABSTAIN_INVESTIGATION_20261005.md` §11.