"""Stage-26: gold 비선택 9건 VALID/PLAUS/IRREL 판정 (b-ai #4).

b-ai: "게이트 통과 ≠ Jev lift" — gold를 고르지 않은 9건을 3분류:
  A. VALID — 다른 후보가 사실상 같은 답을 담음 (gold exact-ID 지표의 인공물)
  B. PLAUS — 다른 후보도 관련 있지만 gold보다 답이 약함
  C. IRREL — 완전히 잘못 고름

stage17/18에서 Jev가 실제로 고른 후보의 content를 추출해 사람이 판정할 수 있게 출력.
Jev 호출 재사용: stage23의 all-snippet run에서 gold를 못 고른 케이스의 pick index.
"""
import os, re, sqlite3, json, sys
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

from gateway import j1_pipeline as j1p
from gateway.j1_pipeline import _filter_and_rank, _imp_search, _graph_lane_search, POOL_BUDGET

def body(c):
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "stage2_final_gold.json"), encoding="utf-8"))

# stage23 all-snippet 결과에 나온 gate-pass 16건 대상:
# head/all에서 gold를 못 고른 케이스 (all 기준 gold miss) — Jev가 뭘 골랐는지 content로 출력
# stage23 실행 결과: lift head 3/16, all 5/16. all에서 gold를 못 고른 11건 중
# 실제로 Jev가 고른 후보(다른 행)를 보여준다.

# pool 재현 (chunk 없이 4-lane 운영 상태) — stage23과 동일
import mnemosyne.core.beam as beam_mod

def pool4(q):
    ranks = {}
    def add(kind, rows):
        for i, r in enumerate(rows, start=1):
            ranks.setdefault(r["id"], {})[kind + "_rank"] = i
    add("fts", beam_mod._fts_search_working(conn, q, k=60))
    qemb = beam_mod._embeddings.embed([q])
    if qemb is not None and len(qemb):
        add("vec", beam_mod._wm_vec_search(conn, qemb[0], k=60))
    add("imp", _imp_search(conn, k=8))
    add("graph", _graph_lane_search(conn, q, k=10))
    K = 60
    rr = {rid: sum(1.0/(K+v) for v in rk.values()) for rid, rk in ranks.items()}
    order = sorted(rr, key=lambda x: -rr[x])
    out = []
    for rid in order:
        r = conn.execute("SELECT id, content, source, importance FROM working_memory WHERE id=?", (rid,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, source, importance FROM episodic_memory WHERE id=?", (rid,)).fetchone()
        if r:
            out.append({"id": r[0], "content": r[1], "source": r[2], "importance": r[3]})
            if len(out) >= POOL_BUDGET:
                break
    return _filter_and_rank(out, q, min_distinctive=2, min_coverage=0.30)[:POOL_BUDGET]

# stage23 all-snippet에서 Jev가 gold가 아닌 다른 후보를 고른 케이스의 pick을 재현
# (Jev 호출 1회씩 — 무료 레인, 11건)
from jev_mem_core.pipeline import _jev_client
client = _jev_client()

def query_window(content, query, win=300):
    c = body(content)
    qt = j1p._tokenize(query) - j1p._STOPWORDS
    if not qt:
        return c[:win]
    best_start, best_score = 0, -1
    for start in range(0, max(1, len(c) - win + 1), 50):
        seg = c[start:start+win]
        score = len(qt & j1p._tokenize(seg))
        if score > best_score:
            best_score, best_start = score, start
    return c[best_start:best_start+win]

def labels_all(pool, query):
    out = []
    for r in pool:
        content = r.get("content") or ""
        if len(content) > 800:
            out.append(j1p._excerpt(query_window(content, query, 300), 150) or "n/a")
        else:
            out.append(j1p._excerpt(content, 100) or "n/a")
    return out

results = []
for g in gold:
    q = g["query"]; target = g["row_id"]
    f = pool4(q)
    fids = [r["id"] for r in f]
    if target not in fids:
        continue
    pos = fids.index(target)
    labels = labels_all(f, q)
    try:
        state = j1p.build_state(q, f)
        pick = j1p._jev_choice(client, state, labels, timeout=20.0)
    except Exception as e:
        print(f"  {target[:14]} ERR {e}")
        continue
    if pick == pos:
        continue  # gold 골랐으면 제외
    picked = f[pick] if pick is not None and pick < len(f) else None
    # gold 행 content 시그니처 (첫 150자)
    gr = conn.execute("SELECT content FROM working_memory WHERE id=?", (target,)).fetchone()
    if not gr:
        gr = conn.execute("SELECT content FROM episodic_memory WHERE id=?", (target,)).fetchone()
    gsig = body(gr["content"])[:150] if gr else "?"
    psig = body(picked["content"])[:150] if picked else "?"
    results.append({
        "gold_id": target[:14], "query": q[:60],
        "gold_sig": gsig, "picked_id": (picked["id"][:14] if picked else None),
        "picked_sig": psig, "picked_source": (picked.get("source") if picked else None),
    })

print(f"=== stage26: gold 미선택 {len(results)}건 — 판정 입력 ===")
for i, r in enumerate(results, 1):
    print(f"\n--- {i}. gold {r['gold_id']}  (miss) ---")
    print(f"  QUERY: {r['query']}")
    print(f"  GOLD 첫150: {r['gold_sig']}")
    print(f"  PICKED {r['picked_id']} (src={r['picked_source']}) 첫150: {r['picked_sig']}")
print("\n판정: 각 건 A(VALID=같은 답)/B(PLAUS=관련 약함)/C(IRREL=틀림) 한 글자씩")
conn.close()