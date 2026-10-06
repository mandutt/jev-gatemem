# -*- coding: utf-8 -*-
"""stage65: 규칙 행 캡 1 JEV 검증 (2026-10-07, 140콜)

stage64 0콜 시뮬: 규칙 행 캡 1(top5에 규칙 1개만) → gold top5 17→52 (+35).
JEV 재호출로 실제 hit·abstain 확인:
- base: 현행 top5 (캡 없음)
- cap1: 규칙 행 캡 1 top5 + abstain 라벨
셋: op-90. KPI: hit@1 (abstain 제외) · abstain 수 · noans 방어 유지.
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

# 규칙 행 id (빈도 상위 5 + 아키텍처) — m48.build_pool의 60 pool에서 추출
RULE_IDS = {
    "d1c90516d9870c95", "2ecef73164830638", "9f04ed2c8e14f11b",
    "5a3ebc06a87940da", "a13019e1f438960c", "1cef4743165b7707",
}

def top5_with_cap(pool, cap):
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

def run_choice(q, rows, meta_cap):
    use = top5_with_cap(rows, 1) if meta_cap else rows[:5]
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

d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
print(f"op-90: {len(op)}건", flush=True)

pools = {i: m48.build_pool(s, q) for i, (q, g) in enumerate(op)}
print("pool 구성 완료", flush=True)

def gold_after_of(pool, g, idx, abstain, is_cap):
    """choice 후 gold 순위 — base는 rows[:5], cap은 top5_with_cap"""
    if abstain: return None
    use = top5_with_cap(pool, 1) if is_cap else pool[:5]
    gold_i = next((i for i, p in enumerate(use) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
    if gold_i is None: return None
    if idx is None or not isinstance(idx, int): return gold_i + 1
    return 1 if idx == gold_i else (gold_i + 2 if idx > gold_i else gold_i + 1)

results = {"base": [], "cap1": []}
t0 = time.time()
for cond, is_cap in (("base", False), ("cap1", True)):
    for i, (q, g) in enumerate(op):
        pool = pools[i]
        idx, abst, ap, err = run_choice(q, pool, is_cap)
        ga = None if abst else gold_after_of(pool, g, idx, abst, is_cap)
        results[cond].append({"query": q, "gold": g, "abstain": abst, "abstain_p": ap,
                              "choice_idx": idx, "gold_after": ga, "err": err})
    h1 = sum(1 for r in results[cond] if r["gold_after"] == 1)
    h3 = sum(1 for r in results[cond] if r["gold_after"] is not None and r["gold_after"] <= 3)
    abst_n = sum(1 for r in results[cond] if r["abstain"] and not r["err"])
    err_n = sum(1 for r in results[cond] if r["err"])
    print(f"{cond}: hit@1 {h1} · hit@3 {h3} · abstain {abst_n} · err {err_n} ({time.time()-t0:.0f}s)", flush=True)

json.dump(results, open(os.path.join(DATA, "stage65_cap1_jev.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage65_cap1_jev.json")

# 대조: base에서 abstain인데 cap1에서 hit된 쿼리 (구제)
print("\n=== cap1에서 회복된 쿼리 (base abstain → cap1 hit) ===")
for b, c in zip(results["base"], results["cap1"]):
    if b["abstain"] and c["gold_after"] == 1 and not c["err"]:
        print(f"  {c['query'][:55]}")
print("\n=== cap1에서 abstain 유지/추가된 쿼리 ===")
for b, c in zip(results["base"], results["cap1"]):
    if not b["abstain"] and c["abstain"] and c["cls"] == "rule" if "cls" in c else False: pass
for b, c in zip(results["base"], results["cap1"]):
    if not b["abstain"] and c["abstain"]:
        print(f"  신규 abstain: {c['query'][:55]}")