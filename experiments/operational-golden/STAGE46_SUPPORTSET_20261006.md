# pool 밖 miss 11건 support_set 재감사 — stage46 (2026-10-06)

## 배경
C AI Q5 제안: pool 밖 miss를 제외하지 말고, ①직접 답 ②동등 support ③코퍼스 답 존재
④문맥 의존 4분류로 재감사. 결과가 retrieval 문제인지 라벨 문제인지 확정이 목적.

## 판정 (사용자 + 제 이중 검토)

### 결과: 11건 전부 q1=direct, q3=exists (진짜 retrieval miss)

| # | 쿼리 | 직접 답 근거 (gold 내용 요지) | q4 |
|---|---|---|---|
| 1 | camelAI 어려운 과제는 어떤 모델로? | gemini-3.7-flash 17/18(94%) 명시 | indep |
| 2 | 92번 호출 라우팅 결과? | 동일 gold (92호출 실측) | indep |
| 3 | 리뷰 전용 턴에서 커밋해도 돼? | "review/fix-only turns NEVER git add/commit (literal)" | indep |
| 4 | 구현 믿기 전에 뭘 확인해? | "Verify 'implemented' read-only before trusting" | indep |
| 5 | evidence 규칙 어땠지? | "Evidence-based only; no speculation" | indep |
| 6 | shutdown API 어떻게 만들었지? | /api/shutdown 종료버튼 구현 내역 | indep |
| 7 | provider가 뭐지? | "메모리 provider=mnemosyne" | indep |
| 8 | TimeoutExpired 처리 어떻게 바뀌지? | "TimeoutExpired 흡수 + phase별 budget" | indep |
| 9 | Exa 왜 안 써? | "Exa 키리스는 한글 mojibake → tavily 권장" | indep |
| 10 | 18080 프록시가 뭐 하는 거야? | "camelai-serial-proxy(127.0.0.1:18080)" 설명 | indep |
| 11 | 전환 전 어떤 문제 있었지? | supermemory 0-byte 유실(전환 사유) | **dependent** |

### 조정 (제 검토 반영)
- **[11]만 q4=dependent** — "전환"이 supermemory→mnemosyne 전환을 가리킨다는 사전
  지식 없이는 해석 불가 (B AI 지적 케이스 그대로). 별도 버킷.
- [3][5] 첫 어휘 매치 0%였으나 gold 원문이 정확한 직접 답임 확인 → direct 유지.

### 판정
- **10건**: 진짜 retrieval miss (코퍼스에 답 존재, pool 60에 미진입)
- **1건 ([11])**: 문맥 의존 버킷 → prefetch 쿼리에 최근 턴 키워드 결합이 해법 (B AI Q5)
- **support_set 재정의 필요 없음**: q2=yes는 [1]뿐 (pool 후보에 동등 답 존재—
  단, [1]의 동등 답도 pool 60 안에 있었지만 JEV가 선택 안 한 rerank 문제일 가능성,
  별도 확인 필요). 나머지 10건 gold 유일.

## 시사점 (next: A Q5)

- **retrieval miss 10건**은 rerank가 아니라 **lane 검색 문제**:
  - [7][9]처럼 단순·직접 질문도 pool 밖인 건 vec/FTS lane의 키워드·의역 한계
  - gold 생성일이 오래됨(07-31~08-25) — 최근 메모리 편향 가능성도 1차 원인 후보
- **해법 후보 (A Q5)**: write-path 태그 보강 (저장 시 직전 대화 주제 키워드→FTS 인덱스)
  → "super memory → 전환, 마이그레이션" 같은 상위 맥락 태그로 lane 진입
- **[11] 해법**: prefetch 쿼리 구성 시 최근 턴 키워드 결합 (문맥 의존 버킷)

## 파일
- 리뷰 시트: `stage46_supportset_review.html` (모바일 대응 v2)
- 판정 raw: (사용자 JSON — 커밋 포함)
- 이 문서: `STAGE46_SUPPORTSET_20261006.md`