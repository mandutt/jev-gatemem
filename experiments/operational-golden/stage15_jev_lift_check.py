"""Stage-15: does Jev actually LIFT the recovered gold rows to #1?

gate-pass at cut N != Jev picks it. For the 6 gold rows whose gate rank is
44-104 (recovered only at budget 60/80/100), call the REAL Jev choice API
(free lane) with the filtered pool at cuts 40/60/80/100 and check whether the
gold row is picked as #1 (idx == its position, i.e. lifted to rank 1).

2 repetitions per call to account for nondeterminism.
Budget: 6 rows x 4 cuts x 2 reps = up to 48 calls (free lane, small).
"""
import os, re, sqlite3, json, sys, winreg, time
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

# --- load EXPLABS keys from HKCU (free lane) ---
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
print("keys present:", bool(os.environ.get("EXPLABS_API_KEY")), bool(os.environ.get("EXPLABS_API_KEY2")), bool(os.environ.get("TYPESAFE_API_KEY")))

import mnemosyne.core.beam as beam_mod
from gateway import j1_pipeline as j1p
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search

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

# client (write_gate._jev_client pattern -> direct)
from gateway import write_gate as wg
from jev_mem_core.pipeline import _jev_client as core_jev_client

client = core_jev_client()
if client is None:
    print("WARN: core _jev_client returned None — keys?", [bool(os.environ.get(k)) for k in ("EXPLABS_API_KEY","EXPLABS_API_KEY2","TYPESAFE_API_KEY")])
print(f"client: {type(client)} url={getattr(client,'_jev_api','?')}")
TARGETS = [
    ("0e2418bbc4d68f1a", "② 3차 외부 검토 지시문(2×2 설계 확정 + 후회율 감사 프로토콜) 초안을 작성해줘", 44),
    ("97bca6e26edd3c63", "시각 프리픽스 삽입을 할 경우, 메모리 호출에 문제가 생기거나 할 가능성은 없어?", 44),
    ("8c43c4f6bd49a0cd", "② 3차 외부 검토 지시문(2×2 설계 확정 + 후회율 감사 프로토콜) 초안을 작성해줘", 46),
    ("01dfeb21681e2ace", "방금 네가 지적한 메모리 문제 때문에 나는 모델 하나만으로 다 끝낼 수 있는 경우를 찾고 있어. 참고로 jevk5는 jev랑은 다른 모델인데, 그 모델도 vec lane은 안되나?", 51),
    ("f76a006d20729049", "이건 현재까지의 우리 데이터에 기반한 거지 만약 내가 장문의 보고서를 입력한다던가 하면 걸릴 수 있는 문제 아닐까?", 66),
    ("77fff37228bff51b", "r3를 다시 하기 전에, r2에서 제시된 실험이나 수정내역은 모두 적용되었어? 나는 ai에 물어보는 라운드 이전 내용을 확인하고 싶어", 87),
]
# gold queries come from stage2_final_gold.json for accuracy
gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_final_gold.json"), encoding="utf-8"))
qmap = {g["row_id"]: g["query"] for g in gold}

client = core_jev_client()
from gateway.write_gate import _post_systemone

time.sleep(0.5)

def run_choice(query, rows, cutoff):
    """Return (idx, abstained, err) — idx is the chosen pool index (0-based)."""
    pool = rows[:cutoff]
    if not pool:
        return None, False, "empty"
    try:
        from gateway.j1_pipeline import build_state
        state = build_state(query, pool)
        labels = [j1p._excerpt((c.get("content") or ""), 100) or "n/a" for c in pool]
        idx = j1p._jev_choice(client, state, labels, timeout=20.0)
        return idx, (idx == len(labels)), None
    except Exception as e:
        return None, False, str(e)[:100]

results = []
for rid, fallback_q, gr in TARGETS:
    q = qmap.get(rid, fallback_q)
    pool = build_lane_pool(recall_raw, q)
    f = _filter_and_rank(pool, q)
    fids = [r.get("id") for r in f]
    gold_pos = fids.index(rid) + 1 if rid in fids else None
    if gold_pos is None:
        results.append((rid[:14], gr, None, "not-in-gate"))
        continue
    print(f"\n=== {rid[:14]} gate_rank={gold_pos} ===")
    for N in (40, 60, 80, 100):
        if gold_pos > N:
            print(f"  cut {N}: gold not in pool (rank {gold_pos})")
            continue
        picks = []
        for rep in range(2):
            idx, abst, err = run_choice(q, f, N)
            if err:
                picks.append(f"ERR:{err}")
            elif abst:
                picks.append("ABSTAIN")
            elif idx is None:
                picks.append("NO-PICK")
            else:
                # is the gold at idx?
                picked_id = fids[idx] if idx < len(fids) and idx < N else None
                is_gold = (picked_id == rid)
                picks.append(f"{'GOLD#1' if is_gold else 'other'} (idx={idx})")
            time.sleep(0.8)
        print(f"  cut {N}: {' | '.join(picks)}")
    results.append((rid[:14], gr, gold_pos, "done"))

print("\n=== SUMMARY ===")
for rid, gr, gp, note in results:
    print(f"  {rid} stage13_gr={gr} actual_gate_rank={gp} {note}")
conn.close()
print("\nDONE")