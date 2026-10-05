#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run R — recall-strengthening pilot (hippo-style retrieval strength, α sweep).

측정 대상: 우리 파이프라인이 이미 쌓는 recall_count/last_recalled 신호를
게이트(무결) 앞단의 pool 순서에 반영하면, JEV choice rerank의 hit@3가
개선되는가? (0콜 추가 — JEV 호출 수 불변)

설계 (사전 고정):
- 골든셋: golden_eval_v2.json 중 gold_id 보유 + NO_ANSWER 제외 (op 90건)
- 조건: baseline(현행) + recall-strengthened(α ∈ {0.05, 0.15, 0.3} — 승수
  log2(1+recall_count), import 모자: max(importance, α·log2(1+rc)))
- 위치: pipeline의 게이트(_filter_and_rank)는 무결하게 통과 → top-40 컷
  직전에만 순서 보정 (강화한 행이 상단으로)
- metric: hit@3 = gold가 상위 3안에 (abstain=miss, gold 미포함=miss)
- JEV 호출: op 90건 × 2조건(baseline / α=0.3) = 180콜, 60s 드레인 병렬 2
- α=0.05/0.15는 오프라인에서 α=0.3 raw의 winner/풀 순서로부터 상한 계산
  (JEV 점수는 후보 텍스트만 보므로 winner 결정은 풀 구성과 독립)

실행: jev-mem venv python으로. 결과: data/runR_recall_strength_raw.json
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
from collections import Counter

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
WORKERS = 2            # 무료 레인 안전값: 병렬 2 + 60s 드레인
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"
CHOICE_INSTR = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. Consider directness and specificity. "
    "If no candidate is usable evidence for answering the question, pick the last option."
)

ALPHAS = [0.05, 0.15, 0.3]
RUN_LIVE_ALPHA = 0.3   # 라이브 JEV 호출은 α=0.3만


def chunks(text, limit=8000):
    return [text[i:i + limit] for i in range(0, len(text), limit)] or [""]


def get_winreg_key(name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except OSError:
        return None


from keyring import SmartRotator
rot = SmartRotator()
print("키 상태:", rot.stats(), flush=True)


def post(url, body, key, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                rot.on_429()   # 키 회전 (같은 조직 키면 순서 변경만)
                time.sleep(1.5 * (attempt + 1))
                last = e
                continue
            return e.code, {"__msg": str(e)}
        except Exception as e:
            if attempt == 5:
                return -1, {"__msg": f"{type(e).__name__}: {e}"}
            time.sleep(1.5)
            last = e
    return 429, {"__msg": "rate limited"}


def choice_call(key, query, cands):
    labels = [(c.get("content") or "")[:100] or "n/a" for c in cands]
    j_labels = list(labels) + [ABSTAIN_LABEL]
    body = {"model": MODEL, "state": {"question": query, "candidates": []},
            "questions": {"best": {"type": "choice", "instructions": CHOICE_INSTR,
                                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}}
    status, resp = post(URL, body, key)
    if status != 200:
        return None, None, f"http-{status}"
    cost = (resp.get("usage") or {}).get("cost", None)
    rot.set_cost(cost)
    ans = (resp.get("answers") or {}).get("best") or {}
    ch = ans.get("choice")
    if ch is None:
        return None, cost, "no-choice"
    i = int(str(ch).lstrip("c"))
    if i == len(labels):
        return -1, cost, None  # abstain
    if not (0 <= i < len(labels)):
        return None, cost, "bad-idx"
    return i, cost, None


def get_beam_refs():
    os.environ.setdefault("MNEMOSYNE_DB", LIVE_DB)
    import gateway.j1_pipeline as j1p
    import mnemosyne.core.beam as bm
    from mnemosyne.core import embeddings as emb_mod
    b = bm.BeamMemory(session_id="runR")

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


def stage1_pool(recall_raw, j1p, query, exclude_ids=None, k=40):
    """현행 파이프라인 그대로 — 게이트(_filter_and_rank) 후 top-40."""
    pool = j1p.build_lane_pool(recall_raw, query)
    if exclude_ids:
        pool = [p for p in pool if p.get("id") not in exclude_ids]
    ranked = j1p._filter_and_rank(pool, query) if pool else []
    return ranked[:k]


def recall_boost(row, alpha):
    """hippo식 retrieval strength 승수: log2(1+recall_count).
    중요도와 겹치지 않게 max(importance, alpha*log2(1+rc)) 형태로
    'recall이 importance를 밀어올린다'로만 작동."""
    rc = row.get("recall_count") or 0
    imp = row.get("importance") or 0.0
    try:
        imp = float(imp)
    except (TypeError, ValueError):
        imp = 0.0
    if rc <= 0:
        return imp
    import math
    boost = alpha * math.log2(1 + rc)
    return max(imp, boost)


def apply_alpha(pool, alpha):
    """순서 보정: 강화값 desc로 재정렬 (동률 시 기존 순서 보존).
    게이트 score와 무관하게 pool 상단을 재배열하는 로컬 수정."""
    out = []
    for i, row in enumerate(pool):
        r = dict(row)
        r["_strength"] = recall_boost(row, alpha)
        r["_orig_idx"] = i
        out.append(r)
    out.sort(key=lambda r: (-r["_strength"], r["_orig_idx"]))
    return out


def corpus_hash():
    conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    n = conn.execute("SELECT COUNT(*) FROM (SELECT id FROM working_memory UNION ALL SELECT id FROM episodic_memory)").fetchone()[0]
    # recall_count 가용 행 (라이브 실측용)
    n_rc = conn.execute("SELECT COUNT(*) FROM working_memory WHERE recall_count > 0").fetchone()[0]
    conn.close()
    return {"total": n, "with_recall": n_rc}


def compute_hit3(rec):
    """hit@3: gold가 상위 3안에 있는가 (abstain=miss, gold 미포함=miss)."""
    if rec.get("choice_abstain") or rec.get("winner_id") is None:
        return False, "abstain/miss"
    gr = rec.get("gold_rank")
    if gr is None:
        return False, "gold-not-in-pool"
    return gr <= 3, f"rank={gr}"


def main():
    gold_all = json.load(open(os.path.join(DATA, "golden_eval_v2.json"), encoding="utf-8"))
    op = [x for x in gold_all if x.get("gold_id") and x.get("cat") != "NO_ANSWER"]
    print(f"op {len(op)}건", flush=True)

    by_id = {}
    conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    for r in conn.execute("SELECT id, recall_count, importance FROM working_memory UNION ALL SELECT id, recall_count, importance FROM episodic_memory"):
        by_id[r[0]] = {"recall_count": r[1] or 0, "importance": r[2] or 0.0}
    conn.close()
    print(f"by_id {len(by_id)}건 (recall_count 보유 {sum(1 for v in by_id.values() if v['recall_count']>0)})", flush=True)

    recall_raw, j1p, b = get_beam_refs()

    recs = []

    def run_one(x, alpha):
        q = x["query"]
        gid = x["gold_id"]
        rec = {"qid": x["gold_id"], "query": q, "alpha": alpha, "gold_id": gid,
               "cat": x.get("cat"), "axis": x.get("axis")}
        try:
            pool = stage1_pool(recall_raw, j1p, q, k=40)
        except Exception as e:
            rec["err"] = f"pool {type(e).__name__}: {e}"
            return rec
        pool = [p for p in pool if p.get("id") in by_id]
        if not pool:
            rec["err"] = "empty-pool"
            return rec
        # ★ hydration row에는 recall_count가 없음 — by_id(라이브 DB)에서 주입
        for p in pool:
            meta = by_id.get(p.get("id"), {})
            p["recall_count"] = meta.get("recall_count", 0)
            p["importance"] = meta.get("importance", 0.0)
        # 실측 조건: baseline pool 그대로, α 별 정렬만 다르게 (동일 JEV 호출)
        if alpha == 0.0:
            cands = pool[:MAX_CAND]
        else:
            ap = apply_alpha(pool, alpha)
            cands = ap[:MAX_CAND]
        rec["n_pool"] = len(cands)
        rec["pool_ids"] = [c.get("id") for c in cands]
        rec["cand_strength"] = [c.get("_strength") for c in cands[:10]]

        key = rot.next()
        idx, cost, err = choice_call(key, q, cands)
        rec["cost"] = cost
        if err:
            rec["err"] = err
            return rec
        if idx == -1:
            rec["choice_abstain"] = True
            rec["winner_id"] = None
            rec["gold_rank"] = None
            return rec
        idx = idx if 0 <= idx < len(cands) else len(cands) - 1
        rec["choice_abstain"] = False
        rec["winner_id"] = cands[idx].get("id")
        order_ids = [cands[idx]["id"]] + [c["id"] for i, c in enumerate(cands) if i != idx]
        rec["gold_rank"] = (order_ids.index(gid) + 1) if gid in order_ids else None
        return rec

    tasks = [(x, 0.0) for x in op] + [(x, RUN_LIVE_ALPHA) for x in op]
    print(f"총 {len(tasks)}건 (baseline {len(op)} + α={RUN_LIVE_ALPHA} {len(op)}) — JEV 1콜/건", flush=True)

    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(run_one, *t): t for t in tasks}
        for f in futs:
            recs.append(f.result())
            done += 1
            if done % 20 == 0:
                el = time.time() - t0
                print(f"  {done}/{len(tasks)} ({el:.0f}s)", flush=True)

    out = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": MODEL, "lane": "free",
        "corpus": corpus_hash(),
        "alpha_live": RUN_LIVE_ALPHA,
        "n": len(recs),
        "records": recs,
    }
    with open(os.path.join(DATA, "runR_recall_strength_raw.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {DATA}/runR_recall_strength_raw.json", flush=True)

    # 즉석 요약
    for alpha in [0.0, RUN_LIVE_ALPHA]:
        rs = [r for r in recs if r.get("alpha") == alpha]
        hit = sum(1 for r in rs if compute_hit3(r)[0])
        abst = sum(1 for r in rs if r.get("choice_abstain"))
        errs = sum(1 for r in rs if r.get("err"))
        print(f"α={alpha}: n={len(rs)} hit@3={hit} ({hit/max(len(rs),1)*100:.1f}%) abstain={abst} err={errs}", flush=True)


if __name__ == "__main__":
    main()