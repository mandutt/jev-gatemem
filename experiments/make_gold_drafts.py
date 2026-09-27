"""Gold-draft generation: for each dataset query, run snapshot recall(top-30) and
record the top-10 hits as gold candidates. Human curation happens afterwards.

Writes: data/dataset_gold_drafts.json  (query -> [hit_id, score, excerpt, src])
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backends.mnemosyne import MnemosyneBackend

SNAP = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db")
QUERIES = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_candidates.json")
OUT = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_gold_drafts.json")


def main():
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))
    backend = MnemosyneBackend(db_path=str(SNAP))
    out = []
    for q in queries:
        hits = backend.recall(q["query"], top_k=30)
        draft = {
            "qid": q["qid"], "query": q["query"], "type": q["type"],
            "top30": [
                {"id": h.id, "score": h.score, "src": h.source,
                 "excerpt": (h.content or "")[:140]}
                for h in hits
            ],
        }
        out.append(draft)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(out)} gold drafts -> {OUT}")


if __name__ == "__main__":
    main()