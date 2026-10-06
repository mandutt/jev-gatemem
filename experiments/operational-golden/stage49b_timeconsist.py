# -*- coding: utf-8 -*-
"""stage49b: 시점 일관 리플레이 — 라이브 60 × 3조건 × 3-run (540콜)

B AI 설계: 시점 필터(created_at < 2026-10-05)로 자기참조 제거 후,
  cur(현행) / head100(win-300 제거·head-100 고정) / imp(improved 라벨) 비교.
판정 축:
  - live no 22건 abstain 수 (무력 해소 여부)
  - live yes 35건 pick 유지율
  - head100에서 abstain이 살아나면 win-300 증폭 가설 확정
"""
import os, re, sys, json, sqlite3, time

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
CUTOFF = "2026-10-05"          # 이 시각 이전 기록만 후보
RUNS = 3
POOL_CAP = j1p.POOL_BUDGET

VERDICTS = {
 "1": "no", "2": "no", "3": "yes", "4": "yes", "5": "no", "6": "no", "7": "yes", "8": "yes", "9": "no", "10": "yes",
 "11": "no", "12": "yes", "13": "yes", "14": "yes", "15": "yes", "16": "no", "17": "yes", "18": "yes", "19": "no", "20": "yes",
 "21": "no", "22": "yes", "23": "yes", "24": "yes", "25": "no", "26": "no", "27": "yes", "28": "yes", "29": "no", "30": "yes",
 "31": "maybe", "32": "yes", "33": "no", "34": "yes", "35": "yes", "36": "no", "37": "yes", "38": "yes", "39": "yes", "40": "no",
 "41": "maybe", "42": "yes", "43": "yes", "44": "yes", "45": "yes", "46": "no", "47": "yes", "48": "no", "49": "yes", "50": "no",
 "51": "maybe", "52": "no", "53": "no", "54": "yes", "55": "no", "56": "no", "57": "yes", "58": "yes", "59": "yes", "60": "yes"
}

ABSTAIN_IMP = ("No candidate contains the specific fact, value, version, or decision the question "
               "asks for — same-topic mention alone is not evidence")

s = sqlite3.connect(SNAP)
s.row_factory = sqlite3.Row

# ---- 시점 필터링된 lane 수집 + pool 구성 ----
def build_pool_time(query):
    def recall_raw(kind, arg, k):
        if kind == "fts": return beam_mod._fts_search_working(s, arg, k=k)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(s, qemb[0], k=k)
        if kind == "imp": return j1p._imp_search(s, k=k)
        if kind == "graph": return j1p._graph_lane_search(s, arg, k=k)
        if kind == "get":
            r = s.execute("SELECT id, content, importance, created_at FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance, created_at FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    pool = j1p.build_lane_pool(recall_raw, query)
    # 시점 필터 (hydrate 전)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < CUTOFF)]
    return j1p._filter_and_rank(pool, query)[:POOL_CAP]

def run_choice(query, rows, abstain_label, mode):
    if mode == "head100":
        labels = [(c.get("content") or "")[:100] or "n/a" for c in rows]
    else:
        labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), query, 300), 150) or "n/a" for c in rows]
    j_labels = labels + [abstain_label]
    state = j1p.build_state(query, rows)
    questions = {"best": {"type": "choice", "instructions": m48.INSTR,
                          "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    client = CLIENT
    _api = getattr(client, "_jev_api", None)
    for attempt in range(2):
        try:
            resp = client.post(_api, json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=20)
            if resp.status_code == 503:
                time.sleep(1.5); continue
            break
        except Exception as e:
            time.sleep(1.5); resp = None
    if resp is None or resp.status_code != 200:
        return {"abstain": False, "abstain_p": 0.0, "err": f"http{getattr(resp,'status_code',None)}"}
    ans = resp.json()["answers"]["best"]
    choice = ans.get("choice")
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(j_labels)-1}", 0.0) or 0.0)
    try:
        idx = int(str(choice).lstrip("c"))
    except Exception:
        idx = None
    abstain = (idx is None) or (idx == len(j_labels) - 1) or (ap > 0.3)
    return {"abstain": abstain, "abstain_p": round(ap, 3), "err": None}

CLIENT = _jev_client()
assert CLIENT

qs = m48.load_queries(None)
assert len(qs) == 60

# pool 사전 구성 (시점 필터, 쿼리당 1회)
pools = {}
for i, q in enumerate(qs, 1):
    pools[i] = build_pool_time(q)
print(f"pool 구성 완료: n={len(pools)} median={sorted(len(v) for v in pools.values())[30]}")
json.dump({str(k): len(v) for k, v in pools.items()},
          open("experiments/operational-golden/data/stage49b_pool_sizes.json", "w", encoding="utf-8"))

conds = [("cur", m48.ABSTAIN_CURRENT), ("head100", m48.ABSTAIN_CURRENT), ("imp", ABSTAIN_IMP)]
results = []
for run_i in range(RUNS):
    for cond, label in conds:
        recs = []
        for i, q in enumerate(qs, 1):
            rows = pools[i]
            r = run_choice(q, rows, label, cond)
            recs.append({"idx": i, **r})
        results.append({"run": run_i + 1, "cond": cond, "records": recs})
        # 중간 저장
        json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": results},
                  open("experiments/operational-golden/data/stage49b_timeconsist.json", "w", encoding="utf-8"),
                  ensure_ascii=False)
        abst = sum(1 for r in recs if r["abstain"])
        err = sum(1 for r in recs if r["err"])
        print(f"run{run_i+1} {cond}: abstain={abst}/60 err={err}", flush=True)

print("완료: data/stage49b_timeconsist.json")
