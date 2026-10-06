# -*- coding: utf-8 -*-
"""regression_live60.py — 라이브 60 회귀 검증 셋 평가 러너 (릴리스 게이트, 2026-10-06)

3종 AI 공통 권고 + stage49~50 확정 사항의 운영화:
- 파이프라인 변경 시 이 셋으로 회귀 확인 (스냅샷 기준 고정)
- 지표: answerable_nonabstain (정답노출), noanswer_abstain (무답차단), IRREL/PLAUS/VALID 분해
- 시점 필터(created_at < 2026-10-05) 적용 — 자기참조 누수 방지 (stage49b)
- 사용자 판정(49c/49d) 로드 → 클래스 분해

용도:
  python regression_live60.py                     # 1-run (60콜)
  python regression_live60.py --runs 3            # 3-run majority (180콜)

출력: data/regression_live60_<ts>.json + 요약 stdout
"""
import os, sys, json, sqlite3, time, argparse, re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (experiments/operational-golden/ → repo)
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
CUTOFF = "2026-10-05"

# ---- 사용자 판정 로드 (49c 라벨 보강) ----
VERDICTS_49C = None
for cand in (os.path.join(DATA, "stage49c_label_booster_verdicts.json"),
             os.path.join(os.path.expanduser("~"), "Downloads", "stage49c_label_booster_verdicts.json")):
    if os.path.exists(cand):
        VERDICTS_49C = json.load(open(cand, encoding="utf-8"))
        break
assert VERDICTS_49C is not None, "stage49c 판정 JSON 필요 (data/ 또는 Downloads/)"

CLASSES = {}
for d in json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8")):
    idx, orig = d["idx"], d["verdict"]
    v = VERDICTS_49C[str(idx)]
    if orig == "no":
        CLASSES[idx] = {"v": "IRREL" if v == "IRREL" else ("PLAUS" if v == "PLAUS" else "VALID"),
                        "role": "block" if v in ("IRREL", "PLAUS") else "protect"}
    elif orig == "yes":
        CLASSES[idx] = {"v": "YES_MISS", "role": "protect"}   # 49d: 답은 rank 6~60
    else:
        CLASSES[idx] = {"v": f"MAYBE_{v}", "role": "protect" if v == "YES" else "block_low"}

s = sqlite3.connect(SNAP)
s.row_factory = sqlite3.Row

def recall_raw_factory(query):
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
    return recall_raw

def build_pool_tc(query):
    """시점 필터(created_at < CUTOFF) 적용 pool"""
    pool = j1p.build_lane_pool(recall_raw_factory(query), query)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < CUTOFF)]
    return j1p._filter_and_rank(pool, query)[:j1p.POOL_BUDGET]

def run_choice(query, rows):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), query, 300), 150) or "n/a" for c in rows]
    j_labels = labels + [m48.ABSTAIN_CURRENT]
    state = j1p.build_state(query, rows)
    questions = {"best": {"type": "choice", "instructions": m48.INSTR,
                          "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    client = CLIENT
    api = getattr(client, "_jev_api", None)
    for attempt in range(2):
        try:
            resp = client.post(api, json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=25)
            if resp.status_code == 503:
                time.sleep(1.5); continue
            break
        except Exception:
            time.sleep(1.5); resp = None
    if resp is None or resp.status_code != 200:
        return {"abstain": None, "abstain_p": None, "err": f"http{getattr(resp,'status_code',None)}"}
    ans = (resp.json().get("answers") or {}).get("best") or {}
    choice = ans.get("choice")
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(j_labels)-1}", 0.0) or 0.0)
    try:
        idx = int(str(choice).lstrip("c"))
    except Exception:
        idx = None
    abstain = (idx is None) or (idx == len(j_labels) - 1) or (ap > 0.3)
    return {"abstain": abstain, "abstain_p": round(ap, 3), "err": None}

def summarize(records, cls_map):
    out = {"n": len(records), "err": sum(1 for r in records if r["err"])}
    groups = {}
    for label in ("IRREL", "PLAUS", "VALID", "YES_MISS", "MAYBE_NO", "MAYBE_YES"):
        rs = [r for r in records if cls_map[r["qid"]].get("v") == label and not r["err"]]
        if rs:
            abst = sum(1 for r in rs if r["abstain"])
            groups[label] = {"n": len(rs), "abstain": abst, "pick": len(rs) - abst}
    out["groups"] = groups
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()

    global CLIENT
    CLIENT = _jev_client()
    assert CLIENT, "EXPLABS_API_KEY SET 터미널에서 실행하라"

    qs = m48.load_queries(None)
    assert len(qs) == 60
    cls_map = {i: CLASSES[i] for i in range(1, 61)}

    # pool 사전 구성 (시점 필터)
    pools = {i: build_pool_tc(q) for i, q in enumerate(qs, 1)}
    print(f"pool 구성 완료 (median {sorted(len(v) for v in pools.values())[30]})", flush=True)

    all_runs = []
    for run in range(args.runs):
        records = []
        for i, q in enumerate(qs, 1):
            r = run_choice(q, pools[i])
            records.append({"qid": i, "query": q, "pool_n": len(pools[i]), **r})
        all_runs.append(records)
        s1 = summarize(records, cls_map)
        g = s1["groups"]
        print(f"run{run+1}: IRREL abstain {g.get('IRREL',{}).get('abstain',0)}/{g.get('IRREL',{}).get('n','-')} "
              f"| YES_MISS abstain {g.get('YES_MISS',{}).get('abstain',0)}/{g.get('YES_MISS',{}).get('n','-')} "
              f"| VALID abstain {g.get('VALID',{}).get('abstain',0)}/{g.get('VALID',{}).get('n','-')} "
              f"| err {s1['err']}", flush=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(DATA, f"regression_live60_{ts}.json")
    json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "runs": args.runs,
               "snapshot": os.path.basename(SNAP), "cutoff": CUTOFF,
               "verdicts_src": "stage49c", "runs_data": all_runs},
              open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"저장: {out_path}")

if __name__ == "__main__":
    main()