"""noans 6건 choice 선택 후보 재현 (2026-10-04)

exp7d는 choice 인덱스(c1/c2/...)만 저장, 후보 pool 미저장.
→ 같은 파이프라인(stage1_pool)으로 pool을 재현하고 choice 인덱스로 실제 선택 메모리 복원.

검증: 재현 pool의 n_pool이 raw의 n_pool과 일치해야 함 (결정적 파이프라인이면).
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "experiments/operational-golden/data")
LIVE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments/operational-golden"))
os.environ.setdefault("MNEMOSYNE_DB", LIVE_DB)
import gateway.j1_pipeline as j1p
import mnemosyne.core.beam as bm
from mnemosyne.core import embeddings as emb_mod

d = json.load(open(os.path.join(DATA, "exp7d_fresh_noans_raw.json"), encoding="utf-8"))
recs = [r for r in d["records"] if not r.get("choice_abstain")]

b = bm.BeamMemory(session_id="exp7d_repro")

def recall_raw(kind, arg, k_):
    if kind == "fts":
        return bm._fts_search_working(b.conn, arg, k=k_)
    if kind == "vec":
        e = emb_mod.embed([arg])
        if e is None or not len(e):
            return []
        return bm._wm_vec_search(b.conn, e[0], k=k_)
    if kind == "imp":
        return j1p._imp_search(b.conn, k=k_)
    if kind == "graph":
        return j1p._graph_lane_search(b.conn, arg, k=k_)
    if kind == "get":
        from core import j1_engine
        row = j1_engine.hydration_get(b, arg)
        return row if isinstance(row, dict) else None
    return []

# exp7d의 stage1_pool 로직 재현
def stage1_pool(query, exclude_ids=None, k=40):
    pool = j1p.build_lane_pool(recall_raw, query)
    if exclude_ids:
        pool = [p for p in pool if p.get("id") not in exclude_ids]
    ranked = j1p._filter_and_rank(pool, query) if pool else []
    return ranked[:k]

out = []
for r in recs:
    qid = r["qid"]
    q = r["query"]
    try:
        pool = stage1_pool(q, k=40)
    except Exception as e:
        print(f"{qid}: pool 재현 실패 {type(e).__name__}: {e}")
        out.append({"qid": qid, "err": f"{type(e).__name__}"})
        continue
    print(f"{qid}: 재현 pool {len(pool)}건 (raw n_pool={r.get('n_pool')})")
    # choice 인덱스 추출 (c1 → 1)
    ch = r.get("choice", "c0")
    idx = int(str(ch).lstrip("c"))
    if idx >= len(pool):
        print(f"  !!! choice idx {idx} >= pool {len(pool)} — 불일치")
        out.append({"qid": qid, "err": f"idx-out-of-range {idx}/{len(pool)}", "n_pool_repro": len(pool)})
        continue
    chosen = pool[idx]
    out.append({
        "qid": qid,
        "query": q,
        "choice_idx": idx,
        "chosen_id": chosen.get("id"),
        "chosen_excerpt100": (chosen.get("content") or "")[:100],
        "chosen_full": chosen.get("content") or "",
        "n_pool_repro": len(pool),
        "n_pool_raw": r.get("n_pool"),
        "match": len(pool) == r.get("n_pool"),
    })
    print(f"  → choice id={chosen.get('id')} | {(chosen.get('content') or '')[:60]}")

with open(os.path.join(DATA, "exp7d_choice_repro.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"\n저장: {DATA}/exp7d_choice_repro.json")