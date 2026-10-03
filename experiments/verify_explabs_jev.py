"""Verify Experiential Labs gateway works as JEV API for jev-mem dev/test.

Tests the real repo code paths (write_gate.evaluate, jev_rerank) against
https://api.experientiallabs.ai/v1/systemone using EXPLABS_API_KEY, WITHOUT
touching the live daemon (which keeps using TYPESAFE_API_KEY).

Usage:
    JEV_API_URL=https://api.experientiallabs.ai/v1/systemone \
    TYPESAFE_API_KEY=<xpl_ key> \
    <jev-mem venv python> experiments/verify_explabs_jev.py

(The repo code reads TYPESAFE_API_KEY for auth — for this test we simply
point it at the xpl_ key; the live daemon is untouched since this script
runs in its own process.)
"""
import os
import sys
import time
import json
import winreg
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

GATEWAY_URL = "https://api.experientiallabs.ai/v1/systemone"


def _resolve_explabs_key():
    """HKCU registry first (matches repo convention), fallback to env."""
    k = os.environ.get("EXPLABS_API_KEY", "")
    try:
        hk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        try:
            reg_k, _ = winreg.QueryValueEx(hk, "EXPLABS_API_KEY")
            if reg_k:
                k = reg_k
        finally:
            winreg.CloseKey(hk)
    except FileNotFoundError:
        pass
    return k


def main():
    key = _resolve_explabs_key()
    if not key:
        print("FAIL: no EXPLABS_API_KEY (env or HKCU)")
        return 1
    import hashlib
    print(f"key: len={len(key)} prefix={key[:4]}... sha12={hashlib.sha256(key.encode()).hexdigest()[:12]}")

    # Point repo code at the gateway: JEV_API_URL + TYPESAFE_API_KEY (auth source)
    os.environ["JEV_API_URL"] = GATEWAY_URL
    os.environ["TYPESAFE_API_KEY"] = key

    import httpx
    from gateway.write_gate import evaluate, evaluate_assistant
    from gateway.j1_pipeline import jev_rerank, build_state

    results = []

    # --- 1) write_gate.evaluate (G-qual) against gateway ---
    t0 = time.perf_counter()
    v = evaluate("내일까지 보고서 제출해야 해")
    dt = (time.perf_counter() - t0) * 1000
    print(f"\n[1] write_gate.evaluate  -> keep={v.get('keep')} store={v.get('store')} "
          f"type={v.get('type')} reason={v.get('reason')} lat={v.get('latency_ms')}ms (wall {dt:.0f}ms)")
    ok1 = v.get("reason") not in ("no-key", None) and "http-" not in str(v.get("reason"))
    results.append(("G-qual via gateway", ok1, v.get("reason")))

    # --- 2) evaluate_assistant (G-AS) ---
    v2 = evaluate_assistant("이제 시스템을 분석한다")
    print(f"[2] evaluate_assistant   -> keep={v2.get('keep')} reason={v2.get('reason')}")
    ok2 = v2.get("reason") not in ("no-key", None) and "http-" not in str(v2.get("reason"))
    results.append(("G-AS via gateway", ok2, v2.get("reason")))

    # --- 3) jev_rerank (read path) against gateway ---
    pool = [
        {"id": "aaaaaaaaaaaa", "content": "보고서는 다음 주 월요일에 제출하면 된다", "memory_type": "fact", "scope": "global", "importance": 0.5, "source": "user"},
        {"id": "bbbbbbbbbbbb", "content": "내일까지 보고서 제출해야 해", "memory_type": "task", "scope": "session", "importance": 0.8, "source": "user"},
        {"id": "cccccccccccc", "content": "오늘 날씨가 맑았다", "memory_type": "context", "scope": "session", "importance": 0.2, "source": "user"},
    ]
    c = httpx.Client(timeout=httpx.Timeout(15.0, connect=15.0),
                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.perf_counter()
    rows, abstained = jev_rerank(query="보고서 언제까지 제출해야 하지?", pool=[dict(p) for p in pool], client=c)
    dt = (time.perf_counter() - t0) * 1000
    print(f"[3] jev_rerank            -> first_id={rows[0]['id'] if rows else None} abstained={abstained} wall={dt:.0f}ms")
    print(f"    (expected lift: bbbbbbbbbbbb to rank 1 for the deadline question)")
    ok3 = bool(rows) and rows[0]["id"] == "bbbbbbbbbbbb"
    results.append(("jev_rerank via gateway (lift bbb.. to #1)", ok3, f"first={rows[0]['id'] if rows else None}"))

    # --- 4) build_state sanity (no network) ---
    st = build_state("보고서 언제?", pool)
    print(f"[4] build_state           -> keys={sorted(st.keys())} n_candidates={len(st['candidates'])}")
    ok4 = "question" in st and len(st["candidates"]) == 3
    results.append(("build_state shape", ok4, ""))

    c.close()

    print("\n== RESULT ==")
    all_ok = True
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({detail})")
        all_ok = all_ok and ok
    print("ALL PASS" if all_ok else "SOME FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
