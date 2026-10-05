"""Stage-18: snippet-window FULL verification — gold 19 + op-90 regression + noans.

Extends stage17 to the full evaluation sets (0 JEV for regression metrics —
choice calls only for the gold-lift subset; regressions measured by gate-pass
which is JEV-free; the gold lift uses free-lane calls like stage17).

Measures:
  A) gold 19: Jev #1-lift, baseline(head-100) vs snippet(query-window 300->150)
     (free lane; 2 reps)
  B) op-90: gate-pass with snippet LABELS? No — gate is label-independent.
     What changes with snippet is only the Jev-choice labels. So op-90
     regression = does snippet change Jev picks (which could break op-90 hit@3)?
     -> run Jev choice on op-90 gold queries with both labelsets, check gold
     row picked (free lane, 90 x 2 x 2 = 360 calls — cap to subset 40 for budget)
  C) noans: with snippet labels, do noans queries get a gold-ish pick (abstain
     vs random row)? Sample 6 noans x 2 labelsets (24 calls).

Budget: ~12(gold lift) + 40(op90 subset) + 12(noans) = ~64 calls x 2 labelsets.
Keep within free lane.
"""
import os, re, sqlite3, json, sys, time
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import winreg
def hkcu_env(name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except OSError:
        return None
for k in ("EXPLABS_API_KEY", "EXPLABS_API_KEY2", "TYPESAFE_API_KEY"):
    if not os.environ.get(k):
        v = hkcu_env(k)
        if v:
            os.environ[k] = v

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

import mnemosyne.core.beam as beam_mod
from gateway import j1_pipeline as j1p
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search, _tokenize, _STOPWORDS, POOL_BUDGET

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = beam_mod._embeddings.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return _imp_search(conn, k=k)
    if kind == "graph": return _graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, source, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, source, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "source": r[2], "importance": r[3]}
    return []

def body(c):
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

def query_window(content, query, win=300):
    c = body(content)
    qt = _tokenize(query) - _STOPWORDS
    if not qt:
        return c[:min(len(c), win)]
    best_start, best_score = 0, -1
    step = 50
    for start in range(0, max(1, len(c) - win + 1), step):
        seg = c[start:start + win]
        seg_toks = _tokenize(seg)
        score = len(qt & seg_toks)
        if score > best_score:
            best_score, best_start = score, start
    return c[best_start:best_start + win]

from jev_mem_core.pipeline import _jev_client
client = _jev_client()
print(f"client url={getattr(client,'_jev_api','?')}")

def labels_for(pool, query, snippet, target_rid=None):
    out = []
    for r in pool:
        content = r.get("content") or ""
        if snippet and (target_rid is None or r.get("id") == target_rid):
            w = query_window(content, query, 300)
            out.append(j1p._excerpt(w, 150) or "n/a")
        else:
            out.append(j1p._excerpt(content, 100) or "n/a")
    return out

def run_choice(query, pool, labels):
    try:
        state = j1p.build_state(query, pool)
        return j1p._jev_choice(client, state, labels, timeout=20.0)
    except Exception as e:
        return f"ERR:{str(e)[:50]}"

def gold_picked(query, pool_rows, target, snippet, reps=2):
    """Returns (picked_count, picks) for target among pool_rows."""
    labels = labels_for(pool_rows, query, snippet, target)
    pos = [r.get("id") for r in pool_rows].index(target)
    picks = []
    for _ in range(reps):
        idx = run_choice(query, pool_rows, labels)
        picks.append(idx)
        time.sleep(0.6)
    hits = sum(1 for p in picks if p == pos)
    return hits, picks, pos

# ---- A) gold 19 ------------------------------------------------------------
gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "stage2_final_gold.json"), encoding="utf-8"))
print("\n=== A) gold 19 lift (base vs snippet) ===")
rowsA = []
for g in gold:
    q = g["query"]; rid = g["row_id"]
    f = _filter_and_rank(build_lane_pool(recall_raw, q), q)[:POOL_BUDGET]
    if rid not in [r.get("id") for r in f]:
        continue
    hb, pb, pos = gold_picked(q, f, rid, snippet=False)
    hs, ps, _ = gold_picked(q, f, rid, snippet=True)
    rowsA.append((rid[:14], pos+1, hb, hs, pb, ps))
for r in rowsA:
    print(f"  {r[0]} pos={r[1]} base={r[2]}/2 snip={r[3]}/2 | picks b={r[4]} s={r[5]}")
print(f"A: base {sum(r[2] for r in rowsA)}/{len(rowsA)*2}  snippet {sum(r[3] for r in rowsA)}/{len(rowsA)*2}")
print(f"   newly: {[r[0] for r in rowsA if r[3]>r[2]]}  lost: {[r[0] for r in rowsA if r[3]<r[2]]}")

# ---- B) op-90 subset (40 queries) -------------------------------------------
goldset = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "data", "golden_eval_v3.json"), encoding="utf-8"))
gold_qs = [(g["gold"], g["query"]) for g in goldset if g.get("gold")]
import random
random.seed(7)
subset = random.sample(gold_qs, min(40, len(gold_qs)))
print(f"\n=== B) op-90 subset ({len(subset)}) — gold pick change ===")
reg = imp = 0
for target, q in subset:
    f = _filter_and_rank(build_lane_pool(recall_raw, q), q)[:POOL_BUDGET]
    fids = [r.get("id") for r in f]
    if target not in fids:
        continue
    hb, pb, _ = gold_picked(q, f, target, snippet=False, reps=1)
    hs, ps, _ = gold_picked(q, f, target, snippet=True, reps=1)
    if hs > hb: imp += 1
    if hs < hb: reg += 1
print(f"B: gold-pick improvements {imp}, regressions {reg} (of {len(gold_qs)} total, subset {len(subset)})")

# ---- C) noans sample (6) ------------------------------------------------------
noans_qs = [g for g in goldset if not g.get("gold")]
sample_n = random.sample(noans_qs, min(6, len(noans_qs)))
print(f"\n=== C) noans sample ({len(sample_n)}) — abstain / pick ===")
for g in sample_n:
    q = g["query"]
    f = _filter_and_rank(build_lane_pool(recall_raw, q), q)[:POOL_BUDGET]
    if not f:
        print(f"  {q[:30]!r}: empty gate (no prefetch) — OK")
        continue
    labels_b = labels_for(f, q, False)
    labels_s = labels_for(f, q, True)
    ib = run_choice(q, f, labels_b); time.sleep(0.6)
    is_ = run_choice(q, f, labels_s); time.sleep(0.6)
    print(f"  {q[:30]!r}: base={ib} snip={is_}")

conn.close()
print("\nDONE")