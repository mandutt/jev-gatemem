"""stage44: abstain 위치 c0/cN × 지시문 2종 2×2 ablation (2026-10-06)

B AI Q4-1 제안: abstain 라벨 위치(첫번째 vs 마지막)와 지시문(현행 vs 슬롯 인지)이
noans 방어와 op 회수에 미치는 영향 측정.

- 조건: {pos: c0 | cN} × {instr: current | slot} = 4조건
- 데이터: 스냅샷 DB(20261006) + op 90 + (스냅샷 기준) noans 50
- 콜: 140쿼리 × 4조건 = 560콜 (free lane 240/분, ~4분)
  (비결정성 제거 위해 4조건 모두 동일 쿼리 실행 — 내부 paired 비교)
"""
import sys, os, time, json, sqlite3, sqlite_vec
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware")

from gateway import j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\snapshots\mnemosyne_snapshot_20261006.db"
DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"

ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"
INSTR_BASE = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. Consider directness and specificity."
)
# 현행 지시문
INSTR_CURRENT = INSTR_BASE + " If none of the candidates contains usable evidence, pick the 'no candidate' option."
# 슬롯 인지 지시문 (B AI 제안 — "마지막 옵션은 abstain 슬롯" 명시)
INSTR_SLOT = INSTR_BASE + (
    " The last option is always the 'no candidate' slot: if none of the candidate "
    "memories contains usable evidence, you MUST pick that slot."
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

# 쿼리 셋: op 90 + noans 50 (스냅샷 기준)
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
op_qs = list(base.keys())
noans = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
noans_qs = [n["query"] for n in noans]
queries = op_qs + noans_qs
print(f"op {len(op_qs)} + noans {len(noans_qs)} = {len(queries)}콜 × 4조건", flush=True)

def run_choice(query, pos, instr):
    """지정 위치/지시문으로 choice 1콜. (idx, abstain_p, gold_rank)"""
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
    # 조건부 라벨 구성
    j_labels = [ABSTAIN_LABEL] + labels if pos == "c0" else labels + [ABSTAIN_LABEL]
    questions = {
        "best": {"type": "choice", "instructions": instr,
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
            return None, 0.0, None, len(rows), f"http-{resp.status_code}"
        ans = (resp.json().get("answers") or {}).get("best") or {}
        choice = ans.get("choice")
        probs = ans.get("probabilities") or {}
        abstain_p = float(probs.get(f"c{len(j_labels)-1}", 0.0) or 0.0) if probs else 0.0
        if choice is None:
            return None, abstain_p, None, len(rows), "no-choice"
        idx = int(str(choice).lstrip("c"))
        abs_idx = 0 if pos == "c0" else len(j_labels) - 1
        is_abstain = (idx == abs_idx)
        # soft gate (cN 조건만 의미 — c0은 abstain 확률이 다름)
        if is_abstain or (pos == "cN" and abstain_p > 0.3):
            return None, abstain_p, None, len(rows), None  # abstain (idx=None으로 표시)
        # gold rank 계산
        # c0: labels[1:]가 후보 (labels[0]=abstain), cN: labels[:N]가 후보
        if pos == "c0":
            pick_id = rows[idx - 1]["id"] if 0 < idx <= len(rows) else None
        else:
            pick_id = rows[idx]["id"] if 0 <= idx < len(rows) else None
        gid = base.get(query, {}).get("gold_id")
        rank = None
        if gid and pick_id:
            ids = [pick_id] + [c["id"] for c in rows if c["id"] != pick_id]
            rank = ids.index(gid) + 1 if gid in ids else None
        return idx, abstain_p, rank, len(rows), None
    except Exception as e:
        return None, 0.0, None, len(rows), type(e).__name__

CONDS = [
    ("cN_current", "cN", INSTR_CURRENT),
    ("c0_current", "c0", INSTR_CURRENT),
    ("cN_slot", "cN", INSTR_SLOT),
    ("c0_slot", "c0", INSTR_SLOT),
]

all_records = []
for cond_name, pos, instr in CONDS:
    print(f"\n=== {cond_name} 시작 ===", flush=True)
    recs = []
    for i, q in enumerate(queries, 1):
        t0 = time.perf_counter()
        idx, abstain_p, rank, pool_n, err = run_choice(q, pos, instr)
        recs.append({
            "query": q, "gold_id": base.get(q, {}).get("gold_id"),
            "grp": "op" if base.get(q, {}).get("gold_id") else "noans",
            "idx": idx, "abstain_p": round(abstain_p, 3),
            "abstained": idx is None and err is None,
            "gold_rank": rank if not err else None,
            "pool_n": pool_n, "err": err,
            "lat_ms": int((time.perf_counter() - t0) * 1000),
        })
        if i % 50 == 0:
            print(f"  {i}/{len(queries)}", flush=True)
    all_records.append({"cond": cond_name, "records": recs})
    print(f"{cond_name} 완료", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "abstain-pos-2x2",
           "runs": all_records},
          open(os.path.join(DATA, "stage44_abstain_pos_2x2.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# 요약
print("\n=== 2×2 요약 ===")
for run in all_records:
    op = [r for r in run["records"] if r["grp"] == "op"]
    na = [r for r in run["records"] if r["grp"] == "noans"]
    h1 = sum(1 for r in op if r["gold_rank"] is not None and r["gold_rank"] <= 1)
    h3 = sum(1 for r in op if r["gold_rank"] is not None and r["gold_rank"] <= 3)
    abs_n = sum(1 for r in op if r["abstained"])
    fp = sum(1 for r in na if not r["abstained"] and not r["err"])
    err = sum(1 for r in run["records"] if r["err"])
    print(f"  {run['cond']:12} | hit@1={h1:2} hit@3={h3:2} abstain={abs_n:2} | noans FP={fp:2}/50 | err={err}")
conn.close()