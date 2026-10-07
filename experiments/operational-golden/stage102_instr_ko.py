# -*- coding: utf-8 -*-
"""stage102: 한국어 지시문 A/B — KO vs EN 지시문·abstain 라벨 paired 비교 (2026-10-08)

core.today 6편 실측: Jev rerank에서 한국어 지시문이 영어보다 미세 우위
(0.929→0.933, 정답1등 89.4→90.6%, n=85 — 잡음 가능). 우리 INSTR·abstain 라벨은
전부 영어. 같은 세션 paired로 한국어 지시문이 우리 데이터에서 유효한지 판정.

설계 (stage101 구조 재사용):
- cond en: 현행 (m48.INSTR + ABSTAIN_CURRENT 영어)
- cond ko: 한국어 지시문 + 한국어 abstain 라벨
- 셋: op-90 + noans-50 + live-60 = 200쿼리 × 2 cond = 400콜
- 같은 세션 alternate (paired) — 풀 순서는 cond 간 동일
- 판정: hit@1/3·abstain·FP 3지표 + flip 대조표 (stage54 gold_after 정의)
"""
from __future__ import annotations

import json
import os
import sys
import time
import sqlite3

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

SNAP = m48.SNAP
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
s.row_factory = sqlite3.Row

# sqlite-vec 로드 (fallback 방지 — 데몬 venv에서 실행)
try:
    import sqlite_vec
    s.enable_load_extension(True)
    sqlite_vec.load(s)
except Exception as exc:
    print(f"[warn] sqlite_vec load 실패: {exc}", file=sys.stderr)

INSTR_EN = m48.INSTR
ABSTAIN_EN = m48.ABSTAIN_CURRENT
INSTR_KO = "질문에 가장 직접적으로 답하는 후보를 하나 고르세요. 쓸 만한 근거가 없으면 마지막 abstain 선택지를 고르세요."
ABSTAIN_KO = "질문에 답하는 데 쓸 수 있는 근거가 되는 후보가 없습니다"

def load_op90():
    with open(os.path.join(DATA, "stage54_op90_regress.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    recs = None
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "gold" in v[0]:
                recs = v
                break
    return [{"q": r.get("query") or r.get("q"), "gold": r.get("gold") or r.get("gold_id"), "src": "op"} for r in recs if (r.get("query") or r.get("q")) and (r.get("gold") or r.get("gold_id"))]

def load_noans():
    with open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    for run in d.get("runs", []):
        if run.get("cond") != "current":
            continue
        recs = run.get("records") or []
        out = [{"q": r["query"], "gold": None, "src": "noans"} for r in recs if r.get("grp") == "noans" and r.get("query")]
        if out:
            return out[:50]
    return []

def load_live():
    qs = m48.load_queries(SNAP)
    return [{"q": q, "gold": None, "src": "live"} for q in qs]

def recall_raw_factory(q):
    def recall_raw(kind, arg, kk):
        if kind == "fts":
            return beam_mod._fts_search_working(s, arg, k=kk)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb):
                return []
            return beam_mod._wm_vec_search(s, qemb[0], k=kk)
        if kind == "imp":
            return j1p._imp_search(s, k=kk)
        if kind == "graph":
            return j1p._graph_lane_search(s, arg, k=kk)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw

def build_pool(q, cap=60):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = j1p._filter_and_rank(pool, q)[:cap]
    return pool

CLIENT = _jev_client()
assert CLIENT
_API = getattr(CLIENT, "_jev_api", None) or "https://api.typesafe.ai/v1/systemone"
_rot = getattr(CLIENT, "_jev_rotator", None)

_LAST = [0.0]
def throttle():
    while True:
        now = time.time()
        if now - _LAST[0] >= 0.34:
            _LAST[0] = now
            return
        time.sleep(0.05)

def post(state, questions):
    for attempt in range(10):
        throttle()
        try:
            resp = CLIENT.post(_API, json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=25)
            if resp.status_code == 429:
                body = resp.text or ""
                if "daily free allowance" in body or "resets at" in body:
                    try:
                        _rot.exhausted_until[_rot.last_key] = time.monotonic() + 3600
                    except Exception:
                        pass
                if _rot is not None and hasattr(_rot, "on_429"):
                    try:
                        nk = _rot.on_429()
                    except Exception:
                        nk = None
                    if nk:
                        CLIENT.headers["Authorization"] = f"Bearer {nk}"
                time.sleep(2.0)
                continue
            if resp.status_code == 503:
                time.sleep(3.0)
                continue
            return resp
        except Exception:
            time.sleep(2.0)
    return None

def run_choice(q, rows, instr, abstain_label):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows[:60]]
    j_labels = labels + [abstain_label]
    state = j1p.build_state(q, rows)
    questions = {"best": {"type": "choice", "instructions": instr,
                          "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    resp = post(state, questions)
    if resp is None:
        return None, None, "noresp"
    if resp.status_code != 200:
        return None, None, f"http{resp.status_code}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(j_labels)-1}", 0.0)) if probs else 0.0
    try:
        idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception:
        idx = None
    abstain = (idx is None) or (idx == len(j_labels) - 1) or (ap > 0.3)
    return idx, abstain, None

def main():
    queries = load_op90() + load_noans() + load_live()
    print(f"쿼리: op={len(load_op90())} noans={len(load_noans())} live={len(load_live())} total={len(queries)}")
    results = []
    for qi, item in enumerate(queries):
        q = item["q"]
        gold = item.get("gold")
        pool = build_pool(q)
        if not pool:
            results.append({"q": q, "src": item["src"], "gold": gold, "err": "empty_pool", "en": None, "ko": None})
            print(f"  [{qi}] empty pool", flush=True)
            continue
        gold_rank = None
        if gold:
            ids = [c["id"] for c in pool]
            gold_rank = ids.index(gold) + 1 if gold in ids else None
        # cond en 먼저, cond ko 다음 (같은 pool·같은 세션)
        idx_en, abst_en, err_en = run_choice(q, pool, INSTR_EN, ABSTAIN_EN)
        idx_ko, abst_ko, err_ko = run_choice(q, pool, INSTR_KO, ABSTAIN_KO)
        results.append({
            "q": q, "src": item["src"], "gold": gold,
            "pool_n": len(pool), "gold_rank": gold_rank,
            "en": {"idx": idx_en, "abstain": abst_en, "err": err_en},
            "ko": {"idx": idx_ko, "abstain": abst_ko, "err": err_ko},
        })
        if (qi + 1) % 20 == 0:
            print(f"  {qi+1}/{len(queries)}", flush=True)

    json.dump(results, open(os.path.join(DATA, "stage102_instr_ko_raw.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장: stage102_instr_ko_raw.json")

if __name__ == "__main__":
    main()