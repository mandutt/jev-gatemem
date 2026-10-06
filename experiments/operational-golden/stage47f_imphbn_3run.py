"""stage47f: imphbn vs cur 3-run 재검증 (2026-10-06)

stage47e 1-run에서 imphbn(head+겹침 non-overlap, improved 라벨)이 전 지표 개선을
보인 것을 3-run majority로 확정/기각. 핵심 6쿼리만 소량 재호출.

- 대상: 코덱스 WHY / 마우스 WHY / gemini 별칭 / codex CLI / pi 프록시 (op 5건,
  1-run에서 imphbn이 구제/보존) + gold50 기준선 (cur만 hit 1건)
- 6쿼리 × 3회 × 2 cond(cur, imphbn) = 36콜
- majority: 3회 중 2회 이상 hit/abstain 방어
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

ABSTAIN_CURRENT = "No candidate is usable evidence for answering the question"
ABSTAIN_IMPROVED = ("No candidate contains the specific fact, value, version, or decision the "
                    "question asks for \u2014 same-topic mention alone is not evidence")
INSTR = "Choose the single candidate that best directly answers the question. If none is usable evidence, choose the final abstain option."

TARGETS = [
    "코덱스 앱이 PC 느려지게 한 원인 뭐였어?",
    "마우스 버벅임 원인 조사 결과?",
    "gemini 별칭으로 모델 호출되나?",
    "codex CLI에서 메모리 기록되나?",
    "pi 에이전트에 등록된 프록시 목록?",
    "gold50 기준선 수치가 뭐지?",
]


def load_queries(snap):
    s = sqlite3.connect(snap)
    s.row_factory = sqlite3.Row
    st47e = json.load(open(os.path.join(DATA, "stage47e_head_overlap_non.json"), encoding="utf-8"))
    cur = {r["query"]: r for r in next(x["records"] for x in st47e if x["cond"] == "cur")}
    items = []
    for q in TARGETS:
        if q in cur:
            items.append((q, cur[q].get("gold_id"), cur[q]["grp"]))
    return s, items


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


def head_overlap_non(content, query, head=150, win=150):
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
    best2_start, best2_score = 0, -1
    for start in range(head, len(c) - win + 1, step):
        seg = c[start:start + win]
        score = len(qt & j1p._tokenize(seg))
        if score > best2_score:
            best2_score, best2_start = score, start
    if best2_score > 0:
        return (head_part + "\n---\n" + c[best2_start:best2_start + win])[:300]
    return head_part


def run_choice(client, query, rows, abstain_label, mode):
    if mode == "imphbn":
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
    s, items = load_queries(SNAP)
    results = {}
    for q, gid, grp in items:
        rows = build_pool(s, q)
        results[q] = {"grp": grp, "gold_id": gid, "pool_n": len(rows), "runs": {}}
        for cond_label, mode, abstain_label in [("cur", "cur", ABSTAIN_CURRENT),
                                                 ("imphbn", "imphbn", ABSTAIN_IMPROVED)]:
            hits = []
            for _ in range(3):
                idx, ap, err = run_choice(client, q, rows, abstain_label, mode)
                hit = None
                if grp == "op" and idx is not None and 0 <= idx < len(rows):
                    hit = rows[idx].get("id") == gid if gid else False
                abst = idx is None and err is None
                hits.append({"idx": idx, "abstain": abst, "hit": hit,
                             "abstain_p": round(ap, 3), "err": err})
                time.sleep(0.3)
            results[q]["runs"][cond_label] = hits
        # 요약
        def summ(key):
            hs = results[q]["runs"][key]
            if grp == "op":
                return sum(1 for h in hs if h["hit"])
            return sum(1 for h in hs if h["abstain"])
        print(f"{grp:5} | {q[:38]:40} | cur = {summ('cur')}/3, imphbn = {summ('imphbn')}/3", flush=True)
    json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": results},
              open(os.path.join(DATA, "stage47f_imphbn_3run.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("저장 완료: stage47f_imphbn_3run.json", flush=True)


if __name__ == "__main__":
    main()