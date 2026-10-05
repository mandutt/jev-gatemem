"""stage38: abstain 라벨 문구 개선 실측 (2026-10-06)

세 AI 공통 제안: "same topic is not evidence" + 시점/버전 불일치 배제 명시.
현행 라벨: "No candidate is usable evidence for answering the question"
개선 라벨: "No candidate contains the specific fact, value, version, or decision the
            question asks for — same-topic mention alone is not evidence"

검증: noans hard 50콜 + op gold 20콜 (탈락 회귀 감시) = 70콜
비교: 현행 라벨 vs 개선 라벨 (동일 쿼리, choice-only, pool60 win-300 soft gate)
실패 기준 (A AI): noans 오주입 13→8 이하(≤16%), op 추가 abstain 1건 이상이면 롤백
"""
import sys, os, time, json, sqlite3, sqlite_vec
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware")

import re
from gateway import j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client

# 실험용 라벨 (코드 상수 오버라이드)
ABSTAIN_LABEL_IMPROVED = (
    "No candidate contains the specific fact, value, version, or decision the "
    "question asks for — same-topic mention alone is not evidence"
)

conn = sqlite3.connect(r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db")
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = emb_mod.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return j1p._imp_search(conn, k=k)
    if kind == "graph": return j1p._graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "importance": r[2]}
    return []

client = _jev_client()
print("client:", "OK" if client else "NONE", flush=True)

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
noans_qs = [n["query"] for n in json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))]
# op: gold 90 중 일부 (1~20)만 회귀 감시
op_qs = list(base.keys())[:20]
queries = [("noans", q) for q in noans_qs] + [("op", q) for q in op_qs]
print(f"noans {len(noans_qs)} + op-sample {len(op_qs)} = {len(queries)}콜 × 2 (현행/개선)", flush=True)

def run_rerank(query, label):
    """특정 abstain 라벨로 jev choice 1콜. (abstained, gold_rank, abstain_p)"""
    pool = j1p.build_lane_pool(recall_raw, query)
    filtered = j1p._filter_and_rank(pool, query) if pool else []
    rows = filtered[:j1p.POOL_BUDGET]
    if not rows:
        return False, None, 0.0, 0
    state = j1p.build_state(query, rows)
    labels = [
        j1p._excerpt(j1p._query_window((c.get("content") or ""), query, 300), 150)
        or "n/a"
        for c in rows
    ]
    # 실험: _jev_choice는 모듈 전역 ABSTAIN_LABEL 참조 — 오버라이드
    orig_abstain = j1p.ABSTAIN_LABEL
    j1p.ABSTAIN_LABEL = label
    try:
        idx, abstain_p, probs = j1p._jev_choice(client, state, labels, timeout=10.0)
    finally:
        j1p.ABSTAIN_LABEL = orig_abstain
    if idx is None:
        return False, None, abstain_p, len(rows)
    if _abstain_enabled := (os.environ.get("JEV_ABSTAIN") or "1").strip().lower() not in ("0", "false", "off", "no", "disabled"):
        if idx == len(labels):
            return True, None, abstain_p, len(rows)
        if abstain_p > j1p._SOFT_ABSTAIN_TAU:
            return True, None, abstain_p, len(rows)
    if not (0 <= idx < len(rows)):
        return False, None, abstain_p, len(rows)
    gid = base.get(query, {}).get("gold_id")
    ids = [rows[idx]["id"]] + [c["id"] for i, c in enumerate(rows) if i != idx]
    rank = (ids.index(gid) + 1) if gid and gid in ids else None
    return False, rank, abstain_p, len(rows)

results = []
for cond, label in [("current", j1p.ABSTAIN_LABEL), ("improved", ABSTAIN_LABEL_IMPROVED)]:
    print(f"\n=== {cond} 라벨 ===", flush=True)
    for i, (grp, q) in enumerate(queries, 1):
        t0 = time.perf_counter()
        abstained, rank, abstain_p, pool_n = run_rerank(q, label)
        results.append({
            "cond": cond, "grp": grp, "query": q,
            "gold_id": base.get(q, {}).get("gold_id"),
            "abstained": abstained, "gold_rank": rank,
            "abstain_p": round(abstain_p, 3), "pool_n": pool_n,
            "lat_ms": int((time.perf_counter() - t0) * 1000),
        })
        if i % 25 == 0:
            print(f"  {i}/{len(queries)}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "abstain-label-ablation",
           "records": results},
          open(os.path.join(DATA, "stage38_abstain_label.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# 요약
for cond in ["current", "improved"]:
    rs = [r for r in results if r["cond"] == cond]
    no = [r for r in rs if r["grp"] == "noans"]
    op = [r for r in rs if r["grp"] == "op"]
    no_fp = sum(1 for r in no if not r["abstained"])
    op_hit3 = sum(1 for r in op if r["gold_rank"] is not None and r["gold_rank"] <= 3)
    op_abs = sum(1 for r in op if r["abstained"])
    print(f"\n[{cond}] noans FP={no_fp}/{len(no)} ({no_fp/len(no)*100:.1f}%) | op-sample hit@3={op_hit3}/{len(op)} abstain={op_abs}")

conn.close()