"""Check lane pool determinism — same query run twice gives same order?"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")

from backends.mnemosyne import MnemosyneBackend
from experiments.lane_pool import LanePool
from gateway.excerpts import build_excerpt

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
Q = json.loads(Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json").read_text(encoding="utf-8"))

b = MnemosyneBackend(db_path=SNAP)
beam = b._ensure_beam()

q = Q[0]
p1 = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)
p2 = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)

c1 = [c.id for c in p1.retrieve(q["query"], budget=50)]
c2 = [c.id for c in p2.retrieve(q["query"], budget=50)]
print("same order:", c1 == c2)
if c1 != c2:
    for i, (a, b2) in enumerate(zip(c1, c2)):
        if a != b2:
            print(f"first diff at {i}: {a[:12]} vs {b2[:12]}")
            break
    print("c1[:10]:", [x[:8] for x in c1[:10]])
    print("c2[:10]:", [x[:8] for x in c2[:10]])

# also check: does prepare_candidates (short_excerpt) affect anything? no, but beam.get might be cached differently
# check FTS search determinism by calling twice
import inspect
src = inspect.getsource(type(beam))
print("\n_fts_search_working in beam:", "_fts_search_working" in src)
print("_wm_vec_search in beam:", "_wm_vec_search" in src)