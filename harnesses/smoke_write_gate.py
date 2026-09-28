"""통합 검증: JevRerankProvider.sync_turn 게이트가 실제 저장 흐름을 막는지.

mock beam + 실 JEV API로:
  1. SKIP 발화 (좋아 진행해줘) -> user 미저장 + assistant 저장
  2. KEEP 발화 (내일까지 보고서) -> user+assistant 모두 저장
  3. 킬스위치 JEV_WRITE_GATE=0 -> base 경로 (모두 저장)
  4. JEV 실패 (잘못된 키) -> KEEP (base 저장, 누락 방지)

실행: Hermes venv python으로 실행 (mnemosyne 의존).
예: ".../venv/Scripts/python.exe" harnesses/smoke_write_gate.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harnesses.hermes_j1 import JevRerankProvider

# ---------------------------------------------------------------------------
# mock beams: 기록용 remember / capture
# ---------------------------------------------------------------------------
def _make_beam(name: str):
    class _Beam:
        session_id = "smoke-session"
        channel_id = "smoke-session"

        def __init__(self, name):
            self.name = name
            self.remembered = []

        def remember(self, **kw):
            self.remembered.append(kw)

        def __repr__(self):
            return f"<Beam {self.name}>"

    return _Beam(name)


def _make_provider(mock_beam, sync_roles=("user", "assistant")):
    p = JevRerankProvider.__new__(JevRerankProvider)
    p._beam = mock_beam
    p._agent_context = "chat"
    p._skip_contexts = {"cron", "flush", "subagent", "background", "skill_loop"}
    p._sync_roles = set(sync_roles)
    p._default_scope = "global"
    p._verbatim_ledger = None  # no ledger in smoke
    p._active_session_id = ""
    p._turn_count = 0
    p._maybe_retry_init = lambda: None
    p._should_filter = lambda content: False
    return p


def _run(provider, user, assistant, session_id="smoke-session"):
    # monkeypatch _beam_session_scope to a contextmanager yielding the mock beam
    from contextlib import contextmanager

    @contextmanager
    def _scope(_sid):
        yield provider._beam

    provider._beam_session_scope = _scope
    provider.sync_turn(user, assistant, session_id=session_id)


def main() -> int:
    failures = []

    # -- 1. SKIP 발화 --------------------------------------------------------
    beam = _make_beam("skip")
    p = _make_provider(beam)
    _run(p, "좋아 진행해줘", "네, 바로 진행하도록 하겠습니다. 구체적인 내용을 알려주시면 처리해드릴게요.")
    user_saved = [r for r in beam.remembered if "[USER]" in r.get("content", "")]
    asst_saved = [r for r in beam.remembered if "[ASSISTANT]" in r.get("content", "")]
    ok1 = len(user_saved) == 0 and len(asst_saved) == 1
    print(f"[1] SKIP 발화: user_saved={len(user_saved)} asst_saved={len(asst_saved)} -> {'PASS' if ok1 else 'FAIL'}")
    if not ok1:
        failures.append("1: SKIP 발화 시 user가 저장됨")

    # -- 2. KEEP 발화 --------------------------------------------------------
    beam = _make_beam("keep")
    p = _make_provider(beam)
    _run(p, "내일까지 보고서 제출해야 해", "알겠습니다, 내일까지 보고서 제출하도록 하겠습니다.")
    user_saved = [r for r in beam.remembered if "[USER]" in r.get("content", "")]
    asst_saved = [r for r in beam.remembered if "[ASSISTANT]" in r.get("content", "")]
    ok2 = len(user_saved) == 1 and len(asst_saved) == 1
    print(f"[2] KEEP 발화: user_saved={len(user_saved)} asst_saved={len(asst_saved)} -> {'PASS' if ok2 else 'FAIL'}")
    if not ok2:
        failures.append("2: KEEP 발화 시 저장 누락")

    # -- 3. 킬스위치 ----------------------------------------------------------
    os.environ["JEV_WRITE_GATE"] = "0"
    try:
        beam = _make_beam("kill")
        p = _make_provider(beam)
        _run(p, "안녕하세요 반갑습니다", "안녕하세요, 무엇을 도와드릴까요? 저는 당신의 비서 역할을 하고 있습니다.")
        user_saved = [r for r in beam.remembered if "[USER]" in r.get("content", "")]
        asst_saved = [r for r in beam.remembered if "[ASSISTANT]" in r.get("content", "")]
        ok3 = len(user_saved) == 1 and len(asst_saved) == 1
        print(f"[3] 킬스위치: user_saved={len(user_saved)} asst_saved={len(asst_saved)} -> {'PASS' if ok3 else 'FAIL'}")
        if not ok3:
            failures.append("3: 킬스위치 시 base 저장 실패")
    finally:
        os.environ.pop("JEV_WRITE_GATE", None)

    # -- 4. JEV 실패 (no key) -> KEEP -----------------------------------------
    saved_key = os.environ.pop("TYPESAFE_API_KEY", None)
    try:
        beam = _make_beam("nokey")
        p = _make_provider(beam)
        _run(p, "이건 저장될까", "네, 이 내용은 저장되어 다음에 참고할 수 있도록 처리해두었습니다.")
        user_saved = [r for r in beam.remembered if "[USER]" in r.get("content", "")]
        asst_saved = [r for r in beam.remembered if "[ASSISTANT]" in r.get("content", "")]
        ok4 = len(user_saved) == 1 and len(asst_saved) == 1
        print(f"[4] JEV 실패: user_saved={len(user_saved)} asst_saved={len(asst_saved)} -> {'PASS' if ok4 else 'FAIL'}")
        if not ok4:
            failures.append("4: JEV 실패 시 데이터 손실")
    finally:
        if saved_key is not None:
            os.environ["TYPESAFE_API_KEY"] = saved_key

    print("=" * 50)
    if failures:
        print("FAILURES:", *failures, sep="\n  - ")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())