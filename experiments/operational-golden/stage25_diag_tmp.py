import json, os, sys, time, sqlite3, urllib.request, urllib.error, traceback
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")

from keyring import SmartRotator
rot = SmartRotator()

URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"
CHOICE_INSTR = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. Consider directness and specificity. "
    "If no candidate is usable evidence for answering the question, pick the last option."
)

def post(url, body, key, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                rot.on_429(); time.sleep(1.5 * (attempt + 1)); continue
            return e.code, {"__msg": str(e)}
        except Exception:
            time.sleep(1.5)
    return -1, {"__msg": "timeout"}

def choice_call_full(key, query, labels):
    j_labels = list(labels) + [ABSTAIN_LABEL]
    body = {"model": MODEL, "state": {"question": query, "candidates": []},
            "questions": {"best": {"type": "choice", "instructions": CHOICE_INSTR,
                                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}}
    status, resp = post(URL, body, key)
    if status != 200:
        return None, f"http-{status}"
    rot.set_cost((resp.get("usage") or {}).get("cost", None))
    ans = (resp.get("answers") or {}).get("best") or {}
    return ans, None

import sqlite_vec
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)
import mnemosyne.core.beam as beam_mod
from mnemosyne.core import embeddings as emb_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search, POOL_BUDGET

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = emb_mod.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return _imp_search(conn, k=k)
    if kind == "graph": return _graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "importance": r[2]}
    return []

# 첫 op 쿼리 3건만 테스트 (수동 로그)
DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
op = [base[q] for q in base][:3]

for r in op:
    q = r["query"]; gid = r["gold_id"]
    print(f"\n--- query: {q[:40]} ---", flush=True)
    try:
        pool = build_lane_pool(recall_raw, q)
        print(f"  build_lane_pool: {len(pool)}", flush=True)
        filtered = _filter_and_rank(pool, q) if pool else []
        print(f"  _filter_and_rank: {len(filtered)}", flush=True)
        pool60 = filtered[:POOL_BUDGET]
        print(f"  pool60: {len(pool60)}", flush=True)
        gid_in = any(c.get("id") == gid for c in pool60)
        print(f"  gold in pool60: {gid_in}", flush=True)
    except Exception as e:
        print(f"  EXC: {type(e).__name__}: {str(e)[:120]}", flush=True)
        traceback.print_exc()
conn.close()
print("DONE", flush=True)