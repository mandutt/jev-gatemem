"""Stage-9 regression: would removing the [ASSISTANT] prefetch exclusion hurt
recall quality?

Question: _PREFETCH_EXCLUDED_PREFIXES=('[ASSISTANT]',) is the real bottleneck
(gold 1/19 -> 8/19 if lifted). But the exclusion exists to keep assistant noise
out of prefetch. Regression test on:

  A) op-90 golden (golden_eval_v3.json 100 rows incl noans 10):
     - with exclusion (current): gold gate-pass rate
     - without exclusion (prefix stripped): gold gate-pass rate
     - MUST NOT regress (loss 0) for adoption.
  B) noans 10 (golden_eval_v3.json rows without 'gold' key):
     - measure how many noans queries get a WRONG gate pass (spurious assistant
       rows entering prefetch) with and without exclusion.
  C) pool composition: how many [ASSISTANT] rows enter the pool per query with
     exclusion lifted (noise level).

0 JEV calls. Live DB read-only.
"""
import os, re, sqlite3, json, sys
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
c.enable_load_extension(True)
sqlite_vec.load(c)

import mnemosyne.core.beam as beam_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(c, arg, k=k)
    if kind == "vec":
        qemb = beam_mod._embeddings.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(c, qemb[0], k=k)
    if kind == "imp": return _imp_search(c, k=k)
    if kind == "graph": return _graph_lane_search(c, arg, k=k)
    if kind == "get":
        r = c.execute("SELECT id, content, source, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = c.execute("SELECT id, content, source, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "source": r[2], "importance": r[3]}
    return []

def gate_with(pool, query, strip_asst):
    rows = []
    for row in pool:
        r2 = dict(row)
        content = r2.get("content") or ""
        if strip_asst and content.upper().startswith("[ASSISTANT]"):
            # simulate lifting the exclusion: strip prefix so startswith check passes
            r2["content"] = content.split("]", 1)[1].lstrip() if "]" in content else content
        rows.append(r2)
    return _filter_and_rank(rows, query)[:40]

# ---- load gold sets ----------------------------------------------------------
goldset = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "data", "golden_eval_v3.json"), encoding="utf-8"))
gold_qs = [(g["gold"], g["query"]) for g in goldset if g.get("gold")]
noans_qs = [g for g in goldset if not g.get("gold")]
print(f"op-90 gold: {len(gold_qs)}   noans: {len(noans_qs)}")

# ---- A) op-90 gold gate pass (with vs without exclusion) ----------------------
a_with = a_without = 0
a_details = []
for target, q in gold_qs:
    pool = build_lane_pool(recall_raw, q)
    fw = gate_with(pool, q, strip_asst=False)
    fo = gate_with(pool, q, strip_asst=True)
    hw = any(r["id"] == target for r in fw)
    ho = any(r["id"] == target for r in fo)
    a_with += hw; a_without += ho
    if hw != ho:
        a_details.append((target[:14], hw, ho))
print(f"\n[A] op-90 gold gate pass: with-excl {a_with}/{len(gold_qs)}   without-excl {a_without}/{len(gold_qs)}")
print(f"    changed cases: {len(a_details)}")
for d in a_details[:15]:
    print(f"      {d[0]} with={int(d[1])} without={int(d[2])}")

# ---- B) noans spurious gate pass ----------------------------------------------
b_with = b_without = 0
b_asst_rows = []
for g in noans_qs:
    q = g["query"]
    pool = build_lane_pool(recall_raw, q)
    fw = gate_with(pool, q, strip_asst=False)
    fo = gate_with(pool, q, strip_asst=True)
    # spurious = any gate-passed row at all (prefetch would show something)
    if len(fw) > 0: b_with += 1
    if len(fo) > 0: b_without += 1
    # count assistant rows in the passed set (noise)
    n_asst = sum(1 for r in fo if (r.get("content") or "").upper().startswith("[ASSISTANT]"))
    b_asst_rows.append((q[:40], n_asst, len(fo)))
print(f"\n[B] noans queries with ANY gate pass: with-excl {b_with}/{len(noans_qs)}   without-excl {b_without}/{len(noans_qs)}")
print("    [assistant rows in passed set] (sample):")
for qq, na, nf in b_asst_rows[:8]:
    print(f"      asst={na}/{nf} | {qq!r}")

# ---- C) pool assistant-noise level per query type ------------------------------
print(f"\n[C] assistant rows in pool (without-excl run, mean over queries):")
for name, qs in (("op90", gold_qs), ("noans", [(None, g["query"]) for g in noans_qs])):
    tot_asst = 0; tot_pool = 0
    for _, q in qs:
        pool = build_lane_pool(recall_raw, q)
        n_asst = sum(1 for r in pool if (r.get("content") or "").upper().startswith("[ASSISTANT]"))
        tot_asst += n_asst; tot_pool += len(pool)
    print(f"    {name}: pool avg {tot_pool/len(qs):.1f}, [ASSISTANT] avg {tot_asst/len(qs):.1f} ({tot_asst/max(tot_pool,1)*100:.0f}%)")

c.close()
print("\nDONE")