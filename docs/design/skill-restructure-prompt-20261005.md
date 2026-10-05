# 지시문: jev-memory-middleware 스킬 구조 정리 (새 세션용)

아래 내용을 새 세션에 붙여넣어 주세요.

---

## 목표

`jev-memory-middleware` 스킬의 SKILL.md 본문(99,814자, ~25K 토큰)을 "항상 로드되는 규칙" + "주제별 references/" 구조로 정리한다. 본문은 세션마다 전체가 컨텍스트에 상주하므로, 항상 필요한 운영 규칙(~200줄)만 남기고 실측 로그·이력성 내용은 references/로 이동한다.

## 배경

- 스킬: `jev-memory-middleware` (default 프로필, `C:\Users\mandu\AppData\Local\hermes\skills\jev-memory-middleware\`)
- 현재 문제: SKILL.md = 99,814자 → skill_manage write/patch가 100,000자 한도에 근접해 실패하는 상태. skill_view 시 전체가 컨텍스트에 상주해 로드 비용이 큼.
- lint 경고: `oversized-body` ("Keep the always-on rules here (~200 lines) and move topic depth into references/<topic>.md, linked from the body")
- 기존 references/: `external-fork-ab-comparison.md`, `recall-experiment-lessons.md`, `hippo-memory-comparison.md`, `evaluation-datasets.md`, `commitment-fp-filter.md` 등 (skill_view의 linked_files로 전체 확인)
- SoT repo: `C:\Users\mandu\hermes-made\jev-memory-middleware` (문서·실측 보고서가 이미 여기 있음 — 스킬은 그 문서들의 포인터 역할만 하면 됨)

## 작업 절차 (승인 게이트 포함)

### Phase 1 — 현황 파악 (변경 금지)
1. `skill_view(name='jev-memory-middleware')`로 현재 SKILL.md 전체와 linked_files 목록을 읽는다.
2. 본문의 각 `##` 섹션을 나열하고, 섹션별로 (a) 항상 필요한 운영 규칙 (b) 실측 로그·이력성 내용 (c) repo 문서로 이미 커버되는 내용 — 3분류를 만든다.
3. 이동 후보 크기 합계와 본문 잔여 예상 크기를 계산해 사용자에게 제시한다.

### Phase 2 — 계획 제출 후 승인 (변경 금지)
4. 다음을 포함한 리팩토링 계획을 사용자에게 제출한다:
   - 신규 references/ 파일 목록 + 각 파일에 들어갈 섹션/항목 목록
   - 본문에 남길 섹션 목록 (~200줄 목표)
   - SKILL.md 상단(또는 요약부)에 추가할 references 링크 인덱스
5. **사용자 승인 후에만 Phase 3 진행.**

### Phase 3 — 이동 실행
6. 신규 references/<topic>.md 파일을 `skill_manage(action='write_file', file_path='references/<topic>.md')`로 작성한다. 내용은 본문에서 **원문 이동**(축약·요약 금지 — '이동'이지 '삭제'가 아님. 실측 수치·날짜·판정·경고 문구는 그대로).
7. SKILL.md 본문에서 이동한 섹션을 제거하고 references 링크 인덱스를 추가한다 (`skill_manage(action='patch')`).
8. 같은 주제가 본문 여러 곳에 흩어져 있으면 이동 시 한 파일로 통합한다 (내용 손실 없이).

### Phase 4 — 검증
9. `skill_view`로 전체를 다시 로드해 오류·누락이 없는지 확인.
10. lint 경고 `oversized-body` 해소 + 본문 크기 < 100,000자 (목표 ~20KB) 확인.
11. 이동한 각 주제가 references/에서 검색(grep)으로 확인 가능한지 확인.
12. 사용자에게 변경 요약 보고 (신규 파일 목록, 본문 삭제 섹션, 최종 본문 크기).

## 제약

- **Hermes 코어/플러그인 코드 수정 금지** — 스킬 파일만.
- **SoT repo(`C:\Users\mandu\hermes-made\jev-memory-middleware`) 문서 수정 금지** — 스킬은 그 문서들의 포인터.
- **내용 손실 금지**: 이동이지 삭제가 아님. 실측 수치·날짜·판정 근거는 전부 유지.
- `mnemosyne-ops` 등 다른 스킬 수정 금지.
- **승인 전 변경 금지** (Phase 2 게이트). 사용자 원칙: 비가역/대규모 변경은 보고 먼저, 승인 후 실행.
- 이동이 아니라 **삭제가 필요한 항목**이 보이면 임의 삭제하지 말고 목록으로 보고만 한다.

## 완료 정의

- SKILL.md ≤ ~20KB, 본문은 항상 필요한 운영 규칙만.
- 모든 실측 로그·이력이 references/에서 찾을 수 있다.
- lint `oversized-body` 경고 해소.
- 사용자 승인 후 종료.

---