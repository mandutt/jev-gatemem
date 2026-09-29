# P1 설계 — `core/j1_engine.py` 분리 (Hermes 종속성 독립화)

> 상태: **설계 대기 (승인 전 코드 작성 금지)** · 2026-09-29
> 기준: v0.1.0 릴리즈 (`1d3b505`) 이후

---

## 1. Scope (범위)

`harnesses/hermes_j1.py`의 **모듈 레벨 순수 함수 5개**를
`core/j1_engine.py`(신규)로 이동:

| 현재 위치 | 함수 | 역할 |
|---|---|---|
| `hermes_j1.py:195` | `_jev_on()` | JEV 킬스위치 확인 |
| `hermes_j1.py:199` | `_hydration_get(beam, memory_id)` | cross-session hydration |
| `hermes_j1.py:236` | `_prefetch_with_j1(provider, beam, query, session_id)` | J1 pipeline 실행 + 포맷 |
| `hermes_j1.py:288` | `_typesafe_client()` | TypeSafe httpx client |
| `hermes_j1.py:307` | `_format_block(rows, query)` | `## Mnemosyne Context` 블록 포맷 |

**분리 후 `hermes_j1.py`는**:
- `class JevRerankProvider(MnemosyneMemoryProvider)` (Hermes 상속) — 유지
- `prefetch()` → `core.j1_engine.run()` 호출 (얇은 어댑터)
- `sync_turn()` → `core.write_gate_engine` 호출 (이미 gateway.write_gate가 독립)

**범위 밖 (하지 않음)**:
- `gateway/` 패키지 rename ❌ (P2)
- opencode 어댑터 ❌ (P3)
- `j1_access.py` / `wg_access.py` 제거 ❌ (P2)
- `sync_turn`의 4-way 분기 로직 이동 ❌ (Hermes base API 의존 — 어댑터에 남김)

---

## 2. DoD (Definition of Done)

- [ ] `core/__init__.py`, `core/j1_engine.py` 생성
- [ ] `hermes_j1.py`에서 모듈 레벨 함수 5개 제거, `core.j1_engine` import로 대체
- [ ] `hermes_j1.py`에 **Hermes import 이외의 순수 로직 0** (모듈 레벨 기준)
- [ ] smoke test 7/7 PASS (Hermes 런타임 venv)
- [ ] 회귀 검증: `verify_*.py` 기존 산출물 재실행 가능
- [ ] 커밋 완료

---

## 3. Public API (core/j1_engine.py)

```python
# core/j1_engine.py — Hermes 무관. Mnemosyne core만 import.

def run(
    beam,                          # Mnemosyne BeamMemory instance
    query: str,
    *,
    client=None,                   # httpx client (None → Jev skip)
    session_id: str = "",
    top_k: int = 5,
    timeout: float = 5.0,
) -> str:
    """J1 pipeline 실행 → '## Mnemosyne Context' 블록 문자열.

    Hermes 무관: beam + recall 콜백만 받음.
    실패 시 빈 문자열 (fallback은 호출자가 처리).
    """

def hydration_get(beam, memory_id: str) -> Optional[dict]:
    """Cross-session hydration (working → episodic, session 필터 없음)."""

def typesafe_client() -> Optional[httpx.Client]:
    """TypeSafe System One client; TYPESAFE_API_KEY 없으면 None."""

def format_block(rows: List[dict], query: str) -> str:
    """'## Mnemosyne Context' 블록 포맷 (Mnemosyne base와 동일)."""

def j1_on() -> bool:
    """JEV_RERANK 킬스위치 확인 (gateway.j1_pipeline.jev_enabled와 동일)."""
```

**주의**: `_prefetch_with_j1`의 어댑터 의존(provider) 제거 — `run()`은
`beam`과 `client`만 받고, `session_id`는 trace용으로만 사용.

---

## 4. 구현 순서

1. `core/__init__.py` + `core/j1_engine.py` 신설 (5개 함수 이동, import 정리)
2. `harnesses/hermes_j1.py` — import 대체 + `prefetch()`가 `run()` 호출하도록 수정
   (provider 인자 제거, beam/client 전달)
3. scramble 검증:
   - smoke 7/7 PASS
   - `hermes_j1.py`에서 Hermes import 이외 순수 로직 0 확인 (grep)
4. 커밋

---

## 5. 리스크 / 롤백

| 리스크 | 대응 |
|---|---|
| `run()` 시그니처 변경으로 prefetch 회귀 | smoke + 실사용 1턴 확인 |
| `_format_block` 포맷 불일치 (모델 프롬프트 파싱 깨짐) | 기존 `## Mnemosyne Context` 출력과 byte 비교 |
| import 순환 (core↔gateway) | core는 **gateway만** import (역방향 금지) |

**롤백**: v0.1.0 태그로 `git checkout` 가능 (릴리즈 스냅샷 확보됨).

---

## 6. 승인 필요

- [ ] **Scope** — 위 범위로 진행 OK?
- [ ] **Public API** — `run()` 시그니처 (beam+client) OK?
- [ ] **구현 순서** — 1→2→3→4 OK?