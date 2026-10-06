"""stage47g: current 라벨 + head150+겹침150(non-overlap) 병합 (2026-10-06)

stage47f에서 imphbn의 WHY 구제는 윈도우 효과, gold50 손실은 improved 라벨 효과로
분리됨 → current 라벨 + head겹침 조합이 두 효과를 모두 얻는지 검증.

- cond cur:    current 라벨 + 300→150 절단 (운영 현행 재현)
- cond imp150: improved 라벨 + win150 직접 (stage47c 재현)
- cond imphb:  improved 라벨 + head150+overlap150 병합 (신규)
"""
import json, os, re, sys, time, sqlite3

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
os.chdir(REPO)

from gateway import j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006.db")
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
GOLD = os.path.join(REPO, "experiments", "operational-golden", "data", "golden_noanswer_hard_queries.json")

ABSTAIN_CURRENT = "No candidate is usable evidence for answering the question"
ABSTAIN_IMPROVED = ("No candidate contains the specific fact, value, version, or decision the "
                    "question asks for \u2014 same-topic mention alone is not evidence")
INSTR = "Choose the single candidate that best directly answers the question. If none is usable evidence, choose the final abstain option."

CONDS = [
    ("cur", ABSTAIN_CURRENT, "w300c150"),
    ("curhb", ABSTAIN_CURRENT, "w_head_overlap_non"),
]


def load_sets(snap):
    s = sqlite3.connect(snap)
    s.row_factory = sqlite3.Row
    st45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
    op = [r for r in st45["runs"][0]["records"] if r["grp"] == "op"]
    op_items = [(r["query"], r["gold_id"]) for r in op]
    na = json.load(open(GOLD, encoding="utf-8"))
    na_items = [(n["query"], n.get("gold_ids") or []) for n in na]
    return s, op_items, na_items


def build_pool(s, query):
    def recall_raw(kind, arg, k):
        if kind == "fts":
            return beam_mod._fts_search_working(s, arg, k=k)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb):
                return []
            return beam_mod._wm_vec_search(s, qemb[0], k=k)
        if kind == "imp":
            return j1p._imp_search(s, k=k)
        if kind == "graph":
            return j1p._graph_lane_search(s, arg, k=k)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return {"id": r[0], "content": r[1], "importance": r[2]} if r else None
        return []

    pool = j1p.build_lane_pool(recall_raw, query)
    filtered = j1p._filter_and_rank(pool, query) if pool else []
    return filtered[:j1p.POOL_BUDGET]


def head_overlap(content, query, head=150, win=150):
    """head(150) + 겹침최대(150) 병합 — head 정답과 겹침 구간 모두 보존 (300자)."""
    m = re.match(r"^(\[[^\]]*\]\s*)?", content or "")
    c = (content or "")[m.end():] if m else (content or "")
    head_part = c[:head]
    qt = j1p._tokenize(query) - j1p._STOPWORDS
    if not qt or len(c) <= head + win:
        return c[:head + win]
    best_start, best_score = 0, -1
    step = 50
    for start in range(0, len(c) - win + 1, step):
        seg = c[start:start + win]
        score = len(qt & j1p._tokenize(seg))
        if score > best_score:
            best_score, best_start = score, start
    both = head_part + "\n---\n" + c[best_start:best_start + win]
    return both[:300]


def head_overlap_non(content, query, head=150, win=150):
    """head(150) + head와 겹치지 않는 겹침최대(150) 병합 (300자).

    stage47d에서 head+겹침이 WHY gold에서 겹침 구간이 head와 겹쳐 동어반복이 된
    문제 해결: 겹침 후보 시작이 head(150) 안이면 건너뛰고 head 이후 최대 겹침 선택.
    """
    m = re.match(r"^(\[[^\]]*\]\s*)?", content or "")
    c = (content or "")[m.end():] if m else (content or "")
    head_part = c[:head]
    qt = j1p._tokenize(query) - j1p._STOPWORDS
    if not qt or len(c) <= head + win:
        return c[:head + win]
    best_start, best_score = 0, -1
    step = 50
    for start in range(0, len(c) - win + 1, step):
        seg = c[start:start + win]
        score = len(qt & j1p._tokenize(seg))
        if score > best_score:
            best_score, best_start = score, start
    if best_start >= head:
        return (head_part + "\n---\n" + c[best_start:best_start + win])[:300]
    # head 안이면 head 이후 최대 겹침
    best2_start, best2_score = 0, -1
    for start in range(head, len(c) - win + 1, step):
        seg = c[start:start + win]
        score = len(qt & j1p._tokenize(seg))
        if score > best2_score:
            best2_score, best2_start = score, start
    if best2_score > 0:
        return (head_part + "\n---\n" + c[best2_start:best2_start + win])[:300]
    return head_part


def run_choice(client, query, rows, abstain_label, win_mode):
    if win_mode == "w150":
        labels = [j1p._query_window((c.get("content") or ""), query, 150) or "n/a" for c in rows]
    elif win_mode == "w_head_overlap":
        labels = [head_overlap((c.get("content") or ""), query) or "n/a" for c in rows]
    elif win_mode == "w_head_overlap_non":
        labels = [head_overlap_non((c.get("content") or ""), query) or "n/a" for c in rows]
    else:
        labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), query, 300), 150) or "n/a" for c in rows]
    j_labels = labels + [abstain_label]
    state = j1p.build_state(query, rows)
    questions = {"best": {"type": "choice", "instructions": INSTR,
                          "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    _api = getattr(client, "_jev_api", None) or "https://api.typesafe.ai/v1/systemone"
    resp = client.post(_api, json={"state": state, "questions": questions,
                                   "model": "jev-latest"}, timeout=12.0)
    if resp.status_code != 200:
        return None, 0.0, f"http{resp.status_code}:{resp.text[:60]}"
    ans = resp.json()["answers"]["best"]
    choice = ans.get("choice")
    probs = ans.get("probabilities") or {}
    abstain_p = float(probs.get(f"c{len(j_labels)-1}", 0.0)) if probs else 0.0
    if choice is None:
        return None, abstain_p, "no-choice"
    idx = int(str(choice).lstrip("c"))
    if idx == len(j_labels) - 1 or abstain_p > 0.3:
        return None, abstain_p, None
    return idx, abstain_p, None


def main():
    client = _jev_client()
    print("client:", "OK" if client else "NONE", flush=True)
    assert client
    s, op_items, na_items = load_sets(SNAP)
    all_runs = []
    for cond, abstain_label, win_mode in CONDS:
        print(f"\n=== {cond} 시작 ===", flush=True)
        recs = []
        for grp, items in (("op", op_items), ("noans", na_items)):
            for query, gold_id in items:
                rows = build_pool(s, query)
                if not rows:
                    recs.append({"query": query, "grp": grp, "gold_id": gold_id,
                                 "gold_rank": None, "pool_n": 0, "abstained": False,
                                 "abstain_p": 0.0, "err": "empty-pool"})
                    continue
                idx, abstain_p, err = run_choice(client, query, rows, abstain_label, win_mode)
                rank = None
                if idx is not None and 0 <= idx < len(rows):
                    if rows[idx].get("id") == gold_id:
                        rank = 1
                    else:
                        ids = [r.get("id") for r in rows]
                        if gold_id in ids:
                            rank = ids.index(gold_id) + 1
                recs.append({"query": query, "grp": grp, "gold_id": gold_id,
                             "gold_rank": rank, "pool_n": len(rows),
                             "abstained": idx is None and err is None,
                             "abstain_p": round(abstain_p, 3), "err": err})
                time.sleep(0.2)
        all_runs.append({"cond": cond, "records": recs})
        op = [r for r in recs if r["grp"] == "op"]
        na = [r for r in recs if r["grp"] == "noans"]
        h1 = sum(1 for r in op if r["gold_rank"] == 1)
        h3 = sum(1 for r in op if r["gold_rank"] is not None and r["gold_rank"] <= 3)
        abst = sum(1 for r in op if r["abstained"])
        fp = sum(1 for r in na if not r["abstained"] and not r["err"])
        err = sum(1 for r in recs if r["err"])
        print(f"{cond}: hit@1={h1} hit@3={h3} abstain={abst} noansFP={fp}/50 err={err}", flush=True)
    json.dump(all_runs, open(os.path.join(DATA, "stage47g_curhb.json"), "w", encoding="utf-8"))
    print("\n저장 완료: stage47g_curhb.json", flush=True)


if __name__ == "__main__":
    main()