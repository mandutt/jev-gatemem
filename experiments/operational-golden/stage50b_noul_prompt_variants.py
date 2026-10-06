# -*- coding: utf-8 -*-
"""stage50b: noul 프롬프트 변형 — 라이브 IRREL 분리 시도 (100쿼리 × 3변형)

v1 현행: "Does this candidate memory directly state or entail the answer to the question?"
v2 구체성: specific fact/value/version/date/decision — same-topic mention is NOT an answer
v3 역방향: 부재 판정 (1 = fully answers, 0 = absent/only topically related)

판정 축: cls별 noul 중앙값 — 특히 live_irrel이 0.91→낮아지는가, live_valid/op는 높게 유지되는가.
분리 지표: IRREL(op류 보호그룹과의 간격) — noul<τ 게이트 재평가.
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

VERDICTS_49C = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
CLASSES = {}
for d in json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8")):
    idx, orig = d["idx"], d["verdict"]
    v49c = VERDICTS_49C[str(idx)]
    if orig == "no":
        if v49c == "IRREL": CLASSES[idx] = ("live_irrel", "block")
        elif v49c == "PLAUS": CLASSES[idx] = ("live_plaus", "block_low")
        else: CLASSES[idx] = ("live_valid", "protect")
    elif orig == "yes":
        CLASSES[idx] = ("live_yes_miss", "protect")
    else:
        CLASSES[idx] = ("live_maybe_no" if v49c == "NO" else "live_maybe_yes",
                        "block_low" if v49c == "NO" else "protect")

CLIENT = _jev_client()
assert CLIENT

PROMPTS = {
    "v1_cur": "Does this candidate memory directly state or entail the answer to the question? Output a 0-1 score.",
    "v2_spec": ("Does this candidate memory contain the specific fact, value, version, date, or decision "
                "the question asks for? Output 1.0 only if it directly answers the question. "
                "A memory that merely discusses the same topic, or states a related rule without the "
                "specific detail asked, scores 0.0."),
    "v3_abs": ("Judge whether the answer to the question is present in this candidate. "
               "Output 1.0 if the candidate fully answers the question. "
               "Output 0.0 if the specific information asked is absent or the candidate is only "
               "topically related without answering."),
}

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

def build_pool(query):
    pool = j1p.build_lane_pool(recall_raw_factory(query), query)
    return j1p._filter_and_rank(pool, query)[:j1p.POOL_BUDGET]

def noul_call(query, rows, prompt_key):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), query, 300), 150) or "n/a" for c in rows[:30]]
    state = j1p.build_state(query, rows)
    questions = {}
    for i, lab in enumerate(labels):
        questions[f"n{i}"] = {"type": "noul",
                              "instructions": {"question": PROMPTS[prompt_key], "candidate": lab}}
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
        return None, f"http{getattr(resp, 'status_code', None)}"
    ans = resp.json().get("answers") or {}
    scores = []
    for i in range(len(labels)):
        v = (ans.get(f"n{i}") or {}).get("noul", 0.0)
        scores.append(float(v) if v is not None else 0.0)
    return scores, None

# ---- 벤치: live 60 + noans 20 + op 20 ----
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op_all = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
no_all = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
live = m48.load_queries(None)

bench = []
for i, q in enumerate(live, 1):
    bench.append({"src": "live", "qid": f"live_{i}", "query": q, "cls": CLASSES[i][0]})
op_sample = op_all[::4][:20]     # 90 → 20 샘플
no_sample = no_all[::2][:20]     # 50 → 20 샘플
for q, g in op_sample:
    bench.append({"src": "op", "qid": f"op_{g}", "query": q, "cls": "op"})
for item in no_sample:
    bench.append({"src": "noans", "qid": item["qid"], "query": item["query"], "cls": "noans_hard"})

print(f"벤치 {len(bench)}건 (live 60 / op 20 / noans 20)", flush=True)

pools = {}
for k, b in enumerate(bench):
    pools[k] = build_pool(b["query"])
print("pool 구성 완료", flush=True)

# ---- 3변형 실행 ----
out = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "prompts": PROMPTS, "results": []}
t0 = time.time()
for k, b in enumerate(bench):
    rows = pools[k]
    for pk in PROMPTS:
        scores, err = noul_call(b["query"], rows, pk)
        out["results"].append({"qid": b["qid"], "src": b["src"], "cls": b["cls"],
                               "variant": pk, "scores": scores, "err": err,
                               "top": round(max(scores), 3) if scores else None})
    if (k+1) % 20 == 0:
        print(f"{k+1}/{len(bench)} elapsed={time.time()-t0:.0f}s", flush=True)
        json.dump(out, open(os.path.join(DATA, "stage50b_noul_prompt_variants.json"), "w", encoding="utf-8"), ensure_ascii=False)

json.dump(out, open(os.path.join(DATA, "stage50b_noul_prompt_variants.json"), "w", encoding="utf-8"), ensure_ascii=False)
err_n = sum(1 for r in out["results"] if r["err"])
print(f"\n완료: {len(bench)}쿼리 × 3변형 = {len(out['results'])}콜, err={err_n}, {time.time()-t0:.0f}s")
