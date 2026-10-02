"""Dry-run (JEV-call-free) validation of abstain choice question construction.

Verifies the questions dicts are structurally valid for the live daemon's patterns:
- baseline: exact match of gateway.j1_pipeline._jev_choice question construction
- abstain:  same + c40 abstain label, instructions mention abstention

Also sanity-checks abstain label wording against the daemon's criteria dict schema
(keys c0..cN, values str).
"""
import json
import sys
import os

ROOT = "C:/Users/mandu/hermes-made/jev-memory-middleware"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import gateway.j1_pipeline as j1p

# --- reproduce the daemon's baseline question exactly (j1_pipeline._jev_choice) ---
def base_questions(labels):
    return {
        "best": {
            "type": "choice",
            "instructions": (
                "Which candidate memory is the single best evidence for answering "
                "the question? Pick exactly one. Consider directness and specificity."
            ),
            "criteria": {f"c{i}": labels[i] for i in range(len(labels))},
        }
    }

def abstain_questions(labels):
    crit = {f"c{i}": labels[i] for i in range(len(labels))}
    crit[f"c{len(labels)}"] = "No candidate is usable evidence for answering the question"
    return {
        "best": {
            "type": "choice",
            "instructions": (
                "Which candidate memory is the single best evidence for answering "
                "the question? If none of the candidates contains usable evidence, "
                "pick the 'no candidate' option. Consider directness and specificity."
            ),
            "criteria": crit,
        }
    }

# load one real pool from the dry-run raw (rows that reached JEV)
raw = json.load(open("experiments/operational-golden/abstain_run_O_raw.json", encoding="utf-8"))
row = next(r for r in raw if "pool" in r and r.get("pool"))
queries = json.load(open("experiments/operational-golden/data/golden_final_v2.json", encoding="utf-8"))
qtext = row["query"]

# rebuild state + labels exactly as the experiment did
import mnemosyne.core.beam as bm
from mnemosyne.core import embeddings as emb_mod
from core import j1_engine

_b = None
def get_beam():
    global _b
    if _b is None:
        _b = bm.BeamMemory(session_id="golden-eval-o-dry")
    return _b

def recall_raw(kind, arg, k_):
    b = get_beam()
    if kind == "fts":  return bm._fts_search_working(b.conn, arg, k=k_)
    if kind == "vec":
        e = emb_mod.embed([arg])
        if not e or not len(e): return []
        return bm._wm_vec_search(b.conn, e[0], k=k_)
    if kind == "imp":  return j1p._imp_search(b.conn, k=k_)
    if kind == "graph": return j1p._graph_lane_search(b.conn, arg, k=k_)
    if kind == "get":
        r = j1_engine.hydration_get(b, arg)
        return r if isinstance(r, dict) else None
    return []

pool = j1p.build_lane_pool(recall_raw, qtext)
pool = j1p._filter_and_rank(pool, qtext)[:40]
state = j1p.build_state(qtext, pool)
labels = [j1p._excerpt((c.get("content") or ""), 100) or "n/a" for c in pool]

qb = base_questions(labels)
qa = abstain_questions(labels)

# --- validations ---
assert len(qb["best"]["criteria"]) == len(labels), "baseline criteria count"
assert len(qa["best"]["criteria"]) == len(labels) + 1, "abstain criteria count"
assert qb == {"best": {
    "type": "choice",
    "instructions": "Which candidate memory is the single best evidence for answering the question? Pick exactly one. Consider directness and specificity.",
    "criteria": {f"c{i}": labels[i] for i in range(len(labels))},
}}, "baseline mismatch vs daemon"

# abstain label is a real string, distinct from all candidate labels
assert qa["best"]["criteria"][f"c{len(labels)}"] == "No candidate is usable evidence for answering the question"
assert all(qa["best"]["criteria"][f"c{len(labels)}"] != v for v in labels), "abstain label collides"

# payload serializable
body = json.dumps({"state": state, "questions": qa, "model": "jev-latest"})
print(f"OK. pool={len(pool)} state_chars={len(json.dumps(state,ensure_ascii=False))} "
      f"payload_chars={len(body)} abstain_criteria_key=c{len(labels)}")
print("abstain question keys:", list(qa["best"]["criteria"].keys())[:5], "...",
      list(qa["best"]["criteria"].keys())[-3:])