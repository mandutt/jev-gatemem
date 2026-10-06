# STAGE59 — read-path meta 라벨 실험 (2026-10-06, 120콜, err 0) — **무력·기각**

> 배경: stage58이 "규칙/프로필 행 클러스터"가 라이브 무답의 공급원임을 실측.
> 대안: choice criteria 라벨에 행 출처(meta) 접두 `[USER-RULE|사용자 규칙·선호 메모리]`를 붙여
> JEV가 "규칙 질문일 때만" 해당 행을 정답으로 인식하도록 유도.

## 설계

- 셋: 라이브 60 (49c human verdicts: block 38 / valid 5 / yes 17)
- 조건: base(현행 excerpt) vs meta(규칙 클러스터 6개 행 id에 meta 접두) — 같은 세션 paired
- 규칙 클러스터 id: stage58의 6개 (허브 d1c90516 + 사용자 제약/ADR/설계 리뷰/감사 형식/아키텍처)
- 콜: 120 (60×2), err 0

## 결과

| | block abstain | valid+yes 오차단 | err |
|---|---|---|---|
| base | 0/38 | 0/22 | 0 |
| meta | **0/38** | 0/22 | 0 |

- **choice_idx 변경: 1건뿐** (`리뷰 전용 턴에서 커밋해도 돼?` 2→12 — block이라 무해)
- abstain 0 유지, block 38 전부 계속 pick

## 판정 — **meta 라벨 무력·기각**

1. **meta 접두가 JEV의 선택에 사실상 영향 없음** (60건 중 1건만 idx 변경, abstain 변화 0).
2. 이유 (추론): abstain 무력의 근본 원인은 "라벨 내용"이 아니라
   **choice가 항상 최선 후보를 고르는 구조** — 라벨에 출처를 붙여도 후보 간 상대 비교만 강화될 뿐,
   "전부 부적격" 판정 신호(abstain)로는 이어지지 않음. stage44(위치)→45(문구)→50b(프롬프트)와 동일한 벽.
3. 기존 12종 레버 + meta 라벨 = **13번째 레버 소진** — read-path 라벨 조작은 전부 무력 확정.

## 결론

- **라이브 IRREL 차단은 read-path 라벨로 불가** — "JEV 단독으로는 미해결" 결론 재확인.
- 남은 유일 실측된 개선 경로: **A AI의 노출 축소(k=2~3)** + **B/C의 소비 측 프레이밍**
  (메모리 경로 밖 — Hermes가 무시하도록).
- KPI 기록: 이번 실험으로 "규칙 행이 pool에 있는 쿼리" 60/60 — 클러스터 행이 전 쿼리에 노출됨 재확인.

## raw

- `data/stage59_meta_labels.json` (base/meta × 60)
- 러너: `stage59_meta_labels.py` (<- stage48 러너 구조 재사용)
- 로그: `data/stage59_run.log`