# -*- coding: utf-8 -*-
"""stage66: 캡 1 — noans-50 + 라이브 60 검증 (2026-10-07, 110콜)

stage65: op-90 캡 1 hit@1 66, 오차단 0. 채택 전 확인:
- noans-50: FP 유지? (하드 무답도 abstain? — 캡 후에도)
- 라이브 60: block(IRREL) abstain 유지? valid/yes 오차단?
"""
import os, sys, json, sqlite3, time

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client

SNAP = m48.SNAP
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row

ABSTAIN_CUR = m48.ABSTAIN_CURRENT
INSTR = m48.INSTR

RULE_IDS = {
    "d1c90516d9870c95", "2ecef73164830638", "9f04ed2c8e14f11b",
    "5a3ebc06a87940da", "a13019e1f438960c", "1cef4743165b7707",
}

def top5_with_cap(pool, cap=1):
    top = []
    rule_cnt = 0
    for p in pool:
        if (p.get("id") or "")[:16] in RULE_IDS:
            if rule_cnt >= cap: continue
            rule_cnt += 1
        top.append(p)
        if len(top) >= 5: break
    return top

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

def run_choice(q, rows, cap):
    use = top5_with_cap(rows, cap) if cap else rows[:5]
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
    abstain = (idx == len(jl)-1) or (ap > 0.3)
    return idx, abstain, ap, None

# noans-50
no = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
# 라이브 60 (human verdicts)
queries = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}

print(f"noans-50 + 라이브 60 | cls { {k: sum(1 for q in queries if q_cls.get(q)==k) for k in ('block','valid','yes')} }", flush=True)

# 풀 구성
no_pools = {i: m48.build_pool(s, n["query"]) for i, n in enumerate(no)}
lv_pools = {q: m48.build_pool(s, q) for q in queries}
print("pool 구성 완료", flush=True)

res = {"noans": [], "live": []}
t0 = time.time()
# noans-50 (base vs cap1)
for cond, cap in (("noans_base", 0), ("noans_cap1", 1)):
    for i, n in enumerate(no):
        idx, abst, ap, err = run_choice(n["query"], no_pools[i], cap)
        res["noans"].append({"qid": n["qid"], "cond": cond, "abstain": abst, "abstain_p": ap, "err": err})
    fp = sum(1 for r in res["noans"] if r["cond"] == cond and not r["err"] and not r["abstain"])
    abst_n = sum(1 for r in res["noans"] if r["cond"] == cond and r["abstain"] and not r["err"])
    print(f"{cond}: FP {fp}/50 · abstain {abst_n}/50 ({time.time()-t0:.0f}s)", flush=True)

# 라이브 60 (base vs cap1)
for cond, cap in (("live_base", 0), ("live_cap1", 1)):
    for q in queries:
        idx, abst, ap, err = run_choice(q, lv_pools[q], cap)
        res["live"].append({"query": q, "cls": q_cls.get(q), "cond": cond, "abstain": abst, "abstain_p": ap, "err": err})
    blk_abst = sum(1 for r in res["live"] if r["cond"] == cond and r["cls"] == "block" and r["abstain"] and not r["err"])
    val_abst = sum(1 for r in res["live"] if r["cond"] == cond and r["cls"] in ("valid", "yes") and r["abstain"] and not r["err"])
    print(f"{cond}: block abstain {blk_abst}/38 · valid+yes 오차단 {val_abst}/22 ({time.time()-t0:.0f}s)", flush=True)

json.dump(res, open(os.path.join(DATA, "stage66_cap1_noans_live.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage66_cap1_noans_live.json")