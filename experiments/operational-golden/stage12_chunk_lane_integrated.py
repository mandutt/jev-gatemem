"""Stage-12: parent-level multi-vector INTEGRATED pilot.

Add a "chunk" lane to the real pipeline (build_lane_pool + _filter_and_rank)
as a sidecar: long-row chunks embedded (correct model) -> query -> top-K chunks
-> collapse to parents (1 slot per parent) -> RRF lane.

Measures (0 JEV, live DB read-only, scratch chunk index in memory):
  A) gold 19 real-usage: pool recovery + gate pass, baseline vs +chunk lane
     ([ASSISTANT] exclusion already lifted in code = current state)
  B) op-90: gate pass regression (must stay 81/90)
  C) noans 10: spurious gate pass (must not increase)

Implementation mirrors production: recall_raw gains "chunk" kind returning
[{"id": parent, "rank": i}]; build_lane_pool hydrates via "get".
"""
import os, re, sqlite3, json, sys
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import mnemosyne.core.beam as beam_mod
emb = beam_mod._embeddings

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search

def cls(c):
    h = c[:400]
    if '@file:' in h or '@url:' in h: return 'attach'
    if 'COMPACTION' in h or 'REFERENCE ONLY' in h: return 'compaction'
    if c.startswith('[opencode') or c.startswith('[codex'): return 'session'
    return 'plain'

def body(c):
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

def chunks_of(content, size=800):
    paras = re.split(r"\n+", content)
    out, acc = [], ""
    for p in paras:
        p = p.strip()
        if not p: continue
        if len(acc)+len(p)+1 > size and acc:
            out.append(acc); acc = p
        else:
            acc = acc + "\n" + p if acc else p
    if acc: out.append(acc)
    res = []
    for ch in out:
        while len(ch) > 1100:
            res.append(ch[:1100]); ch = ch[1100:]
        res.append(ch)
    return res

# ---- sidecar chunk index (long plain rows) ---------------------------------
long_rows = {}
for t in ("working_memory", "episodic_memory"):
    for r in conn.execute(f"SELECT id, content FROM {t}"):
        c = r["content"]
        if c and len(c) >= 2000 and cls(c) == 'plain':
            long_rows[r["id"]] = body(c)
print(f"long plain rows for sidecar: {len(long_rows)}")

chunk_index = []  # (parent_id, chunk_text)
for pid, c in long_rows.items():
    for ch in chunks_of(c):
        chunk_index.append((pid, ch))
chunk_texts = [ci[1] for ci in chunk_index]
CH, B = [], 32
for i in range(0, len(chunk_texts), B):
    CH.extend(np.asarray(v, dtype=np.float32) for v in emb.embed(chunk_texts[i:i+B]))
CH = np.stack(CH)
CH = CH / (np.linalg.norm(CH, axis=1, keepdims=True) + 1e-9)
parents = [ci[0] for ci in chunk_index]
print(f"sidecar chunks: {len(chunk_index)}")

CHUNK_TOP_K = 20   # chunks to pull
CHUNK_PARENT_SLOTS = 5  # collapsed parents to offer as lane (1 slot each)

def chunk_lane(qv, top_chunks=CHUNK_TOP_K, parent_slots=CHUNK_PARENT_SLOTS):
    """Returns [{id, rank}] parents collapsed from top chunks."""
    qv = qv / (np.linalg.norm(qv) + 1e-9)
    sims = CH @ qv
    order = np.argsort(-sims)[:top_chunks]
    parent_sim = {}
    for idx in order:
        pid = parents[idx]
        parent_sim[pid] = max(parent_sim.get(pid, -1), float(sims[idx]))
    ranked = sorted(parent_sim.items(), key=lambda x: -x[1])[:parent_slots]
    return [{"id": pid, "rank": i+1} for i, (pid, _) in enumerate(ranked)]

# ---- integrated recall_raw with chunk lane ----------------------------------
_CHUNK_ACTIVE = {"v": True}

def make_recall_raw(cx):
    def recall_raw(kind, arg, k):
        if kind == "fts": return beam_mod._fts_search_working(cx, arg, k=k)
        if kind == "vec":
            qemb = beam_mod._embeddings.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(cx, qemb[0], k=k)
        if kind == "imp": return _imp_search(cx, k=k)
        if kind == "graph": return _graph_lane_search(cx, arg, k=k)
        if kind == "chunk":
            if not _CHUNK_ACTIVE["v"]:
                return []
            qv = np.asarray(beam_mod._embeddings.embed([arg])[0], dtype=np.float32)
            return chunk_lane(qv)
        if kind == "get":
            r = cx.execute("SELECT id, content, source, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = cx.execute("SELECT id, content, source, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            if not r: return None
            return {"id": r[0], "content": r[1], "source": r[2], "importance": r[3]}
        return []
    return recall_raw

def run_one(cx, q, target, use_chunk):
    _CHUNK_ACTIVE["v"] = use_chunk
    rr = make_recall_raw(cx)
    pool = build_lane_pool(rr, q)
    f = _filter_and_rank(pool, q)[:40]
    fids = [r.get("id") for r in f]
    hit_pool = target in [r["id"] for r in pool]
    hit_gate = target in fids
    return hit_pool, hit_gate, len(pool), len(f)

# ---- A) gold 19 ------------------------------------------------------------
gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "stage2_final_gold.json"), encoding="utf-8"))
print(f"\n=== A) gold 19 (real-usage) ===")
resA = []
for g in gold:
    hp0, hg0, p0, f0 = run_one(conn, g["query"], g["row_id"], use_chunk=False)
    hp1, hg1, p1, f1 = run_one(conn, g["query"], g["row_id"], use_chunk=True)
    resA.append((g["row_id"][:14], hp0, hg0, hp1, hg1, p0, p1))
print(f"pool:  base {sum(r[1] for r in resA)}/19  +chunk {sum(r[3] for r in resA)}/19")
print(f"gate:  base {sum(r[2] for r in resA)}/19  +chunk {sum(r[4] for r in resA)}/19")
new_pool = [r for r in resA if not r[1] and r[3]]
new_gate = [r for r in resA if not r[2] and r[4]]
print(f"NEW pool entries: {len(new_pool)}  NEW gate passes: {len(new_gate)}")
for r in resA:
    if r[1] != r[3] or r[2] != r[4]:
        print(f"  {r[0]} pool {int(r[1])}->{int(r[3])} gate {int(r[2])}->{int(r[4])} (pool {r[5]}->{r[6]})")

# ---- B) op-90 regression -----------------------------------------------------
goldset = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "data", "golden_eval_v3.json"), encoding="utf-8"))
gold_qs = [(g["gold"], g["query"]) for g in goldset if g.get("gold")]
print(f"\n=== B) op-90 regression ===")
resB = []
for target, q in gold_qs:
    hp0, hg0, _, _ = run_one(conn, q, target, use_chunk=False)
    hp1, hg1, _, _ = run_one(conn, q, target, use_chunk=True)
    resB.append((target[:14], hp0, hg0, hp1, hg1))
print(f"pool:  base {sum(r[1] for r in resB)}/{len(resB)}  +chunk {sum(r[3] for r in resB)}/{len(resB)}")
print(f"gate:  base {sum(r[2] for r in resB)}/{len(resB)}  +chunk {sum(r[4] for r in resB)}/{len(resB)}")
reg = [r for r in resB if r[1] and not r[3]]
regg = [r for r in resB if r[2] and not r[4]]
print(f"pool regressions: {len(reg)}  gate regressions: {len(regg)}")
for r in reg[:8]: print(f"  {r[0]} pool {int(r[1])}->{int(r[3])}")
for r in regg[:8]: print(f"  {r[0]} gate {int(r[2])}->{int(r[4])}")

# ---- C) noans spurious --------------------------------------------------------
noans_qs = [g for g in goldset if not g.get("gold")]
print(f"\n=== C) noans 10 spurious gate pass ===")
resC = []
for g in noans_qs:
    q = g["query"]
    _, hg0, _, _ = run_one(conn, q, "", use_chunk=False)
    _, hg1, _, _ = run_one(conn, q, "", use_chunk=True)
    resC.append((q[:35], hg0, hg1))
print(f"noans with ANY gate pass: base {sum(r[1] for r in resC)}/10  +chunk {sum(r[2] for r in resC)}/10")

conn.close()
print("\nDONE")