# agentmemory 보류 4건 — 0콜 실측 결과 (2026-10-09)

- 러너: `experiments/operational-golden/am_hold_4probe.py` (+ `am_trace_pool_queries.json`)
- raw: `experiments/operational-golden/data/am_hold_4probe.json`
- 방식: 0콜 — 라이브 DB(read-only)·기존 raw(stage87/stage50c)·trace 10-09 재계산
- 판정 요약: **① 기각(선행 실측 이미 완료) · ② 3쌍 전부 작업 지시 반복 → 채택 근거 부재 · ③ evictable 0건 → 시기상조 · ④ 작업 지시 pool 진입 실측 완료 → slots 후보 유지**

---

## ① `_adjusted` 강등 방지 후처리 — 기각 (선행 실측이 이미 판정 완료)

- **선행 0콜 시뮬레이션(stage79)**: 게이트 통과 90쿼리에서 현행 adjusted 재정렬은 gold rank1을 **10/90**만 노출, **RRF 순서 보존(A) 44/90**(4.4배) — '재정렬이 RRF 순위를 파괴한다'(exp8a [59][71] 1→8·1→9)의 전체 유병률 시뮬.
- **그러나 JEV 콜 실측(stage80~82)에서 A/B 모두 기각**:
  - A(RRF 보존, stage80 90콜): hit@1 78/90 (현행 79) — **동률 미달**. 시뮬의 'rank1 44건' 예측은 +4/−5 flip으로 상쇄 (JEV는 rank1만 보지 않고 excerpt 전체에서 gold를 집어냄).
  - B(평균 순위, stage81 90콜 + stage82 3셋 110콜): op hit@1 79 동률·hit@3 81(+1)·abstain 1(−2) **vs noans FP 20~23→25(+2~5)** — **순손실 확정**.
- 추가 실측(stage87, raw 재계산): op 90 gold_rank≥8이 54/86 — 'gold가 top-7 밖'은 흔하지만(86/90이 rank≤14, max 41), 이는 **게이트/RRF/재정렬 누적 결과**이고, JEV choice가 excerpt로 gold를 lift하므로(현행 hit@1 78) '강등 유병률 자체'는 더 이상 문제가 아님. 유병률 63%(54/86)는 노출이 아니라 **choice 재료**로 작동 중.
- **판정: 기각 — 'do not re-run' 범위 (stage82 3셋 회귀) 확정. agentmemory 보류 ① 닫음.**

## ② 자동 supersede(Jaccard>0.9) — 3쌍 전부 버전 충돌 아님 → 채택 근거 부재

- 최근 300 active 행 Jaccard>0.9: **3쌍** — 전부 같은 세션/이벤트의 재전송(다시 보여드립니다·다시 보내드립니다·진행해보자)이지 '같은 사실의 새 버전' 아님.
- 정확 중복 32그룹/100행: **작업 지시·벤치 태스크(USER) 64행 + 단문 동의(좋아/그래) 15행 + 기타 21행(조사/작성 지시)** — mem0 프로브 결론 재확인: '같은 사실의 버전 충돌'이 아니라 **벤치/작업 지시 반복**.
- superseded_by 113행·valid_until 159행은 이미 write-time 경로로 작동 중.
- **판정: 채택 근거 부재(유병률 0에 수렴) → 보류 유지가 아니라 '기각 방향 확정'** — 단, G-qual이 '모순/대체 관계'를 아예 보지 못하는 구조적 갭(corrected_by 0건)은 그대로 남으므로 **'모순 유병률' 자체의 사람 라벨링**만 남은 미실측. Jaccard>0.9 자동supersede 도입은 불필요.

## ③ retention 점수 + 액세스 로그 — evictable 0건 → 시기상조

- λ=0.01/σ=0.3 (agentmemory 기본값) 0콜 시뮬: **evictable(<0.15) 0건** — 우리 코퍼스의 importance 양극화(0.15×728 / 0.5×1127) + 메모리 연령 분포 때문에 Ebbinghaus가 cold 미만으로 떨어뜨리는 행이 없다.
- λ 상향(0.05/0.1/0.3)도 전부 evictable 0건 (warm→cold 이동만, 15% 언더 행 0).
- tier 분포(기본값): hot 37 / warm 1517 / cold 372 — **tier는 생성되지만 eviction 임계는 코퍼스 한계**.
- **판정: 보류 유지 → '코퍼스 성장 시 재검토'로 완화** (수만 행 + 중요도 분포 다변화 전제). 액세스 로그(recall_count/last_recalled)는 우리 DB에 **이미 존재** — agentmemory의 '액세스 강화' 축만 미사용. recall_count 분포 확인(추가 실측 가능) 후에도 레버가 될 지표는 아님.

## ④ 작업 지시형 pool 진입율 — 15/113(13.3%) + abstain 과다거부 패턴 → slots 후보 강화

- 10-09 trace `|pool|` 113 이벤트(전체 쿼리 `am_trace_pool_queries.json`):
  - **작업 지시형 15건(13.3%)**: '저장해둬·테스트해보자·정리해줘·진행해줘·확인해줘·알려줘·보고해줘' — stage96 'abstain 91% = 작업 지시 오판'의 기저율 확인. **canary 12건 중 무답 6건(복권/맛집/비밀번호/설명/우주/어제날씨)도 작업 지시로 오인 가능한 명령형 어미('알려줘·추천해줘·말해줘')를 씀** — canary L1 쿼리 레이블링 시 이 패턴 주의.
  - 시스템/[IMPORTANT]·짧은 단어(단일 토큰) 다수 포함.
- 작업 지시형이 풀 진입 + JEV choice에서 abstain/오주입되는 구조는 재확인 — **pinned slots(전용 저장소)이 이 13.3%를 일반 사실 풀에서 분리하는 유일한 구조적 해법**.
- **판정: 보류 유지 (사용자 승인 영역 — 소비 측 주입). 실측 근거 보강됨.**

---

## 결론

| 항목 | 실측 결과 | 판정 |
|---|---|---|
| ① `_adjusted` 후처리 | stage79~82 선행 실측 A/B 기각 + gold_rank≥8 54/86는 choice 재료로 작동 | **기각 확정 (do not re-run)** |
| ② 자동 supersede | Jaccard>0.9 3쌍·정확중복 100행 전부 작업 지시/재전송 | **기각 방향 (모순 유병률 라벨링만 잔여)** |
| ③ retention | evictable 0건 (λ 0.01~0.3 전부) | **보류 완화 — 코퍼스 성장 시 재검토** |
| ④ pinned slots | 작업 지시 13.3% 풀 진입 + canary 명령형 어미 오인 패턴 | **보류 유지 — 유효 후보 (승인 영역)** |

- 코드 변경 없음 (0콜 실측). HANDOFF 외부 비교 표의 agentmemory 행을 이 결과로 갱신 예정.