# JEV-Mnemosyne Middleware — Hermes 종속성 독립화 로드맵

> 작성: 2026-09-29 · 기준 커밋: `e1389b2`
> 목적: 이 플러그인의 **핵심 가치(J1 rerank, 쓰기 게이트 G-qual/G-AS)**를
> Hermes 뿐 아니라 **opencode / Codex / pi / 기타 에이전트**에서도
> 재사용 가능한 형태로 분리하는 로드맵.

---

## 1. 현황 요약 (2026-09-29 코드 기준)

| 레이어 | 파일 | Hermes 종속 |
|---|---|---|
| **J1 pipeline** (lane pool→gate→Jev rerank) | `gateway/j1_pipeline.py` | ❌ 없음 (Mnemosyne core만) |
| **쓰기 게이트** (G-qual / G-AS) | `gateway/write_gate.py` | ❌ 없음 (순수 Python + TypeSafe API) |
| **trace logger** | `gateway/trace.py` | ❌ 없음 |
| **gateway API** | `gateway/gateway.py`, `types.py`, `excerpts.py` | ❌ 없음 |
| **backend** | `backends/mnemosyne.py` | ❌ 없음 |
| **Hermes 어댑터** | `harnesses/hermes_j1.py` | 🔴 `mnemosyne_hermes.MnemosyneMemoryProvider` 상속 |
| **Hermes plugin wrapper** | `harnesses/jev_mem_plugin/__init__.py` | 🔴 `register_memory_provider(ctx)` 계약 |
| **섀도잉 accessor** | `harnesses/j1_access.py`, `wg_access.py` | 🟡 Hermes의 `gateway` 패키지 충돌 대응 + 하드코딩 경로 |

**결론: 핵심 로직은 이미 휴대 가능. "Hermes로 가는 입구" 2개(어댑터+wrapper)와
"섀도잉 방어" 1개(accessor)만 Hermes에 붙어 있음.**

---

## 2. 독립화 대상 (3곳)

### 2.1 `harnesses/hermes_j1.py` — 최우선 (난이도: 중)

현재 `class JevRerankProvider(MnemosyneMemoryProvider)` 로 Hermes base를 상속.
재사용하려면 **에이전트 불문 공통 코어**와 **Hermes 전용 어댑터**로 분리해야 함.

**분리 방안**:

```
gateway/                    # 이미 독립 (손댈 필요 없음)
  j1_pipeline.py
  write_gate.py
  trace.py
  gateway.py

core/                       # 신규 — 에이전트 불문 공통 로직
  __init__.py
  j1_engine.py        ← hermes_j1.py의 _prefetch_with_j1/recall_raw/_format_block
                       (beam 객체 + recall 콜백만 받으면 됨)
  write_gate_engine.py ← evaluate()/evaluate_assistant() (이미 독립, 재export)
  types.py            ← MemoryCandidate 등

adapters/                   # 신규 — 에이전트별 어댑터
  hermes/
    provider.py        ← JevRerankProvider (MnemosyneMemoryProvider 상속, 얇게)
    plugin.py          ← register_memory_provider(ctx)
  opencode/
    provider.py        ← opencode session-memory 플러그인 계약
  (pi/ codex/ ...)

harnesses/                  # (기존 유지) 기존 smoke/검증이 깨지지 않게
```

**핵심 원칙**:
- `j1_engine`은 **`beam`(Mnemosyne BeamMemory)과 `recall_*` 콜백만** 받는다.
  Hermes 관련 import **0개**. (Mnemosyne core는 이미 에이전트 불문)
- `_prefetch_with_j1`의 `_hydration_get`, `_typesafe_client`, `_format_block`은
  전부 core로 이동 (Hermes 무관).
- `hermes_j1.py`는 core를 import하는 **얇은 어댑터**로 축소
  (기존 smoke/검증 그대로 통과해야 함 — 회귀 금지).

### 2.2 `harnesses/jev_mem_plugin/__init__.py` — 낮음

`register_memory_provider(ctx)`는 Hermes plugin discovery 계약.
→ adapters/hermes/plugin.py로 이동, wrapper 본체는 `register` 함수만 남김.

### 2.3 `harnesses/j1_access.py` / `wg_access.py` — 낮음

Hermes 프로세스 안에서 hermes-agent의 `gateway` 패키지가 섀도잉하는 문제의
**우회책** (Hermes가 `gateway`라는 top-level 패키지를 가졌기 때문에 생긴 문제).
→ core 패키지명을 `gateway` → `jev_gateway`(또는 `jev_mw`)로 **이름 변경**하면
  섀도잉 자체가 사라져 accessor 불필요.

**단, 이건 영향 범위가 큼** (gateway import를 쓰는 모든 파일 + 실패 시 회귀).
→ **Phase 2에서 별도 결정**. 당장은 accessor 유지.

---

## 3. 단계별 실행 계획

| Phase | 내용 | 산출물 | 게이트 |
|---|---|---|---|
| **P0 (현재)** | 핵심 로직 독립 확인 (완료) | — | — |
| **P1** | `core/` 신설 + `j1_engine` 분리. `hermes_j1.py`는 얇은 어댑터로 | `core/j1_engine.py` | 기존 smoke 7/7 + verify_* 전부 PASS |
| **P2** | 패키지명 정리 (`gateway` → `jev_gateway`) — 섀도잉 accessor 제거 | rename + accessor 삭제 | Hermes 런타임 실사용 확인 |
| **P3** | `adapters/opencode/` 첫 타 에이전트 어댑터 (session-memory 플러그인 계약) | `adapters/opencode/provider.py` | opencode에서 J1 prefetch + write gate 동작 |
| **P4** | 문서/스킬 갱신 (설치법, 계약 문서) | `docs/adapters.md` | — |

**우선순위**: P1 (공통 코어 분리) → P3 (타 에이전트 실증) → P2 (섀도잉 제거) → P4.

> P2는 게이트 통과 후에만: Hermes 런타임에서 `Jev choice` 라인 재실측으로
> 회귀 없음을 확인한 뒤 진행.

---

## 4. 타 에이전트 연결 시 필요한 것 (체크리스트)

타 에이전트 어댑터가 만족해야 할 최소 계약:

```python
# adapters/<agent>/provider.py
class JevMemoryAdapter:
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """J1 pipeline 결과를 '## Mnemosyne Context' 블록으로 반환"""
        # core.j1_engine.run(beam, query, recall_cb) 사용

    def sync_turn(self, user_content: str, assistant_content: str, *,
                  session_id: str = "", messages=None) -> None:
        """G-qual / G-AS 게이트 적용 후 Mnemosyne에 저장"""
        # core.write_gate.evaluate() / evaluate_assistant() 사용
        # 4-way 분기 (both KEEP / user SKIP / asst SKIP / both SKIP)
```

- **저장 포맷**: `[USER]` / `[ASSISTANT]` prefix는 이미 에이전트 불문 (역할 구분용)
- **필요 env**: `TYPESAFE_API_KEY` (Jev API), `MNEMOSYNE_*` (Mnemosyne 설정)
- **Mnemosyne DB**: 에이전트별 session_id를 `hermes_<sid>` 대신
  `<agent>_<sid>`로 구분만 바꾸면 됨 (이미 `_provider_session_id()`에서 처리)

---

## 5. 위험 / 주의

| 리스크 | 대응 |
|---|---|
| `core/` 분리 시 `hermes_j1.py` 회귀 | 게이트: 기존 smoke + verify_* 전부 PASS 후 커밋 |
| `gateway` rename이 크면 실패 시 롤백 복잡 | P2는 별도 승인 + 롤백 계획 포함 |
| 타 에이전트마다 Mnemosyne 접근 방식 상이 | 어댑터 계약을 최소화 (beam + 콜백만) |
| Hermes 업데이트로 base provider 시그니처 변경 | 어댑터에서만 대응 (core는 불변) |

---

## 6. 참고

- 현재 Hermes base: `MnemosyneMemoryProvider(HermesPersonaPromptMixin, MemoryProvider)`
  (v0.7.0, `mnemosyne_hermes`)
- Hermes MemoryProvider 추상 계약: `prefetch()`, `sync_turn()`, `name`, `initialize()` 등
- 실측: Hermes 런타임 venv에서 `mnemosyne_hermes/__init__.py` 확인됨