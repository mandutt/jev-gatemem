"""Korean screen FP + catch probe on the live Mnemosyne DB (read-only, 0 calls).

Runs ko_screen over all working+episodic rows. Reports FP candidates (flagged
rows) with a snippet for human adjudication, plus shape distribution.
Also re-runs the earlier English screen flagged rows (73) against ko_screen to
confirm they are NOT double-flagged (i.e. ko screen adds no new FP on them).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screen_probe_ko import ko_screen
from screen_probe_vendor import local_screen, is_sensitive

DB = os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "screen_probeKO_raw.jsonl")


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    all_rows = []
    for table in ("working_memory", "episodic_memory"):
        for rid, content, source in con.execute(f"SELECT id, content, source FROM {table}"):
            all_rows.append((table, rid, content or "", source))
    con.close()

    t0 = time.time()
    flagged = []
    shapes: Counter = Counter()
    eng_flagged_ids = set()
    with open(OUT, "w", encoding="utf-8") as f:
        for table, rid, content, source in all_rows:
            shape = ko_screen(content)
            rec = {"table": table, "id": rid, "shape": shape, "len": len(content), "source": source}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if shape:
                flagged.append((table, rid, shape, content))
                shapes[shape] += 1
            # English screen overlap check (from earlier probe A: 73 rows flagged)
            sens = is_sensitive(content)
            eng = local_screen(content, unvetted=sens)
            if eng or sens:
                eng_flagged_ids.add(rid)
    elapsed = time.time() - t0

    print(f"rows: {len(all_rows)}  elapsed: {elapsed:.1f}s")
    print(f"ko_screen flagged: {len(flagged)} ({len(flagged) / len(all_rows) * 100:.2f}%)")
    print("shapes:", dict(shapes))
    # overlap with English-flagged set (are they the same rows?)
    ko_ids = {rid for _, rid, _, _ in flagged}
    overlap = ko_ids & eng_flagged_ids
    print(f"English-flagged(73)∩ko-flagged: {len(overlap)} (ko adds {len(ko_ids) - len(overlap)} new)")
    print("\n--- ko-flagged rows (FP adjudication) ---")
    for table, rid, shape, content in flagged:
        print(f"[{table[:8]}] {shape:12s} {rid[:12]} len={len(content)} :: {content[:110]!r}")


if __name__ == "__main__":
    main()