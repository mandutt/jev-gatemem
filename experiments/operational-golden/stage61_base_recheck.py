# -*- coding: utf-8 -*-
"""stage61: 오늘(JEV 모델 변경 후) base 기준선 재확인 (2026-10-07, 60콜)

stage60에서 abstain_p가 어제(0.0 중앙)와 극단적으로 다름(0.95 중앙) — JEV 서버 측 변경 의심.
오늘 모델에서 base(k5, current 라벨, 시간 필터)를 라이브 60으로 재실행해 기준선 확보.
- abstain_p 분포 (0.3 초과 비율)
- block abstain 수 · valid/yes 오차단
- choice가 실제로 abstain 라벨을 고르는지 (choice_idx == len-1)
어제 stage48 cur과 동일 조건. 3-run은 기준선 확인 후.
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

def run_choice(q, rows):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows[:5]]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows[:5])
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
    # idx가 abstain 라벨(마지막)인지 별도 기록 — "진짜 abstain 선택" vs "ap>0.3"
    chose_abstain = (idx == len(jl) - 1)
    abstain = chose_abstain or (ap > 0.3)
    return idx, abstain, ap, {"chose_abstain": chose_abstain, "raw_choice": ans.get("choice")}

queries = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}
print(f"라이브 60 | cls { {k: sum(1 for q in queries if q_cls.get(q)==k) for k in ('block','valid','yes')} }", flush=True)

pools = {q: build_pool(q) for q in queries}
print("pool 구성 완료", flush=True)

recs = []
t0 = time.time()
for qi, q in enumerate(queries, 1):
    idx, abst, ap, extra = run_choice(q, pools[q])
    recs.append({"query": q, "cls": q_cls.get(q), "abstain": abst, "abstain_p": ap,
                 "choice_idx": idx, "chose_abstain": extra["chose_abstain"], "err": None})
    if qi % 20 == 0:
        print(f"  {qi}/60 ({time.time()-t0:.0f}s)", flush=True)

blk_abst = sum(1 for r in recs if r["cls"] == "block" and r["abstain"])
blk_pick = sum(1 for r in recs if r["cls"] == "block" and not r["abstain"])
val_abst = sum(1 for r in recs if r["cls"] in ("valid", "yes") and r["abstain"])
aps = sorted(r["abstain_p"] for r in recs)
print(f"\n=== 결과 (base k5, current, 오늘 모델) ===")
print(f"block: abstain {blk_abst}/38 · pick {blk_pick}/38")
print(f"valid+yes: 오차단 {val_abst}/22")
print(f"abstain_p: min {aps[0]:.3f} q25 {aps[14]:.3f} med {aps[29]:.3f} q75 {aps[44]:.3f} max {aps[-1]:.3f}")
print(f">0.3: {sum(1 for a in aps if a>0.3)}/60 · chose_abstain: {sum(1 for r in recs if r['chose_abstain'])}/60")

json.dump(recs, open(os.path.join(DATA, "stage61_base_recheck.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage61_base_recheck.json")

# 어제(stage48)와 대조
s48 = json.load(open(os.path.join(DATA, "stage48_live60_cross.json"), encoding="utf-8"))
cur48 = s48[0]["records"] if s48[0]["cond"] == "cur" else s48[1]["records"]
aps48 = sorted(r["abstain_p"] for r in cur48)
print(f"\n=== 어제(stage48 cur) 대조 ===")
print(f"abstain_p: min {aps48[0]:.3f} med {aps48[29]:.3f} max {aps48[-1]:.3f} | >0.3: {sum(1 for a in aps48 if a>0.3)}/60 | abstained: {sum(1 for r in cur48 if r['abstained'])}/60")