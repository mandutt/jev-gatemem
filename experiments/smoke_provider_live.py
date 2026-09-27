"""Prod-venv integration test: JevRerankProvider.prefetch on the LIVE Hermes DB.

Modes:
  --off   JEV_RERANK=0        -> must equal base Mnemosyne prefetch (regression)
  --on    JEV_RERANK=1 + key  -> J1 path runs; must produce valid block or fall back

Uses the live production DB (read-only recall; no writes). Requires the
Hermes runtime venv python (mnemosyne_hermes importable).
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from harnesses.hermes_j1 import JevRerankProvider

DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
Q = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json", encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--off", action="store_true")
    ap.add_argument("--on", action="store_true")
    args = ap.parse_args()
    off = args.off or not args.on

    if off:
        os.environ["JEV_RERANK"] = "0"
    else:
        os.environ.pop("JEV_RERANK", None)

    p = JevRerankProvider()
    # initialize against the live DB so _beam is bound
    p.initialize(
        "hermes_j1_smoke",
        hermes_home=r"C:\Users\mandu\AppData\Local\hermes",
        agent_context="primary",
        platform="cli",
    )
    beam = p._beam
    if beam is None:
        print("BEAM NONE — provider init failed")
        return 1
    print("beam db:", beam.db_path)

    base = p.prefetch if False else None  # placeholder

    # 1) base provider output for comparison (construct a plain MnemosyneMemoryProvider)
    from mnemosyne_hermes import MnemosyneMemoryProvider

    bp = MnemosyneMemoryProvider()
    bp.initialize(
        "hermes_j1_smoke",
        hermes_home=r"C:\Users\mandu\AppData\Local\hermes",
        agent_context="primary",
        platform="cli",
    )

    identical = 0
    n_queries = 8
    for q in Q[:n_queries]:
        qq = q["query"]
        a = bp.prefetch(qq)
        b = p.prefetch(qq)
        if off:
            same = (a == b)
            identical += int(same)
            print(f"[off] {'SAME' if same else 'DIFF'} :: {qq[:50]}")
        else:
            print(f"[on]  base_len={len(a)} j1_len={len(b)} :: {qq[:50]}")
            if b and not b.startswith("## Mnemosyne Context"):
                print("   !!! J1 block missing header:", repr(b[:60]))

    if off:
        print(f"\nidentical: {identical}/{n_queries}")
        ok = identical == n_queries
        print("REGRESSION", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    else:
        print("\nJ1 ON smoke done (real Jev calls happen per query)")
        return 0


if __name__ == "__main__":
    sys.exit(main())