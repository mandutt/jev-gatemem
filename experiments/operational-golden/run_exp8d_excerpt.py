"""④ A excerpt 길이 실험 — 100자(현행) vs 240자 vs 400자 (2026-10-04)

b AI 제안: "A가 120자 절단 때문에 근거를 놓친 경우는 게이트가 구제하지 못한다.
A의 excerpt를 240/400자로 올려 op hit@3과 LGO/noans를 다시 재는 실험이
게이트보다 영향이 클 수 있다."

실험: choice label 길이를 240/400자로 변경해 3세트(op 90 + lgo 90 + noans 50) 재실행.
- exp8a(100자) 결과와 hit@3 / acceptance / non-abstain 비교
- 지연/토큰도 기록 (b AI: 후보 40개 × 400자의 지연/토큰 확인 포함)

비용: 230콜/조건 × 2조건 = 460콜 FREE (SmartRotator)
출력: data/exp8d_excerpt240_raw.json, data/exp8d_excerpt400_raw.json
"""
import json
import os
import sys
import time
import sqlite3
import urllib.request
import urllib.error
import winreg
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments/operational-golden"))

DATA = os.path.join(ROOT, "experiments/operational-golden/data")
LIVE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
MAX_CRIT = 64
MAX_CAND = MAX_CRIT - 1
MAX_CAND_CHARS = 1350
WORKERS = 3
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"
CHOICE_INSTR = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. Consider directness and specificity. "
    "If no candidate is usable evidence for answering the question, pick the last option."
)

from keyring import SmartRotator
rot = SmartRotator()
print("키 상태:", rot.stats(), flush=True)


def post(url, body, key, timeout=180.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    for attempt in range(6):
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                nk = rot.on_429()
                if nk:
                    key = nk
                    continue
                ra = e.headers.get("Retry-After")
                try:
                    wait = float(ra) if ra else 30.0
                except ValueError:
                    wait = 30.0
                print(f"    429 → {wait:.0f}s (attempt {attempt+1}/6)", flush=True)
                time.sleep(wait)
                continue
            return e.code, {"__msg": e.read().decode()[:200]}
        except Exception as e:
            if attempt == 5:
                return -1, {"__msg": f"{type(e).__name__}"}
            time.sleep(1.5)
    return 429, {"__msg": "rate limited"}


def choice_call(key, query, cands, excerpt_len):
    labels = [(c.get("content") or "")[:excerpt_len] or "n/a" for c in cands]
    j_labels = list(labels) + [ABSTAIN_LABEL]
    body = {"model": MODEL, "state": {"question": query, "candidates": []},
            "questions": {"best": {"type": "choice", "instructions": CHOICE_INSTR,
                                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}}
    t0 = time.perf_counter()
    status, resp = post(URL, body, key)
    lat = (time.perf_counter() - t0) * 1000
    if status != 200:
        return None, None, f"http-{status}", lat
    cost = (resp.get("usage") or {}).get("cost", None)
    rot.set_cost(cost)
    tok_in = (resp.get("usage") or {}).get("input_tokens", None)
    ans = (resp.get("answers") or {}).get("best") or {}
    ch = ans.get("choice")
    if ch is None:
        return None, cost, "no-choice", lat
    i = int(str(ch).lstrip("c"))
    if i == len(labels):
        return -1, cost, None, lat
    if not (0 <= i < len(labels)):
        return None, cost, "bad-idx", lat
    return i, cost, None, lat


def get_beam_refs():
    os.environ.setdefault("MNEMOSYNE_DB", LIVE_DB)
    import gateway.j1_pipeline as j1p
    import mnemosyne.core.beam as bm
    from mnemosyne.core import embeddings as emb_mod
    b = bm.BeamMemory(session_id="exp8d")

    def recall_raw(kind, arg, k_):
        if kind == "fts":
            return bm._fts_search_working(b.conn, arg, k=k_)
        if kind == "vec":
            e = emb_mod.embed([arg])
            if e is None or not len(e):
                return []
            return bm._wm_vec_search(b.conn, e[0], k=k_)
        if kind == "imp":
            return j1p._imp_search(b.conn, k=k_)
        if kind == "graph":
            return j1p._graph_lane_search(b.conn, arg, k=k_)
        if kind == "get":
            from core import j1_engine
            row = j1_engine.hydration_get(b, arg)
            return row if isinstance(row, dict) else None
        return []
    return recall_raw, j1p, b


def stage1_pool(query, exclude_ids=None, k=40):
    recall_raw, j1p, b = get_beam_refs()
    pool = j1p.build_lane_pool(recall_raw, query)
    if exclude_ids:
        pool = [p for p in pool if p.get("id") not in exclude_ids]
    ranked = j1p._filter_and_rank(pool, query) if pool else []
    return ranked[:k]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--excerpt", type=int, required=True, choices=[240, 400])
    ap.add_argument("--groups", default="op,lgo,noans")
    args = ap.parse_args()
    EL = args.excerpt

    # 쿼리 로드 (exp8a와 동일 구성)
    op_all = json.load(open(os.path.join(DATA, "golden_eval_v2.json"), encoding="utf-8"))
    op = [x for x in op_all if x.get("gold_id") and x.get("cat") != "NO_ANSWER"]
    noans = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
    groups = args.groups.split(",")

    by_id = set()
    conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    for tbl in ["working_memory", "episodic_memory"]:
        for r in conn.execute(f"SELECT id FROM {tbl}"):
            by_id.add(r[0])
    conn.close()

    tasks = []
    if "op" in groups:
        for x in op:
            tasks.append(("op", x["gold_id"], x["query"], x["gold_id"], None))
    if "lgo" in groups:
        for x in op:
            tasks.append(("lgo", x["gold_id"], x["query"], x["gold_id"], {x["gold_id"]}))
    if "noans" in groups:
        for x in noans:
            tasks.append(("noans", x.get("qid"), x["query"], None, None))
    print(f"excerpt {EL}자 | {len(tasks)}건 ({len(tasks)}콜)", flush=True)

    recs = []
    def run_one(grp, qid, query, gold_id, exclude_ids):
        try:
            pool = stage1_pool(query, exclude_ids=exclude_ids, k=40)
        except Exception as e:
            return {"grp": grp, "qid": qid, "err": f"pool {type(e).__name__}: {e}"}
        pool = [p for p in pool if p.get("id") in by_id]
        if not pool:
            return {"grp": grp, "qid": qid, "err": "empty-pool"}
        cands = pool[:MAX_CAND]
        key = rot.next()
        idx, cost, err, lat = choice_call(key, query, cands, EL)
        rec = {"grp": grp, "qid": qid, "gold_id": gold_id, "n_pool": len(cands),
               "lat_ms": round(lat, 1), "err": err}
        if err:
            rec["choice"] = None
            return rec
        if idx == -1:
            rec["choice"] = "abstain"
            rec["choice_abstain"] = True
            rec["winner_id"] = None
            rec["gold_rank"] = None
            return rec
        rec["choice"] = f"c{idx}"
        rec["choice_abstain"] = False
        rec["winner_id"] = cands[idx].get("id")
        order_ids = [cands[idx]["id"]] + [c["id"] for i, c in enumerate(cands) if i != idx]
        rec["gold_rank"] = (order_ids.index(gold_id) + 1) if gold_id in order_ids else None
        return rec

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(run_one, *t): t for t in tasks}
        done = 0
        for f in futs:
            recs.append(f.result())
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(tasks)}", flush=True)

    out = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": MODEL,
        "cond": f"A-choice-excerpt{EL}",
        "excerpt_len": EL,
        "corpus_n": len(by_id),
        "n": len(recs),
        "records": recs,
    }
    fname = f"exp8d_excerpt{EL}_raw.json"
    with open(os.path.join(DATA, fname), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {DATA}/{fname}")

    # 요약
    lats = [r.get("lat_ms") for r in recs if r.get("lat_ms")]
    if lats:
        lats.sort()
        print(f"지연: p50 {lats[len(lats)//2]:.0f}ms | p95 {lats[int(len(lats)*0.95)]:.0f}ms | n={len(lats)}")
    for grp in ["op", "lgo", "noans"]:
        sub = [r for r in recs if r["grp"] == grp]
        if not sub:
            continue
        abs_n = sum(1 for r in sub if r.get("choice_abstain"))
        if grp == "op":
            h3 = sum(1 for r in sub if r.get("gold_rank") is not None and r["gold_rank"] <= 3)
            print(f"op: hit@3 {h3}/{len(sub)} ({h3/len(sub)*100:.1f}%) | abstain {abs_n}")
        elif grp == "lgo":
            non_abs = len(sub) - abs_n
            print(f"lgo: non-abstain {non_abs}/{len(sub)} ({non_abs/len(sub)*100:.1f}%) | abstain {abs_n}")
        else:
            non_abs = len(sub) - abs_n
            print(f"noans: non-abstain {non_abs}/{len(sub)} ({non_abs/len(sub)*100:.1f}%)")


if __name__ == "__main__":
    main()