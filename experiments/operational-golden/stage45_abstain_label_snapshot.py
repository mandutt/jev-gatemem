"""stage45: abstain 라벨 문구 재검증 — 스냅샷 기준 (2026-10-06)

세 AI(A·B·C) 공통 제안 문구 vs 현행 문구. 위치는 cN 고정(위치 무효과 실측).
- op 90 + noans 50 (스냅샷+신선 셋) × 2 = 280콜
- 기준선 (stage44): cN_current hit@3 78, noans FP 27
- 개선 문구: "No candidate contains the specific fact, value, version, or decision
  the question asks for — same-topic mention alone is not evidence"
"""
import sys, os, time, json, sqlite3, sqlite_vec
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware")

from gateway import j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\snapshots\mnemosyne_snapshot_20261006.db"
DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"

ABSTAIN_CURRENT = "No candidate is usable evidence for answering the question"
ABSTAIN_IMPROVED = (
    "No candidate contains the specific fact, value, version, or decision the "
    "question asks for — same-topic mention alone is not evidence"
)
# v3: improved + 원인/이유 질문 수용 (stage45에서 '코덱스 원인' 손실 구제 목적)
ABSTAIN_V3 = (
    "No candidate contains the specific fact, value, version, decision, or "
    "explanation the question asks for (an explanation of a cause or reason "
    "counts as evidence) — same-topic mention alone is not evidence"
)
# v4: 조건부 원인 수용 — WHY/원인 질문만 explanation 허용, 시점/규칙은 여전히 불충분
ABSTAIN_V4 = (
    "No candidate contains the specific fact, value, version, decision, or cause "
    "the question asks for. When the question asks WHY or about a cause, an "
    "explanation of that cause counts as evidence. But a memory that merely "
    "shares the topic without stating the specific fact, value, version, "
    "decision, or cause is not evidence"
)
INSTR = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. Consider directness and specificity. "
    "If none of the candidates contains usable evidence, pick the 'no candidate' option."
)

conn = sqlite3.connect(SNAP)
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

raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
op_qs = list(base.keys())
noans_qs = [n["query"] for n in json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))]
queries = op_qs + noans_qs
print(f"op {len(op_qs)} + noans {len(noans_qs)} = {len(queries)}콜 × 2", flush=True)

def run_choice(query, abstain_label):
    pool = j1p.build_lane_pool(recall_raw, query)
    if not pool: return None, 0.0, None, 0, "no-pool"
    filtered = j1p._filter_and_rank(pool, query) if pool else []
    rows = filtered[:j1p.POOL_BUDGET]
    if not rows: return None, 0.0, None, 0, "no-filtered"
    labels = [
        j1p._excerpt(j1p._query_window((c.get("content") or ""), query, 300), 150)
        or "n/a" for c in rows
    ]
    state = j1p.build_state(query, rows)
    j_labels = labels + [abstain_label]
    questions = {
        "best": {"type": "choice", "instructions": INSTR,
                 "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}
    }
    try:
        import os as _os
        _api = getattr(client, "_jev_api", None) or (
            _os.environ.get("JEV_API_URL") or "https://api.typesafe.ai/v1/systemone")
        resp = client.post(_api, json={"state": state, "questions": questions,
                                       "model": "jev-latest"}, timeout=10.0)
        if resp.status_code == 429:
            rot = getattr(client, "_jev_rotator", None)
            keys = getattr(client, "_jev_keys", None)
            if rot is not None and keys is not None and len(keys) > 1:
                nk = rot.on_429()
                if nk:
                    client.headers["Authorization"] = f"Bearer {nk}"
                    resp = client.post(_api, json={"state": state, "questions": questions,
                                                   "model": "jev-latest"}, timeout=10.0)
        if resp.status_code != 200:
            # 503(일시 장애) 1회 재시도 (429는 위에서 키 전환 처리)
            if resp.status_code == 503:
                time.sleep(1.0)
                resp = client.post(_api, json={"state": state, "questions": questions,
                                               "model": "jev-latest"}, timeout=10.0)
            if resp.status_code != 200:
                return None, 0.0, None, len(rows), f"http-{resp.status_code}"
        ans = (resp.json().get("answers") or {}).get("best") or {}
        choice = ans.get("choice")
        probs = ans.get("probabilities") or {}
        abstain_p = float(probs.get(f"c{len(j_labels)-1}", 0.0) or 0.0) if probs else 0.0
        if choice is None:
            return None, abstain_p, None, len(rows), "no-choice"
        idx = int(str(choice).lstrip("c"))
        if idx == len(j_labels) - 1 or abstain_p > 0.3:
            return None, abstain_p, None, len(rows), None  # abstain
        pick_id = rows[idx]["id"] if 0 <= idx < len(rows) else None
        gid = base.get(query, {}).get("gold_id")
        rank = None
        if gid and pick_id:
            ids = [pick_id] + [c["id"] for c in rows if c["id"] != pick_id]
            rank = ids.index(gid) + 1 if gid in ids else None
        return idx, abstain_p, rank, len(rows), None
    except Exception as e:
        return None, 0.0, None, len(rows), type(e).__name__

runs = []
for cond, label in [("current", ABSTAIN_CURRENT), ("improved", ABSTAIN_IMPROVED)]:
    print(f"\n=== {cond} 시작 ===", flush=True)
    recs = []
    for i, q in enumerate(queries, 1):
        t0 = time.perf_counter()
        idx, abstain_p, rank, pool_n, err = run_choice(q, label)
        recs.append({
            "query": q, "gold_id": base.get(q, {}).get("gold_id"),
            "grp": "op" if base.get(q, {}).get("gold_id") else "noans",
            "abstained": idx is None and err is None,
            "abstain_p": round(abstain_p, 3),
            "gold_rank": rank if not err else None,
            "pool_n": pool_n, "err": err,
            "lat_ms": int((time.perf_counter() - t0) * 1000),
        })
        if i % 50 == 0:
            print(f"  {i}/{len(queries)}", flush=True)
    runs.append({"cond": cond, "records": recs})
    print(f"{cond} 완료", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "abstain-label-snapshot-final",
           "runs": runs},
          open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

print("\n=== 요약 (스냅샷 기준) ===")
for run in runs:
    op = [r for r in run["records"] if r["grp"] == "op"]
    na = [r for r in run["records"] if r["grp"] == "noans"]
    h1 = sum(1 for r in op if r["gold_rank"] is not None and r["gold_rank"] <= 1)
    h3 = sum(1 for r in op if r["gold_rank"] is not None and r["gold_rank"] <= 3)
    abs_n = sum(1 for r in op if r["abstained"])
    fp = sum(1 for r in na if not r["abstained"] and not r["err"])
    err = sum(1 for r in run["records"] if r["err"])
    print(f"  {run['cond']:9} | hit@1={h1:2} hit@3={h3:2} abstain={abs_n:2} | noans FP={fp:2}/50 | err={err}")
print("저장 완료: stage45_v4_snapshot.json")
conn.close()