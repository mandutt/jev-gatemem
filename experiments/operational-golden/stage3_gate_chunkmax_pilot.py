"""Stage-3 pilot: "gate input chunking" — modify _filter_and_rank's lexical
overlap to compute per-800-char-chunk (max over chunks) instead of whole row.

0 JEV calls. Live DB read-only. No production code touched: we monkeypatch a
copy of the gate function in-process and evaluate on:
  A) real-usage gold 19 (stage2_final_gold.json) — target recovery
  B) op-90 regression (golden_eval_v3.json 100 rows incl noans) — must not regress
     (op 90: hit@3 proxy = does gold row pass pool+gate; we compare gate-pass
      against the production `_filter_and_rank` baseline on the same scratch DB)

Implementation of the chunk-max gate: for each row, split content into 800-char
chunks (paragraph-aware), compute overlap & coverage per chunk, take the max.
If any chunk satisfies min_distinctive / min_coverage, the row passes.
Also apply the same vec-rank-2 exemption semantics as the real gate.
"""
import os, re, sqlite3, json, sys, time, tempfile
import numpy as np

REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware"
sys.path.insert(0, REPO)
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
SCRATCH = os.path.join(os.environ.get("TMPDIR", tempfile.gettempdir()), "jev_scratch_chunk")
import tempfile
SCRATCH = os.path.join(os.environ.get("TMPDIR", tempfile.gettempdir()), "jev_scratch_chunk")
os.makedirs(SCRATCH, exist_ok=True)
SCRATCH_DB = os.path.join(SCRATCH, "mnemosyne_scratch.db")

import sqlite_vec
def connect_db(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        c.enable_load_extension(True)
        sqlite_vec.load(c)
    except Exception as e:
        print("  sqlite_vec load failed:", e)
    return c

# fresh scratch copy
if os.path.exists(SCRATCH_DB):
    os.remove(SCRATCH_DB)
src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
dst = connect_db(SCRATCH_DB)
src.backup(dst)
src.close(); dst.close()
conn = connect_db(SCRATCH_DB)
print("scratch DB ready")

# ---- import pipeline primitives --------------------------------------------
import mnemosyne.core.beam as beam_mod
from gateway.j1_pipeline import build_lane_pool, _rrf_merge
# the REAL _filter_and_rank for baseline; we'll monkeypatch a chunk-max variant
from gateway.j1_pipeline import _filter_and_rank as _real_filter_and_rank

# ---- chunk-max gate implementation -----------------------------------------
_CHUNK_SIZE = 800

def _chunk_text(content: str, size: int = _CHUNK_SIZE):
    paras = re.split(r"\n+", content)
    out, acc = [], ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(acc) + len(p) + 1 > size and acc:
            out.append(acc)
            acc = p
        else:
            acc = acc + "\n" + p if acc else p
    if acc:
        out.append(acc)
    res = []
    for ch in out:
        while len(ch) > size + 300:
            res.append(ch[:size])
            ch = ch[size:]
        res.append(ch)
    return res

def _tokenize(text):
    # same as j1_pipeline._tokenize (syllable for CJK, word for ASCII)
    c = text.lower()
    tokens = {ch for ch in c if "\u4e00" <= ch <= "\u9fff" or "\uac00" <= ch <= "\ud7af"}
    for tok in re.findall(r"[^\W_][\w./:-]*", c, re.IGNORECASE | re.UNICODE):
        tok = tok.strip(".,;!?()[]{}")
        if len(tok) > 2 and tok not in _STOPWORDS:
            tokens.add(tok)
    return tokens

# copy stopwords from pipeline
from gateway.j1_pipeline import _STOPWORDS, _PREFETCH_EXCLUDED_PREFIXES, _SOURCE_QUALITY, _RAW_SOURCES, _synthesize_histories

def _filter_and_rank_chunkmax(rows, query, min_distinctive=2, min_coverage=0.30):
    """Same as _filter_and_rank but overlap/coverage computed per 800-char chunk,
    taking the max across chunks. Rows <= 800 chars behave identically."""
    q_tokens = _tokenize(query) - _STOPWORDS
    if not q_tokens:
        return []
    out = []
    for row in rows:
        r = _synthesize_histories(row)
        content = (r.get("content") or "").strip()
        if not content or len(content.split()) <= 1:
            continue
        if content.upper().startswith(_PREFETCH_EXCLUDED_PREFIXES):
            continue
        # CHUNK-MAX lexical overlap
        chunks = _chunk_text(content) if len(content) > _CHUNK_SIZE else [content]
        best_overlap, best_cov = 0, 0.0
        for ch in chunks:
            ch_toks = _tokenize(ch)
            ov = q_tokens & ch_toks
            if len(ov) > best_overlap:
                best_overlap = len(ov)
            cov = len(ov) / len(q_tokens) if q_tokens else 0
            if cov > best_cov:
                best_cov = cov
        if best_overlap < min_distinctive:
            lane_ranks = r.get("_lane_ranks") or {}
            vr = lane_ranks.get("vec_rank")
            if not (vr is not None and vr <= 2 and best_overlap >= 1):
                continue
        if best_cov < min_coverage:
            lane_ranks = r.get("_lane_ranks") or {}
            vr = lane_ranks.get("vec_rank")
            if not (vr is not None and vr <= 2 and best_overlap >= 1):
                continue
        # rest identical
        source = str(r.get("source") or "").lower()
        quality = _SOURCE_QUALITY.get(source, 1.0)
        if source in _RAW_SOURCES:
            quality *= 0.72
        if content.upper().startswith("[USER]"):
            quality *= 0.68
        elif content.upper().startswith("[IDENTITY]"):
            quality *= 0.80
        score = float(r.get("score") or 0.0)
        signal = max(float(r.get("keyword_score") or 0.0),
                     float(r.get("fts_score") or 0.0),
                     float(r.get("dense_score") or 0.0))
        import_ = min(max(float(r.get("importance") or 0.0), 0.0), 1.0)
        r["_adjusted"] = (score * 0.65 + signal * 0.35 + import_ * 0.05) * quality
        out.append(r)
    out.sort(key=lambda r: r["_adjusted"], reverse=True)
    return out

# ---- eval helper ------------------------------------------------------------
def j1_imp(cx, k=50):
    from gateway.j1_pipeline import _imp_search
    return _imp_search(cx, k=k)
def j1_graph(cx, q, k=50):
    from gateway.j1_pipeline import _graph_lane_search
    return _graph_lane_search(cx, q, k=k)

def run(cx, q, target_cid, gate_fn):
    def recall_raw(kind, arg, k):
        if kind == "fts": return beam_mod._fts_search_working(cx, arg, k=k)
        if kind == "vec":
            qemb = beam_mod._embeddings.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(cx, qemb[0], k=k)
        if kind == "imp": return j1_imp(cx, k=k)
        if kind == "graph": return j1_graph(cx, arg, k=k)
        if kind == "get":
            r = cx.execute("SELECT id, content, source, importance, metadata_json FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = cx.execute("SELECT id, content, source, importance, metadata_json FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            if not r: return None
            return {"id": r[0], "content": r[1], "source": r[2], "importance": r[3], "metadata_json": r[4]}
        return []
    pool = build_lane_pool(recall_raw, q)
    # 운영 게이트 파라미터: 라이브 데몬은 (1, 0.0) 완화값 (10-01 커밋 c3aee3a, RPC 파이프라인 경로)
    gate_kw = {"min_distinctive": 1, "min_coverage": 0.0} if os.environ.get("GATE_OP") == "1" else {}
    f_real = _real_filter_and_rank(pool, q, **gate_kw)[:40]
    f_new = gate_fn(pool, q, **gate_kw)[:40]
    def ids_hit(fids, target):
        return target in fids or any(isinstance(f, str) and f.startswith(target + ":") for f in fids)
    return (ids_hit([r.get("id") for r in f_real], target_cid),
            ids_hit([r.get("id") for r in f_new], target_cid))

# ---- A) real-usage gold 19 --------------------------------------------------
gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_final_gold.json"), encoding="utf-8"))
print(f"\n=== A) real-usage gold: {len(gold)} ===")
resA = []
for g in gold:
    hp_real, hp_new = run(conn, g["query"], g["row_id"], _filter_and_rank_chunkmax)
    resA.append((g["row_id"], hp_real, hp_new))
print(f"gate pass (top40): real {sum(r[1] for r in resA)}/{len(resA)}   chunkmax {sum(r[2] for r in resA)}/{len(resA)}")
for rid, hr, hn in resA:
    print(f"  {rid[:14]} real={int(hr)} chunk={int(hn)} {'NEW' if hn and not hr else ('LOST' if hr and not hn else '')}")

# ---- B) op-90 regression ----------------------------------------------------
print(f"\n=== B) op-90 regression ===")
gold90 = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "golden_eval_v3.json"), encoding="utf-8"))
# gold queries only (exclude noans)
queries90 = [(g["gold"], g["query"]) for g in gold90 if g.get("gold")]
results90 = []
for target, q in queries90:
    hp_real, hp_new = run(conn, q, target, _filter_and_rank_chunkmax)
    results90.append((target, hp_real, hp_new))
n = len(results90)
print(f"op-90 gold gate pass: real {sum(r[1] for r in results90)}/{n}   chunkmax {sum(r[2] for r in results90)}/{n}")
regress = [r for r in results90 if r[1] and not r[2]]
improve = [r for r in results90 if not r[1] and r[2]]
print(f"regressions (real pass -> chunk fail): {len(regress)}")
for r in regress[:10]:
    print(f"  {r[0][:14]}")
print(f"improvements (chunk pass -> real fail): {len(improve)}")
for r in improve[:10]:
    print(f"  {r[0][:14]}")

conn.close()
print("\nDONE")