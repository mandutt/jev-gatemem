# -*- coding: utf-8 -*-
"""stage103: 한국어 형태소 보조 벡터 실측 — Kiwi 형태소 FTS가 pool_recall miss 구제하는가 (0콜)

AnchorMind(MorphemeTokenizer) + core.today 5편(Kiwi) 참고. 목표:
현재 FTS(unicode61 공백 분리)가 놓치는 gold를 형태소 분석(명사/외국어/숫자) 기반
보조 검색이 구제하는지 + 발동률(stage90 기준) 측정. JEV 콜 0회.

- 셋: op-90 (스냅샷 고정)
- miss 정의: 현재 build_pool(_filter_and_rank 후 60컷)에 gold가 없는 쿼리
- 보조 검색: Kiwi 형태소(명사 NNG/NNP/NNB/NP + 외국어 SL + 숫자 SN + 한자 SH)로
  쿼리·메모리를 토큰화 → 형태소 유니온 FTS (like 검색) → gold 포함 여부
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import sqlite_vec
from gateway import j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod
from kiwipiepy import Kiwi

SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006.db")
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")

s = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
s.row_factory = sqlite3.Row
s.enable_load_extension(True)
sqlite_vec.load(s)

kiwi = Kiwi()

# 품사: 명사 계열 + 외국어/숫자/한자 (AnchorMind PROPER_NOUN_POS = NNP/SL/SH 유사)
KEEP_POS = {"NNG", "NNP", "NNB", "NP", "NR", "SL", "SN", "SH", "MAG"}

def morph_tokens(text: str, max_n=20) -> list[str]:
    """Kiwi 형태소 중 내용어만 추출 (조사·어미·접사 제외)"""
    try:
        out = []
        for tok in kiwi.tokenize(text):
            pos = tok.tag
            if pos.startswith("N") or pos in ("SL", "SN", "SH", "MAG"):
                w = tok.form
                if len(w) >= 2 and w not in ("있다", "없다", "하다", "되다"):
                    out.append(w)
            if len(out) >= max_n:
                break
        return out
    except Exception:
        return []

def build_pool(q, cap=60):
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
    pool = j1p.build_lane_pool(recall_raw, q)
    pool = j1p._filter_and_rank(pool, q)[:cap]
    return pool

def load_op90():
    with open(os.path.join(DATA, "stage54_op90_regress.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    recs = None
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "gold" in v[0]:
                recs = v
                break
    return [{"q": r.get("query") or r.get("q"), "gold": r.get("gold") or r.get("gold_id")} for r in recs if (r.get("query") or r.get("q")) and (r.get("gold") or r.get("gold_id"))]

def main():
    queries = load_op90()
    print(f"op-90: {len(queries)}")

    # 현재 pool miss 식별
    results = []
    miss_n = 0
    for item in queries:
        q, gold = item["q"], item["gold"]
        pool = build_pool(q)
        ids = [c["id"] for c in pool]
        in_pool = gold in ids
        if not in_pool:
            miss_n += 1
            # 1) 현재 FTS 단독
            fts = beam_mod._fts_search_working(s, q, k=200)
            fts_ids = [r["id"] for r in fts]
            # 2) 형태소 보조: 쿼리 형태소로 메모리에서 LIKE 검색 (형태소 유니온)
            q_toks = morph_tokens(q)
            morph_hit = None
            if q_toks:
                # 형태소 전부 AND 매칭하는 working_memory 검색 (LIKE)
                rows = s.execute(
                    "SELECT id, content FROM working_memory WHERE superseded_by IS NULL "
                    "AND (valid_until IS NULL OR valid_until > ?) AND length(content) > 0",
                    (__import__("datetime").datetime.now().isoformat(),),
                ).fetchall()
                # 형태소 포함 점수: 포함 개수 / 총 개수
                best, best_score = None, 0
                for r in rows:
                    content = r["content"] or ""
                    hits = sum(1 for t in q_toks if t in content)
                    if hits > best_score:
                        best_score, best = hits, r["id"]
                if best_score >= max(1, len(q_toks) * 0.3):
                    morph_hit = {"id": best, "score": best_score, "n_toks": len(q_toks)}
            gold_row = s.execute("SELECT id, content FROM working_memory WHERE id=?", (gold,)).fetchone()
            if not gold_row:
                gold_row = s.execute("SELECT id, content FROM episodic_memory WHERE id=?", (gold,)).fetchone()
            results.append({
                "q": q, "gold": gold,
                "gold_content": (gold_row["content"] if gold_row else "")[:80],
                "gold_in_fts200": gold in fts_ids,
                "q_toks": q_toks,
                "morph_best_id": morph_hit["id"] if morph_hit else None,
                "morph_best_is_gold": (morph_hit["id"] == gold) if morph_hit else False,
                "morph_score": morph_hit["score"] if morph_hit else 0,
            })
            if results and len(results) % 5 == 0:
                print(f"  miss {len(results)}...", flush=True)

    print(f"\n현재 pool miss: {miss_n}/90")
    morph_saved = sum(1 for r in results if r["morph_best_is_gold"])
    print(f"형태소 보조로 gold 구제: {morph_saved}/{miss_n}")
    print("\nmiss 상세:")
    for r in results:
        print(f"  fts200={r['gold_in_fts200']} morph_gold={r['morph_best_is_gold']} toks={r['q_toks'][:8]} | {r['q'][:35]}")
        print(f"    gold: {r['gold_content'][:60]}")

    json.dump(results, open(os.path.join(DATA, "stage103_morph_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n저장: stage103_morph_raw.json")

if __name__ == "__main__":
    main()