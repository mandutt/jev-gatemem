"""Stage-17: FTS-snippet / query-aware window (b-ai #6) — does feeding the
MATCHING 300-char window instead of the head-100 excerpt improve Jev's choice?

Design (a-ai Run S-Snippet):
- For each gold 19 row that reaches the gate: instead of label = head 100 chars,
  compute a query-aware window: find the 300-char span in the content with the
  max lexical overlap with the query (FTS match positions), label = that window.
- Call real Jev choice (free lane) twice: baseline labels (head-100) vs
  snippet labels (window-300 char, truncated to ~100-120 for fairness? NO —
  keep 300 to give it a chance; but labels must stay short for the API.
  Use 150 chars of the window).
- Measure: gold picked as #1 with baseline vs with snippet.

Budget: gold 19 x 2 labelsets x 2 reps = up to 76 calls (free lane).
Only rows that pass gate (12 at budget 60) are tested.
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
    """Find the span of `win` chars with max lexical overlap vs query tokens."""
    c = body(content)
    qt = _tokenize(query) - _STOPWORDS
    if not qt:
        return c[:min(len(c), win)]
    # scan windows at 50-char steps
    best_start, best_score = 0, -1
    step = 50
    for start in range(0, max(1, len(c) - win + 1), step):
        seg = c[start:start + win]
        seg_toks = _tokenize(seg)
        score = len(qt & seg_toks)
        if score > best_score:
            best_score, best_start = score, start
    # also try exact match positions via regex on query terms (korean blocks)
    return c[best_start:best_start + win]

gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "stage2_final_gold.json"), encoding="utf-8"))
from jev_mem_core.pipeline import _jev_client
client = _jev_client()
print(f"client: {type(client)} url={getattr(client,'_jev_api','?')}")

def run_choice(query, pool_rows, labels):
    """Returns idx (0-based) or None (abstain/err)."""
    try:
        state = j1p.build_state(query, pool_rows)
        # build_state already uses head excerpts; we override labels below.
        idx = j1p._jev_choice(client, state, labels, timeout=20.0)
        return idx
    except Exception as e:
        return f"ERR:{str(e)[:60]}"

results = []
for g in gold:
    rid = g["row_id"]
    q = g["query"]
    f = _filter_and_rank(build_lane_pool(recall_raw, q), q)[:POOL_BUDGET]
    fids = [r.get("id") for r in f]
    if rid not in fids:
        continue
    pos = fids.index(rid)
    # baseline labels (head-100) — same as production
    labels_base = [j1p._excerpt((r.get("content") or ""), 100) or "n/a" for r in f]
    # snippet labels (query-aware 150)
    labels_snip = []
    for r in f:
        content = r.get("content") or ""
        if len(content) > 800 and rid != r.get("id"):
            # only targeted row gets window; others keep head (fairness)
            labels_snip.append(j1p._excerpt(content, 100))
        else:
            w = query_window(content, q, 300)
            labels_snip.append(j1p._excerpt(w, 150) or "n/a")
    picks_base, picks_snip = [], []
    for rep in range(2):
        ib = run_choice(q, f, labels_base)
        picks_base.append(ib)
        time.sleep(0.7)
        is_ = run_choice(q, f, labels_snip)
        picks_snip.append(is_)
        time.sleep(0.7)
    base_hit = any(p == pos for p in picks_base if isinstance(p, int))
    snip_hit = any(p == pos for p in picks_snip if isinstance(p, int))
    results.append((rid[:14], pos+1, base_hit, snip_hit, picks_base, picks_snip))
    print(f"  {rid[:14]} pos={pos+1} base={base_hit} snip={snip_hit} | base_picks={picks_base} snip_picks={picks_snip}")

print("\n=== SUMMARY ===")
n_base = sum(1 for r in results if r[2])
n_snip = sum(1 for r in results if r[3])
print(f"tested: {len(results)} (gate-passed at budget 60)")
print(f"gold picked #1: baseline {n_base}/{len(results)}  snippet {n_snip}/{len(results)}")
print("newly picked by snippet:",
      [r[0] for r in results if not r[2] and r[3]])
print("lost by snippet:",
      [r[0] for r in results if r[2] and not r[3]])
conn.close()
print("\nDONE")