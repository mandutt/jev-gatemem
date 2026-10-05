"""Screen probe A: run the vendored local_screen over the live Mnemosyne DB (read-only).

0-call offline probe. For each row: content length, sensitive?, screen shape.
Outputs JSONL raw + a summary. No writes to the DB; report only.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screen_probe_vendor import classify, local_screen, is_sensitive, normalize, screen_one

DB = os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "screen_probeA_raw.jsonl")

SCHEMAS = {
    "working_memory": ("id", "content", "source", "timestamp", "memory_type"),
    "episodic_memory": ("id", "content", "source", "timestamp", "memory_type"),
}


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows_written = 0
    stats: Counter = Counter()
    hits: Counter = Counter()
    examples: dict = {}
    t0 = time.time()

    with open(OUT, "w", encoding="utf-8") as f:
        for table, cols in SCHEMAS.items():
            q = f"SELECT {', '.join(cols)} FROM {table}"
            for row in con.execute(q):
                rid, content, source, ts, mtype = row
                content = content or ""
                stats["total"] += 1
                flagged, shape = classify(content)
                sens = is_sensitive(content)
                rec = {
                    "table": table, "id": rid, "len": len(content), "source": source,
                    "memory_type": mtype, "sensitive": sens, "flagged": flagged, "shape": shape,
                    "ts": ts,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                rows_written += 1
                if flagged:
                    stats["flagged"] += 1
                    hits[shape] += 1
                    examples.setdefault(f"{table}:{shape}", []).append((rid, content[:200]))
                elif sens:
                    stats["sensitive_clean"] += 1
                # len buckets
                if len(content) > 900:
                    stats["over900"] += 1

    con.close()
    elapsed = time.time() - t0

    print(f"rows written: {rows_written}  elapsed: {elapsed:.1f}s")
    print(f"total      : {stats['total']}")
    print(f"flagged    : {stats['flagged']}  ({stats['flagged'] / max(1, stats['total']) * 100:.2f}%)")
    print(f"over900    : {stats['over900']}")
    print("shapes:")
    for shape, n in hits.most_common():
        print(f"  {shape:20s} {n}")
    print("\nexamples per shape/table:")
    for key, exs in examples.items():
        print(f"--- {key} ({len(exs)}) ---")
        for rid, snippet in exs[:3]:
            print(f"  {rid}: {snippet!r}")


if __name__ == "__main__":
    main()