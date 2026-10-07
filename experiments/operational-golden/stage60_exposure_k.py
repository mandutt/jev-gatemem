# -*- coding: utf-8 -*-
"""stage60: 노출 k 실험 (2026-10-06, JEV 180콜)

A AI: 실노출 rows[:5] → rows[:2~3] — 무관 노출 60% 감소, hit@k 실측상 정답 손실 0 (stage57).
검증: k=5/3/2를 라이브 60에 같은 세션 적용.
- block abstain이 k 축소로 늘어나는가 (softmax 집중 — pool20에서 본 효과)
- valid/yes 정답이 k 밖으로 밀려 오차단되는가
- abstain_p 분포 변화
콜: 60 × 3 = 180콜 (err 0 목표)
"""
import os, sys, json, sqlite3, time

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod
from jev_mem_core.pipeline import _jev_client

SNAP = m48.SNAP
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row

ABSTAIN_CUR = m48.ABSTAIN_CURRENT
INSTR = m48.INSTR

def recall_raw_factory(q):
    def recall_raw(kind, arg, kk):
        if kind == "fts": return beam_mod._fts_search_working(s, arg, k=kk)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(s, qemb[0], k=kk)
        if kind == "imp": return j1p._imp_search(s, k=kk)
        if kind == "graph": return j1p._graph_lane_search(s, arg, kk)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw

def build_pool(q):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    return j1p._filter_and_rank(pool, q)[:60]

CLIENT = _jev_client(); assert CLIENT
_API = getattr(CLIENT, "_jev_api", None)
_rot_i = getattr(CLIENT, "_jev_rotator", None)
if _rot_i is not None and hasattr(_rot_i, "_active"):
    _act = _rot_i._active()
    if len(_act) >= 2:
        CLIENT.headers["Authorization"] = f"Bearer {_act[1][1]}"
        sys.stderr.write(f"[start] {_act[1][0]}\n")

_LAST_CALL = [0.0]
def throttle():
    while True:
        now = time.time()
        if now - _LAST_CALL[0] >= 0.34:
            _LAST_CALL[0] = now; return
        time.sleep(0.05)

def post(state, questions):
    rot = getattr(CLIENT, "_jev_rotator", None)
    for attempt in range(10):
        throttle()
        try:
            resp = CLIENT.post(_API, json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=25)
            if resp.status_code == 429:
                if rot is not None and hasattr(rot, "on_429"):
                    try: nk = rot.on_429()
                    except Exception: nk = None
                    if nk: CLIENT.headers["Authorization"] = f"Bearer {nk}"
                time.sleep(2.0); continue
            if resp.status_code == 503:
                time.sleep(3.0); continue
            return resp
        except Exception:
            time.sleep(2.0)
    return None

def run_choice(q, rows, k):
    use = rows[:k]
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in use]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, use)
    qs = {"best": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200:
        return None, None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    abstain = (idx is None) or (idx == len(jl)-1) or (ap > 0.3)
    return idx, abstain, ap, None

queries = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}
print(f"라이브 60: {len(queries)}건 | cls { {k: sum(1 for q in queries if q_cls.get(q)==k) for k in ('block','valid','yes')} }", flush=True)

pools = {q: build_pool(q) for q in queries}
print("pool 구성 완료", flush=True)

conds = [("k5", 5), ("k3", 3), ("k2", 2)]
results = {name: [] for name, _ in conds}
t0 = time.time()
for name, k in conds:
    for qi, q in enumerate(queries, 1):
        idx, abst, ap, err = run_choice(q, pools[q], k)
        results[name].append({"query": q, "cls": q_cls.get(q), "abstain": abst, "abstain_p": ap,
                              "choice_idx": idx, "err": err, "k": len(pools[q][:k])})
    blk_abst = sum(1 for r in results[name] if r["cls"] == "block" and r["abstain"] and not r["err"])
    val_abst = sum(1 for r in results[name] if r["cls"] in ("valid", "yes") and r["abstain"] and not r["err"])
    err_n = sum(1 for r in results[name] if r["err"])
    aps = [r["abstain_p"] for r in results[name] if not r["err"]]
    med = sorted(aps)[len(aps)//2]
    print(f"{name}: block abstain {blk_abst}/38 · valid+yes 오차단 {val_abst}/22 · err {err_n} · abstain_p 중앙 {med:.3f} ({time.time()-t0:.0f}s)", flush=True)

json.dump(results, open(os.path.join(DATA, "stage60_exposure_k.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage60_exposure_k.json")

# 대조
print("\n=== k별 block abstain 변화 (k5→k2) ===")
for b, m in zip(results["k5"], results["k2"]):
    if b["cls"] == "block" and (b["abstain"] != m["abstain"]):
        print(f"  {'ABSTAIN' if m['abstain'] else 'pick'} | {b['query'][:45]}")
print("\n=== valid/yes 오차단 변화 ===")
for b, m in zip(results["k5"], results["k2"]):
    if b["cls"] in ("valid", "yes") and (b["abstain"] != m["abstain"]):
        print(f"  {b['cls']:5} k5={'A' if b['abstain'] else 'P'} k2={'A' if m['abstain'] else 'P'} | {b['query'][:45]}")
print("\n=== k별 abstain_p>0.1 건수 ===")
for name, _ in conds:
    n = sum(1 for r in results[name] if not r["err"] and r["abstain_p"] > 0.1)
    print(f"  {name}: {n}/60")