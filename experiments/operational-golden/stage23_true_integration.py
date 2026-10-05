"""Stage-23: 진짜 통합 — chunk-vec 레인을 build_lane_pool에 추가해 RRF 합산 + all-candidate snippet + 최종 hit@3.

c-ai/b-ai 검토 반영 (2026-10-05):
- stage12/20의 "통합 이득 0"은 build_lane_pool이 "chunk" kind를 호출하지 않아 무효였음.
- 이번엔 build_lane_pool을 모방하는 커스텀 lane pool로 fts+vec+imp+graph+chunk(vec) 5레인 RRF를 진짜 합산.
- POOL-MISS 4건(afd156a9, 329fb315, f66a777d, 77f9a2b2)이 chunk lane으로 살아나는지.
- all-candidate snippet VS target-only snippet 비교 (production은 all-candidate).
- 최종 hit@3 (Jev choice free lane, gold 19 전부).

0 JEV 기준선은 0콜, Jev lift만 무료 레인 소량.
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

# ---- sidecar chunk vec index (correct model beam) ---------------------------
chunk_index = []
for t in ("working_memory", "episodic_memory"):
    for r in conn.execute(f"SELECT id, content FROM {t}"):
        c = r["content"]
        if c and len(c) >= 2000 and cls(c) == 'plain':
            for ch in chunks_of(c):
                chunk_index.append((r["id"], ch))
print(f"chunks: {len(chunk_index)}")
B = 4
CH = []
for i in range(0, len(chunk_index), B):
    CH.extend(np.asarray(v, dtype=np.float32) for v in beam_mod._embeddings.embed([ci[1] for ci in chunk_index[i:i+B]]))
CH = np.stack(CH)
parents = [ci[0] for ci in chunk_index]
CHUNK_TOP_K = 30
CHUNK_PARENT_SLOTS = 20

def chunk_lane_vec(qv, top_chunks=CHUNK_TOP_K, parent_slots=CHUNK_PARENT_SLOTS):
    sims = np.asarray(CH) @ qv
    order = np.argsort(-sims)[:top_chunks]
    seen = set(); out = []
    for idx in order:
        pid = parents[idx]
        if pid not in seen:
            seen.add(pid)
            out.append({"id": pid, "rank": len(out)+1})
            if len(out) >= parent_slots:
                break
    return out

# ---- 커스텀 5-lane RRF pool (build_lane_pool 모방 + chunk) ---------------------
LANE = {"fts": 60, "vec": 60, "imp": 8, "graph": 10, "chunk": 20}
def pool5(q, use_chunk):
    ranks = {}
    def add(kind, rows):
        for i, r in enumerate(rows, start=1):
            ranks.setdefault(r["id"], {})[kind + "_rank"] = i
    add("fts", beam_mod._fts_search_working(conn, q, k=LANE["fts"]))
    qemb = beam_mod._embeddings.embed([q])
    if qemb is not None and len(qemb):
        add("vec", beam_mod._wm_vec_search(conn, qemb[0], k=LANE["vec"]))
    add("imp", _imp_search(conn, k=LANE["imp"]))
    add("graph", _graph_lane_search(conn, q, k=LANE["graph"]))
    if use_chunk:
        qv = np.asarray(qemb[0], dtype=np.float32)
        add("chunk", chunk_lane_vec(qv))
    # RRF (k=60)
    K = 60
    rr = {}
    for rid, rk in ranks.items():
        s = sum(1.0/(K + v) for v in rk.values())
        rr[rid] = s
    order = sorted(rr, key=lambda x: -rr[x])
    # hydrate
    out = []
    for rid in order[:POOL_BUDGET*2]:
        r = conn.execute("SELECT id, content, source, importance FROM working_memory WHERE id=?", (rid,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, source, importance FROM episodic_memory WHERE id=?", (rid,)).fetchone()
        if r:
            out.append({"id": r[0], "content": r[1], "source": r[2], "importance": r[3]})
        if len(out) >= POOL_BUDGET:
            break
    return out

def gate(pool, q):
    return _filter_and_rank(pool, q, min_distinctive=2, min_coverage=0.30)[:POOL_BUDGET]

gold_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_final_gold.json")
gold = json.load(open(gold_path, encoding="utf-8"))

# ---- A) POOL-MISS 4건 chunk lane 구제 확인 (0콜) --------------------------------
print("=== A) POOL-MISS 4건: chunk lane 구제? ===")
miss = ["afd156a9", "329fb315", "f66a777d", "77f9a2b2"]
for g in gold:
    if g["row_id"][:8] in miss:
        target = g["row_id"]
        p0 = pool5(g["query"], use_chunk=False)
        p1 = pool5(g["query"], use_chunk=True)
        h0 = target in [r["id"] for r in p0]
        h1 = target in [r["id"] for r in p1]
        p0r = next((i+1 for i, r in enumerate(p0) if r["id"] == target), None)
        p1r = next((i+1 for i, r in enumerate(p1) if r["id"] == target), None)
        print(f"  {target[:14]}: base pool={h0}(rank {p0r})  +chunk pool={h1}(rank {p1r})")

# ---- B) gold 19 전체: chunk lane 효과 (0콜) -------------------------------------
print("\n=== B) gold 19: pool/gate base vs +chunk ===")
resB = []
for g in gold:
    q = g["query"]; target = g["row_id"]
    p0 = pool5(q, False); f0 = gate(p0, q)
    p1 = pool5(q, True);  f1 = gate(p1, q)
    resB.append((target[:14],
                 target in [r["id"] for r in p0], target in [r["id"] for r in f0],
                 target in [r["id"] for r in p1], target in [r["id"] for r in f1]))
print(f"pool: base {sum(r[1] for r in resB)}/19  +chunk {sum(r[3] for r in resB)}/19")
print(f"gate: base {sum(r[2] for r in resB)}/19  +chunk {sum(r[4] for r in resB)}/19")
new = [r for r in resB if not r[1] and r[3]]
print(f"NEW pool: {len(new)} {[r[0] for r in new]}")
newg = [r for r in resB if not r[2] and r[4]]
print(f"NEW gate: {len(newg)} {[r[0] for r in newg]}")

# ---- C) all-candidate snippet vs head (production 형태, Jev 무료 레인) ----------
print("\n=== C) all-candidate snippet Jev lift (gold, gate-pass rows) ===")
from jev_mem_core.pipeline import _jev_client
client = _jev_client()

def query_window(content, query, win=300):
    c = body(content)
    qt = _tokenize(query) - _STOPWORDS
    if not qt:
        return c[:win]
    best_start, best_score = 0, -1
    for start in range(0, max(1, len(c) - win + 1), 50):
        seg = c[start:start+win]
        score = len(qt & _tokenize(seg))
        if score > best_score:
            best_score, best_start = score, start
    return c[best_start:best_start+win]

def labels_for(pool, query, mode):
    out = []
    for r in pool:
        content = r.get("content") or ""
        if mode == "head":
            out.append(j1p._excerpt(content, 100) or "n/a")
        elif mode == "target":  # gold을 제외한 후보인지 모르므로 여기선 미사용
            out.append(j1p._excerpt(content, 100) or "n/a")
        elif mode == "all":
            if len(content) > 800:
                out.append(j1p._excerpt(query_window(content, query, 300), 150) or "n/a")
            else:
                out.append(j1p._excerpt(content, 100) or "n/a")
    return out

def run_choice(query, pool, labels):
    try:
        state = j1p.build_state(query, pool)
        return j1p._jev_choice(client, state, labels, timeout=20.0)
    except Exception as e:
        return f"ERR:{str(e)[:50]}"

pick_head = []
pick_all = []
for g in gold:
    q = g["query"]; target = g["row_id"]
    p1 = pool5(q, True)  # 현재 운영 상태(+chunk는 아직 미적용이지만 라벨 비교엔 무관)
    f1 = gate(p1, q)
    if target not in [r["id"] for r in f1]:
        continue
    pos = [r["id"] for r in f1].index(target)
    lb = labels_for(f1, q, "head")
    la = labels_for(f1, q, "all")
    ib = run_choice(q, f1, lb); time.sleep(0.6)
    ia = run_choice(q, f1, la); time.sleep(0.6)
    pick_head.append(ib == pos)
    pick_all.append(ia == pos)
    print(f"  {target[:14]} pos={pos+1} head={ib==pos} all={ia==pos}")
print(f"lift: head {sum(pick_head)}/{len(pick_head)}  all-snippet {sum(pick_all)}/{len(pick_all)}")

print("\nDONE")