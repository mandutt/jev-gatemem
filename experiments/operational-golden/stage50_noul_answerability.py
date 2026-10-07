# -*- coding: utf-8 -*-
"""stage50: Noul answerability 실험 — 200-query × 1-run (choice+noul30 1콜/쿼리)

구조 (같은 1콜 응답을 후처리로 비교):
  baseline   : choice만, abstain_p>0.3 (현행)
  noul_top50 : noul_top < 0.50 → abstain
  noul_top65 : noul_top < 0.65 → abstain
  noul_win50 : winner의 noul < 0.50 → abstain

합격선 (live60):
  1) IRREL 15건 중 ≥5 차단 (block)
  2) 정답노출 21건 (YES 16 + VALID 5) 중 ≤1 희생
  3) 부가: IN 21건(답이 rank 6~60)에서 noul 상위 회복 측정
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
s = sqlite3.connect(SNAP)
s.row_factory = sqlite3.Row

VERDICTS_49C = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage49c_label_booster_verdicts.json", encoding="utf-8"))

# 라이브 60 분류 (49c+49d 판정 통합)
CLASSES = {}
for d in json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8")):
    idx, orig = d["idx"], d["verdict"]
    v49c = VERDICTS_49C[str(idx)]
    if orig == "no":
        if v49c == "IRREL": CLASSES[idx] = ("live_irrel", "block")
        elif v49c == "PLAUS": CLASSES[idx] = ("live_plaus", "block_low")
        else: CLASSES[idx] = ("live_valid", "protect")
    elif orig == "yes":
        CLASSES[idx] = ("live_yes_miss", "protect")   # 49d: 답은 rank 6~60 (IN 21/21)
    else:
        CLASSES[idx] = ("live_maybe_no" if v49c == "NO" else "live_maybe_yes",
                        "block_low" if v49c == "NO" else "protect")

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
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw

CLIENT = _jev_client()
assert CLIENT

def build_pool(query):
    pool = j1p.build_lane_pool(recall_raw_factory(query), query)
    return j1p._filter_and_rank(pool, query)[:j1p.POOL_BUDGET]

def hybrid_call(query, rows):
    """choice(60 전체) + noul(앞 30개만) — API MAX_QS=31 한도 대응.
    noul 미평가 후보(31~60위)의 winner_noul은 None."""
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), query, 300), 150) or "n/a" for c in rows]
    state = j1p.build_state(query, rows)
    NOUL_N = 30
    questions = {"best": {"type": "choice",
                          "instructions": "Which candidate memory is the single best evidence for answering the question? Pick exactly one. Consider directness and specificity.",
                          "criteria": {f"c{i}": labels[i] for i in range(len(labels))}}}
    for i in range(min(NOUL_N, len(labels))):
        questions[f"n{i}"] = {"type": "noul",
                              "instructions": {"question": "Does this candidate memory directly state or entail the answer to the question? Output a 0-1 score.",
                                               "candidate": labels[i]}}
    for attempt in range(2):
        try:
            resp = CLIENT.post(getattr(CLIENT, "_jev_api", None),
                               json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=25)
            if resp.status_code == 503:
                time.sleep(1.5); continue
            break
        except Exception:
            time.sleep(1.5); resp = None
    if resp is None or resp.status_code != 200:
        return None, 0.0, [], f"http{getattr(resp, 'status_code', None)}"
    ans = (resp.json().get("answers") or {})
    best = ans.get("best") or {}
    choice = best.get("choice")
    probs = best.get("probabilities") or {}
    abstain_p = float(probs.get(f"c{len(labels)}", 0.0) or 0.0)  # abstain 라벨 = c{N}
    try:
        idx = int(str(choice).lstrip("c"))
        if idx == len(labels): idx = None  # abstain 선택
    except Exception:
        idx = None
    noul = []
    for i in range(min(NOUL_N, len(labels))):
        v = (ans.get(f"n{i}") or {}).get("noul", 0.0)
        noul.append(float(v) if v is not None else 0.0)
    return idx, abstain_p, noul, None

# ---- 벤치 구성 ----
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
no = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
live = m48.load_queries(None)

bench = []
for i, q in enumerate(live, 1):
    bench.append({"src": "live", "qid": f"live_{i}", "query": q, "gold": None,
                  "cls": CLASSES[i][0], "role": CLASSES[i][1]})
for q, g in op:
    bench.append({"src": "op", "qid": f"op_{g}", "query": q, "gold": g, "cls": "op", "role": "protect"})
for item in no:
    bench.append({"src": "noans", "qid": item["qid"], "query": item["query"], "gold": None,
                  "cls": "noans_hard", "role": "block"})

print(f"벤치: {len(bench)}건 (live {sum(1 for b in bench if b['src']=='live')} / op {sum(1 for b in bench if b['src']=='op')} / noans {sum(1 for b in bench if b['src']=='noans')})", flush=True)

# pool 사전 구성
pools = {}
for k, b in enumerate(bench):
    pools[k] = build_pool(b["query"])
    if (k+1) % 40 == 0: print(f"pool {k+1}/{len(bench)}", flush=True)

# ---- 1-run 실행 (choice+noul 1콜/쿼리) ----
results = []
t0 = time.time()
for k, b in enumerate(bench):
    rows = pools[k]
    idx, abstain_p, noul, err = hybrid_call(b["query"], rows)
    rec = {"src": b["src"], "qid": b["qid"], "cls": b["cls"], "role": b["role"],
           "pool_n": len(rows), "choice_idx": idx, "abstain_p": abstain_p,
           "noul_top": round(max(noul), 3) if noul else None,
           "noul_second": round(sorted(noul)[-2], 3) if noul and len(noul) > 1 else None,
           "winner_noul": round(noul[idx], 3) if (noul and isinstance(idx, int) and 0 <= idx < len(noul)) else None,
           "err": err, "pool_ids": [(r.get("id") or "")[:16] for r in rows]}
    results.append(rec)
    if (k+1) % 25 == 0:
        print(f"{k+1}/{len(bench)} elapsed={time.time()-t0:.0f}s", flush=True)
        json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results},
                  open(os.path.join(DATA, "stage50_noul_answerability.json"), "w", encoding="utf-8"), ensure_ascii=False)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results},
          open(os.path.join(DATA, "stage50_noul_answerability.json"), "w", encoding="utf-8"), ensure_ascii=False)
err_n = sum(1 for r in results if r["err"])
print(f"\n완료: {len(results)}쿼리, err={err_n}, {time.time()-t0:.0f}s")
