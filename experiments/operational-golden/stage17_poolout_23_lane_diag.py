import json, os, sys, sqlite3
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")

import sqlite_vec
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

import mnemosyne.core.beam as beam_mod
from mnemosyne.core import embeddings as emb_mod
from gateway.j1_pipeline import _imp_search, _graph_lane_search

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
gold_all = json.load(open(os.path.join(DATA, "golden_eval_v2.json"), encoding="utf-8"))
q2g = {g["query"]: g.get("gold_id") for g in gold_all}
rows = json.load(open(os.path.join(DATA, "stage16_poolout_23_gold_content.json"), encoding="utf-8"))

# FTS: 어휘 게이트 확인 — gold content에서 쿼리 토큰이 얼마나 매칭되는지
# vec: gold의 vec 순위 (top-k에서 몇 위인지)
# imp: importance >= 0.85 여부
# graph: gold가 graph lane에 붙는지

def fts_query_tokens(query):
    # min_coverage (1, 0.0) — 1토큰이라도 매칭되면 통과. 실질 매칭 토큰 수 확인
    return set(query.replace("?", "").split())

def tokenize_ko(text):
    # 간단 분리: 공백 + 특수문자 제거
    import re
    return set(re.findall(r"[a-zA-Z0-9_가-힣]+", text.lower()))

out = []
for r in rows:
    q = r["query"]
    gid = r["gold_id"]
    content = r["gold_content"]
    rec = {"query": q, "cat": r["cat"], "gold_id": gid}
    if not content:
        rec["err"] = "no-content"
        out.append(rec)
        continue

    qt = fts_query_tokens(q)
    ct = tokenize_ko(content)
    # FTS 매칭: 쿼리 토큰 중 gold content에 있는 것
    matched = [t for t in qt if t.lower() in ct]
    rec["query_tokens"] = sorted(qt)
    rec["matched_tokens_in_gold"] = matched
    rec["n_match"] = len(matched)

    # vec 순위: gold 임베딩과 쿼리 임베딩 유사도 → top-k 랭크
    try:
        qemb = emb_mod.embed([q])
        if qemb and len(qemb):
            top = beam_mod._wm_vec_search(conn, qemb[0], k=200)
            # episodic도?
            top_ep = beam_mod._ep_vec_search(conn, qemb[0], k=50) if hasattr(beam_mod, "_ep_vec_search") else []
            rank_w = next((i + 1 for i, x in enumerate(top) if x.get("id") == gid), None)
            rank_e = next((i + 1 for i, x in enumerate(top_ep) if x.get("id") == gid), None)
            rec["vec_rank_working"] = rank_w
            rec["vec_rank_episodic"] = rank_e
    except Exception as e:
        rec["vec_err"] = str(e)[:80]

    # imp lane
    try:
        imp = _imp_search(conn, k=50)
        imp_ids = {x.get("id") for x in imp}
        rec["in_imp"] = gid in imp_ids
    except Exception as e:
        rec["imp_err"] = str(e)[:80]

    # graph lane
    try:
        gr = _graph_lane_search(conn, q, k=50)
        gr_ids = {x.get("id") for x in gr}
        rec["in_graph"] = gid in gr_ids
    except Exception as e:
        rec["graph_err"] = str(e)[:80]

    out.append(rec)
    print(f"[{rec['cat']}] {q[:40]} | match={rec.get('n_match')} vec_w={rec.get('vec_rank_working')} vec_e={rec.get('vec_rank_episodic')} imp={rec.get('in_imp')} graph={rec.get('in_graph')}", flush=True)

with open(os.path.join(DATA, "stage17_poolout_23_lane_diag.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("\n저장:", os.path.join(DATA, "stage17_poolout_23_lane_diag.json"))