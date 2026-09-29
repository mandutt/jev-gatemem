# Release Notes — v0.1.0 (2026-09-29)

> **JEV-Mnemosyne Middleware** — Hermes 메모리 플러그인 첫 공개 릴리즈.
> 현재 Hermes 데스크톱에서 실사용 검증 완료된 시점을 스냅샷으로 고정.

---

## 주요 변경 사항 (Highlights)

- **J1 재순위화 파이프라인**: Mnemosyne 선형 recall → lane pool(FTS/vector/importance/graph) → JEV rerank.
  recall@1 0.500 → **0.712**, MRR 0.599 → **0.747** (baseline 대비).
- **쓰기 게이트 G-qual (user)**: 의미 없는 발화("좋아 진행해줘" 류) SKIP, 데이터 손실 0.
- **assistant 발화 저장 게이트 G-AS**: `[ASSISTANT]` 레코드 자동 저장 활성화
  (기존 Hermes 기본은 user 발화만 저장). gold50 precision 0.744 / recall 0.935 / F1 0.829.
- **Unconditional trace**: KEEP/SKIP 모든 판정을 `jev_trace.log`에 `write-gate` / `write-gate-as`로 기록.
- **실사용 검증 완료** (2026-09-29): G-AS 체크리스트 실측 통과,
  `[ASSISTANT]` 레코드 8건 저장, final 발화 KEEP / 중간 진행 SKIP 판정 정상.

## 아키텍처 변경

```
gateway/                  # Hermes 무관 — J1 pipeline, write gate, trace, gateway API
  j1_pipeline.py          # lane pool → gate → Jev rerank
  write_gate.py           # G-qual (user) / G-AS (assistant)
  trace.py                # ring buffer trace (512KB cap)
  gateway.py / types.py / excerpts.py
backends/mnemosyne.py     # Hermes 무관 — Mnemosyne backend 추상화
harnesses/                # Hermes 어댑터
  hermes_j1.py            # JevRerankProvider (MnemosyneMemoryProvider 상속, prefetch/sync_turn 오버라이드)
  jev_mem_plugin/         # Hermes plugin discovery 계약 (register_memory_provider)
  j1_access.py / wg_access.py  # 섀도잉 안전 accessor
```

- **핵심 로직은 Hermes와 독립** — 2026-09-29 독립화 로드맵 작성 (`docs/hermes-decoupling-roadmap.md`).
- **Hermes core / Mnemosyne core는 수정하지 않음** (플러그인 외부 코드 0 변경).

## ADR 영향

- 이 저장소에는 ADR이 없습니다 (grep `ADR` → 0건). 설계 결정은
  `HANDOFF_NEXT_SESSION.md` + `memory-classification-evaluation/*` 리포트에 기록.

## Known Limitations (검증된 사실)

| # | 한계 | 근거 |
|---|---|---|
| 1 | **개발 경로 하드코딩 4곳**: `gateway/write_gate.py:139`, `gateway/j1_pipeline.py:64`, `harnesses/wg_access.py:17`, `harnesses/smoke_write_gate.py:19` — `C:\Users\mandu\hermes-made\jev-memory-middleware` 문자열. 다른 머신/경로에서 개발 시 수정 필요 | `grep` 검증 (위 라인) |
| 2 | **타 에이전트 어댑터 없음** (opencode/Codex/pi) — 현재 Hermes 전용. | `harnesses/` 디렉터리 — hermes_j1.py만 존재 |
| 3 | **`_sync_roles` 기본값은 `{"user"}`** — assistant 저장은 `memory.mnemosyne.sync_roles`에 `assistant` 추가 시에만 동작 | `hermes_j1.py` 주석 + HANDOFF §8 |
| 4 | **JEV 호출은 TypeSafe 직접 API 필수** (`api.typesafe.ai/v1/systemone`) — 9router(localhost:20128) 경유 시 간헐적 400 | HANDOFF §8 G-AS 주의 |
| 5 | **`gateway` 패키지명 섀도잉**: Hermes 프로세스 내 `import gateway`는 hermes-agent의 gateway로 resolve → accessor 경유 필수 (bare import 금지) | `j1_access.py` docstring |
| 6 | **첫 릴리즈 = 태그 없음** — v0.1.0이 최초 | `git tag -l` → 0건 |
| 7 | **실사용 A/B 1차는 보류** — 12쿼리, 체감 차이 없음. 메모리 2,000+ rows 후 재평가 예정 | HANDOFF §2 상태표 |

## Future Work (Phase 5)

- **Hermes 종속성 독립화** (`docs/hermes-decoupling-roadmap.md`):
  P1 `core/j1_engine.py` 분리 → P3 opencode 어댑터 → P2 `gateway` rename (섀도잉 제거).
- 데이터 축적 후: 유형별 하이브리드 재검토, graph/fact lane 실데이터 재평가.
- Mnemosyne 업데이트 시: 한국어 어미 분류 패치 재적용 (`scripts/reapply_korean_classifier.py`).

## Verification

- **Smoke test**: `harnesses/smoke_write_gate.py` — **7/7 ALL PASS**
  (SKIP / KEEP / 킬스위치 / JEV 실패 fallback / G-AS SKIP / G-AS KEEP / sync_roles user-only)
- **실사용**: 2026-09-29 데스크톱 세션 — G-AS 체크리스트 §8.5 전 항목 실측 통과
- **Git**: working tree clean (커밋 `dbe7c01` 기준, 36커밋)

**Judgement: READY FOR RELEASE (Final)**