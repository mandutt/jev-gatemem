"""stage47b: win150 vs current 3-run 재검증 (2026-10-06)

stage47 1-run에서 win150이 WHY 질문 2건을 구제 + FP 5건 방어한 것을
3-run majority로 확정/기각. 대상 쿼리만 소량 재호출.

- 대상: WHY 2건(코덱스·마우스) + FP방어 5건(provider/임베딩버전/deepseek/API키/golden_eval_v2)
  + 대조 current 전용 2건(gemini 별칭·codex CLI) = 9쿼리 × 3-run × 2 cond = 54콜
- majority: 3회 중 2회 이상 hit/FP면 채택
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
INSTR = "Choose the single candidate that best directly answers the question. If none is usable evidence, choose the final abstain option."

# 대상 쿼리: (grp, query, gold_id)
TARGETS = [
    ("op", "코덱스 앱이 PC 느려지게 한 원인 뭐였어?", None),
    ("op", "마우스 버벅임 원인 조사 결과?", None),
    ("noans", "provider가 뭐지?", None),
    ("noans", "임베딩 모델을 bekko-a8m으로 바꾸기 전에 쓰던 모델의 정확한 버전이 뭐야?", None),
    ("noans", "deepseek 스트림 오류가 프롬프트 길이 초과 때문이었던 적 있어?", None),
    ("noans", "API 키를 코드에 하드코딩하던 규칙이 있었어?", None),
    ("noans", "golden_eval_v2에 영어 쿼리가 포함된 적이 있어?", None),
    ("op", "gemini 별칭으로 모델 호출되나?", None),
    ("op", "codex CLI에서 메모리 기록되나?", None),
]

def load_gold(snap):
    s = sqlite3.connect(snap)
    s.row_factory = sqlite3.Row
    # stage47 raw에서 gold_id 가져오기
    st47 = json.load(open(os.path.join(DATA, "stage47_win150.json"), encoding="utf-8"))
    cur = {r["query"]: r for r in st47[0]["records"]}
    out = []
    for grp, q, _ in TARGETS:
        gid = None
        if q in cur:
            gid = cur[q].get("gold_id")
        out.append((grp, q, gid))
    return s, out


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


def run_choice(client, query, rows, body_fn):
    labels = [body_fn(c, query) for c in rows]
    j_labels = labels + [ABSTAIN_CURRENT]
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
        return None, abstain_p, None  # abstain
    return idx, abstain_p, None


def body_current(c, query):
    return j1p._excerpt(j1p._query_window((c.get("content") or ""), query, 300), 150) or "n/a"


def body_win150(c, query):
    return j1p._query_window((c.get("content") or ""), query, 150) or "n/a"


def main():
    client = _jev_client()
    print("client:", "OK" if client else "NONE", flush=True)
    assert client
    s, targets = load_gold(SNAP)
    conds = {"current": body_current, "win150": body_win150}
    results = {}
    for grp, q, gid in targets:
        rows = build_pool(s, q)
        results[q] = {"grp": grp, "gold_id": gid, "pool_n": len(rows), "runs": {}}
        for cond, fn in conds.items():
            hits = []
            for run_i in range(3):
                idx, ap, err = run_choice(client, q, rows, fn)
                hit = None
                if grp == "op" and idx is not None and 0 <= idx < len(rows):
                    hit = rows[idx].get("id") == gid if gid else False
                abst = idx is None and err is None
                picks = idx if idx is not None else None
                hits.append({"idx": picks, "abstain": abst, "hit": hit,
                             "abstain_p": round(ap, 3), "err": err})
                time.sleep(0.25)
            results[q]["runs"][cond] = hits
        # 요약: op는 hit, noans는 abstain(방어) 기준
        def summ(hits_list):
            if grp == "op":
                return sum(1 for h in hits_list if h["hit"])
            return sum(1 for h in hits_list if h["abstain"])
        print(f"{grp:5} | {q[:40]:42} | cur = {summ(results[q]['runs']['current'])}/3 "
              f"w150 = {summ(results[q]['runs']['win150'])}/3", flush=True)
    json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "targets": len(TARGETS), "results": results},
              open(os.path.join(DATA, "stage47b_win150_3run.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("저장 완료: stage47b_win150_3run.json", flush=True)


if __name__ == "__main__":
    main()