"""J1 rerank pipeline — production integration of the Phase 1 recipe.

Measured recipe (see mnemosyne-ops skill / jev-retrieval-rerank.md):
  - lane pool (FTS 60 + vec 60, RRF k=30) fixes the pool problem:
    gold-in-pool 8% -> 79%.
  - Jev "choice" question (1 call) lifts the single best candidate to rank 1.
  - Fallback contract (spec §19): ANY Jev failure -> pool-only ranking.
  - Jev OFF (env JEV_RERANK=0) -> pool-only ranking (identical shape).

This module is backend-agnostic: it takes a *raw recall function* and returns
ranked rows. It lives in the middleware repo so harness code stays thin.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable, List, Optional

from mnemosyne.core import beam as beam_mod

log = logging.getLogger(__name__)

# NOTE: do NOT add a module-level `from gateway.trace import ...` here.
# In a real Hermes process the middleware gateway package is loaded under the
# private alias `__j1mw_gateway` (see harnesses/j1_access.py); a bare import
# resolves against the restored core `gateway` package and raises
# ModuleNotFoundError, silently killing the J1 prefetch (observed 2026-09-27).
# Use _jtrace() below — it resolves the trace module lazily through the same
# alias accessor, falling back to the middleware repo path for standalone runs.


def _jtrace(event: str, fields: dict) -> None:
    """Lazy trace() call that survives gateway shadowing.

    Resolution order:
      1. `__j1mw_gateway.trace` (the middleware gateway alias installed by
         harnesses/j1_access.py — the alive Hermes process path).
      2. `gateway.trace` (standalone venv / scripts where no shadow exists).
      3. direct file load from the middleware repo (last resort).
    Never raises: tracing must not break the prefetch path.
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path

        mod = None
        alias = _sys.modules.get("__j1mw_gateway")
        if alias is not None:
            t = getattr(alias, "trace", None)
            if t is not None:
                # `alias.trace` may be the submodule (once loaded) or already
                # the function (first call); unwrap module -> function.
                mod = getattr(t, "trace", None) or t
        if mod is None:
            try:
                from gateway.trace import trace as _t  # standalone path
                mod = _t
            except Exception:
                mod = None
        if mod is None:
            import importlib.util

            _repo = _Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
            spec = importlib.util.spec_from_file_location(
                "jev_trace_direct", _repo / "gateway" / "trace.py"
            )
            if spec and spec.loader:
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                mod = m.trace
        if mod is None:
            return
        mod(event, fields)
    except Exception:
        pass  # tracing must never raise

LANE_FTS_BUDGET = 60
LANE_VEC_BUDGET = 60
# vec-rank coverage exemption threshold (Run I/J: gate-missed golds are vec
# rank 1-2; exempting them recovers short colloquial queries). Env-overridable
# for ablation; set 0 to disable the exemption.
VEC_RANK_EXEMPT = int(os.environ.get("JEV_VEC_RANK_EXEMPT", "2"))
LANE_IMP_BUDGET = 8        # importance 보조 lane (CJK 검색 한계 보완)
IMP_MIN_IMPORTANCE = 0.85  # 이 이상의 importance만 보조 lane에 포함
LANE_GRAPH_BUDGET = 10     # graph/fact lane (관계·속성 기반 회수)
RRF_K = 30
POOL_BUDGET = 40          # candidates fed to Jev choice
# JEV state excerpt cap (chars). Env override: JEV_EXCERPT_LIMIT. Default 120.
EXCERPT_LIMIT = int(os.environ.get("JEV_EXCERPT_LIMIT", "120"))
POOL_DEFAULT_TOP = 40     # pool-alone fallback returns this many
JEV_CHOICE_TIMEOUT_S = 5.0   # hard cap; MemoryManager also bounds external prefetch
JEV_ENV_KEY = "JEV_RERANK"
# Run O (2026-10-03): abstain label on the Jev choice question. Default ON;
# set JEV_ABSTAIN=0 to disable (pre-Run-O behavior). Measured: NO_ANSWER
# misinjection 10/10 -> 0/10, gold pick 59/59 preserved, wrong->none 17/17
# were true abstentions (gold absent from pool), tokens +1.0%, latency flat.
ABSTAIN_ENV_KEY = "JEV_ABSTAIN"
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"
ABSTAIN_INSTRUCTION = (
    " If none of the candidates contains usable evidence, "
    "pick the 'no candidate' option."
)

# Align with mnemosyne_hermes prefetch gates (do not import the private
# adapter; re-declared here so this module also works from the middleware
# venv where mnemosyne_hermes is absent).
_SOURCE_QUALITY = {"conversation": 0.72, "task": 1.0}
_PREFETCH_EXCLUDED_PREFIXES = ("[ASSISTANT]",)
_RAW_SOURCES = {"conversation"}


def _tokenize(text: str) -> set:
    """Mirror of mnemosyne_hermes._prefetch_tokens (ASCII + CJK chars)."""
    import re

    c = (text or "").strip()
    if c.upper().startswith(("[USER]", "[ASSISTANT]", "[IDENTITY]")):
        c = c.split("]", 1)[1].strip()
    c = c.lower()
    tokens = {ch for ch in c if "\u4e00" <= ch <= "\u9fff" or "\uac00" <= ch <= "\ud7af"}
    for tok in re.findall(r"[^\W_][\w./:-]*", c, re.IGNORECASE | re.UNICODE):
        tok = tok.strip(".,;!?()[]{}")  # ASCII-only trim; CJK handled above
        if len(tok) > 2 and tok not in _STOPWORDS:
            tokens.add(tok)
    return tokens


_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "be", "but", "by", "do", "for", "go",
    "hi", "how", "i", "if", "in", "is", "it", "me", "my", "no", "of", "ok",
    "on", "or", "so", "the", "to", "u", "we", "what", "why", "yes", "you",
    "about", "after", "before", "because", "could", "from", "have", "into",
})


def _synthesize_histories(row: dict) -> dict:
    """Compute per-row fields the filtered prefetch path expects.

    RRF result rows carry ``{id, rank}`` (FTS) / ``{id, sim}`` (vec) only — the
    shared lane modules return bare dicts. Tuples are (row, rrf_score).
    """
    if "score" not in row:
        row["score"] = float(row.get("sim") or 0.0)
    if "fts_score" not in row:
        row["fts_score"] = float(row.get("keyword_score") or 0.0)
    if "dense_score" not in row:
        row["dense_score"] = float(row.get("sim") or 0.0)
    if "keyword_score" not in row:
        row["keyword_score"] = row.get("fts_score", 0.0)
    return row


def _filter_and_rank(rows: List[dict], query: str,
                     min_distinctive: int = 2, min_coverage: float = 0.30) -> List[dict]:
    """Conservative prefetch gate (lexical + source quality), matching
    mnemosyne_hermes's automatic-injection thresholds. Rows keep relevance."""
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
        overlap = q_tokens & _tokenize(content)
        if len(overlap) < min_distinctive:
            # vec-rank exemption: the embedding lane's top hits pass even with
            # low lexical overlap — short colloquial queries ("provider가 뭐지?")
            # systematically fail cov>=0.30 despite the answer being vec rank 1-2.
            # Run I sim: recovers 7 gate-missed golds (5 at pool rank 1).
            lane_ranks = r.get("_lane_ranks") or {}
            vr = lane_ranks.get("vec_rank")
            if not (vr is not None and vr <= VEC_RANK_EXEMPT and len(overlap) >= 1):
                continue
        if len(overlap) / len(q_tokens) < min_coverage:
            lane_ranks = r.get("_lane_ranks") or {}
            vr = lane_ranks.get("vec_rank")
            if not (vr is not None and vr <= VEC_RANK_EXEMPT and len(overlap) >= 1):
                continue
        source = str(r.get("source") or "").lower()
        quality = _SOURCE_QUALITY.get(source, 1.0)
        if source in _RAW_SOURCES:
            quality *= 0.72
        if content.upper().startswith("[USER]"):
            quality *= 0.68
        elif content.upper().startswith("[IDENTITY]"):
            quality *= 0.80
        # Fixed adjusted score: FTS/vec lane evidence dominates, importance tints.
        score = float(r.get("score") or 0.0)
        signal = max(float(r.get("keyword_score") or 0.0),
                     float(r.get("fts_score") or 0.0),
                     float(r.get("dense_score") or 0.0))
        import_ = min(max(float(r.get("importance") or 0.0), 0.0), 1.0)
        r["_adjusted"] = (score * 0.65 + signal * 0.35 + import_ * 0.05) * quality
        out.append(r)
    out.sort(key=lambda r: r["_adjusted"], reverse=True)
    _jtrace("gate", {
        "query": (query or "")[:120],
        "pool": len(rows),
        "passed": len(out),
    })
    return out


def _rrf_merge(full_rows: List[dict], ranks: dict, k: int = RRF_K) -> List[tuple]:
    """Rows already hydrated; ranks = {id: {lane: rank}}. Returns (row, rrf)."""
    scored = []
    for row in full_rows:
        lane_ranks = ranks.get(row["id"], {})
        if not lane_ranks:
            continue
        rrf = sum(1.0 / (k + r) for r in lane_ranks.values())
        scored.append((row, rrf))
    scored.sort(key=lambda x: -x[1])
    return scored


def _imp_search(conn, k: int = LANE_IMP_BUDGET, min_importance: float = IMP_MIN_IMPORTANCE) -> List[dict]:
    """Importance 보조 lane: 고중요도 메모리를 최신순으로 반환.

    CJK LIKE 검색의 언어/row-limit 한계로 빠지는 고신뢰 메모리
    (importance >= min_importance)를 쿼리와 무관하게 회수한다.
    RRF merge에서 이 lane도 rank 1..k를 부여받아 자연 통합된다.
    """
    try:
        rows = conn.execute(
            "SELECT id, importance, timestamp FROM working_memory"
            " WHERE importance >= ?"
            " AND superseded_by IS NULL"
            " AND (valid_until IS NULL OR valid_until > ?)"
            " ORDER BY timestamp DESC LIMIT ?",
            (min_importance, datetime.now().isoformat(), k),
        ).fetchall()
    except Exception:
        return []
    return [{"id": r["id"], "rank": i} for i, r in enumerate(rows, start=1)]


def _graph_lane_search(conn, query: str, k: int = LANE_GRAPH_BUDGET) -> List[dict]:
    """Graph/fact lane: 관계·속성 기반 회수.

    어휘 검색(FTS/vec)은 단어 일치만 보지만, facts는 "X (predicate) Y" 구조라
    쿼리의 토큰이 subject/object에 있으면 관계로 찾을 수 있다. 세 소스를 합친다:
      1) facts/consolidated_facts: subject/object에 쿼리 토큰 부분매치
         -> source_msg_id / sources_json 의 memory id 회수
      2) graph_edges: gist_<id> -> fact_<id> ctx 엣지 -> gist에 연결된 memory
         (graph_edges.source에서 gist_ 스트립 -> working_memory id)
      3) memoria_facts: key/value에 쿼리 토큰 매치 -> source_memory_id 회수
    노이즈 제어: 매치 토큰 최소 길이 3, confidence >= 0.5, budget k로 컷.
    """
    toks = _query_tokens(query)
    if not toks:
        return []
    found: dict = {}  # memory_id -> best rank
    rank_counter = [0]

    def _add(mid: str):
        if not mid:
            return
        rank_counter[0] += 1
        found.setdefault(mid, rank_counter[0])

    # 1) facts + consolidated_facts (subject/object 매치)
    try:
        for row in conn.execute(
            "SELECT subject, object, source_msg_id, confidence FROM facts"
            " WHERE confidence >= 0.5"
        ).fetchall():
            subj, obj, mid, conf = row
            subj_toks = _query_tokens(str(subj or ""))
            obj_toks = _query_tokens(str(obj or ""))
            if toks.intersection(subj_toks) or toks.intersection(obj_toks):
                _add(mid)
        for row in conn.execute(
            "SELECT subject, object, sources_json, confidence FROM consolidated_facts"
            " WHERE confidence >= 0.5"
        ).fetchall():
            subj, obj, sources_json, conf = row
            subj_toks = _query_tokens(str(subj or ""))
            obj_toks = _query_tokens(str(obj or ""))
            if toks.intersection(subj_toks) or toks.intersection(obj_toks):
                try:
                    import json as _json
                    srcs = _json.loads(sources_json or "[]")
                except Exception:
                    srcs = []
                for mid in srcs:
                    _add(mid)
    except Exception:
        log.debug("J1 lane graph facts failed; continuing", exc_info=True)

    # 2) graph_edges: gist_<id> -> working_memory id
    #    gist 메모리 자체가 쿼리와 관련 있을 때만 추가 (무관한 gist 상시 추가는 노이즈)
    try:
        for row in conn.execute(
            "SELECT DISTINCT source FROM graph_edges WHERE edge_type = 'ctx'"
        ).fetchall():
            src = row[0] or ""
            if not src.startswith("gist_"):
                continue
            gid = src[len("gist_"):]
            # gist가 가리키는 working_memory content를 확인해 쿼리 관련성 검사
            content = None
            for table in ("working_memory", "episodic_memory"):
                r = conn.execute(
                    f"SELECT content FROM {table} WHERE id = ?"
                    f" AND superseded_by IS NULL"
                    f" AND (valid_until IS NULL OR valid_until > ?)",
                    (gid, datetime.now().isoformat()),
                ).fetchone()
                if r:
                    content = r[0]
                    break
            if content and toks.intersection(_query_tokens(content or "")):
                _add(gid)
    except Exception:
        log.debug("J1 lane graph edges failed; continuing", exc_info=True)

    # 3) memoria_facts: key/value 매치
    try:
        for row in conn.execute(
            "SELECT key, value, source_memory_id FROM memoria_facts"
        ).fetchall():
            key, val, mid = row
            key_toks = _query_tokens(str(key or ""))
            val_toks = _query_tokens(str(val or ""))
            if toks.intersection(key_toks) or toks.intersection(val_toks):
                _add(mid)
    except Exception:
        log.debug("J1 lane graph memoria failed; continuing", exc_info=True)

    if not found:
        return []
    # rank 순 정렬 후 budget 컷
    ranked = sorted(found.items(), key=lambda x: x[1])
    return [{"id": mid, "rank": i} for i, (mid, _) in enumerate(ranked[:k], start=1)]


def _query_tokens(text: str) -> set:
    """쿼리/문자열에서 매치용 토큰 추출 (영어 단어 + 한글 2+자 블록).

    graph lane은 부분매치가 목적이므로 소문자 정규화된 토큰 집합을 반환.
    스네이크/케밥/점 결합 토큰은 분리도 함께 토큰화 (python_version -> python, version).
    """
    import re
    toks = set()
    for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_.-]{2,}", text or ""):
        t = t.lower().strip("._-")
        if len(t) >= 3 and t not in _STOPWORDS:
            toks.add(t)
            # 결합 토큰 분리: python_version -> python, version
            for part in re.split(r"[_.-]+", t):
                if 3 <= len(part) and part not in _STOPWORDS:
                    toks.add(part)
    # 한글: 연속 2자 이상 블록 (조사 분리 없이 명사성 매치용)
    for blk in re.findall(r"[\uac00-\ud7af]{2,}", text or ""):
        if len(blk) >= 2:
            toks.add(blk)
    return toks


def build_lane_pool(recall_raw: Callable[[str, int], List[dict]], query: str) -> List[dict]:
    """Union of FTS + vector + importance + graph lanes, reranked by RRF. Returns hydrated rows.

    ``recall_raw(query, k)`` is the lane supplier (``_fts_search_working`` or
    ``_wm_vec_search`` or ``_imp_search`` or ``_graph_lane_search``). Falls back
    to fewer lanes; never raises.
    """
    ranks: dict = {}
    full: dict = {}
    try:
        fts = recall_raw("fts", query, LANE_FTS_BUDGET)
        for i, r in enumerate(fts, start=1):
            ranks.setdefault(r["id"], {})["fts_rank"] = i
    except Exception:
        log.debug("J1 lane FTS failed; continuing", exc_info=True)
    try:
        vec = recall_raw("vec", query, LANE_VEC_BUDGET)
        for i, r in enumerate(vec, start=1):
            ranks.setdefault(r["id"], {})["vec_rank"] = i
    except Exception:
        log.debug("J1 lane vec failed; continuing", exc_info=True)
    try:
        imp = recall_raw("imp", query, LANE_IMP_BUDGET)
        for i, r in enumerate(imp, start=1):
            ranks.setdefault(r["id"], {})["imp_rank"] = i
    except Exception:
        log.debug("J1 lane importance failed; continuing", exc_info=True)
    try:
        graph = recall_raw("graph", query, LANE_GRAPH_BUDGET)
        for i, r in enumerate(graph, start=1):
            ranks.setdefault(r["id"], {})["graph_rank"] = i
    except Exception:
        log.debug("J1 lane graph failed; continuing", exc_info=True)
    if not ranks:
        return []
    for mid in ranks:
        row = recall_raw("get", mid, 0)  # hydration via backend
        if row:
            full[mid] = row
    ranked = _rrf_merge(list(full.values()), ranks)
    _jtrace("pool", {
        "query": (query or "")[:120],
        "fts": sum(1 for r in ranks.values() if "fts_rank" in r),
        "vec": sum(1 for r in ranks.values() if "vec_rank" in r),
        "imp": sum(1 for r in ranks.values() if "imp_rank" in r),
        "graph": sum(1 for r in ranks.values() if "graph_rank" in r),
        "pool": len(full),
    })
    out = []
    for row, _ in ranked:
        lane_ranks = ranks.get(row["id"], {})
        if lane_ranks:
            # Attach lane ranks so the gate can apply the vec-rank exemption
            # (semantic-signal pass for vec top hits with low lexical overlap).
            row = dict(row)
            row["_lane_ranks"] = lane_ranks
        out.append(row)
    return out


def _abstain_enabled() -> bool:
    """JEV_ABSTAIN env: '0'/'false'/'off' disables; default ON."""
    raw = (os.environ.get(ABSTAIN_ENV_KEY) or "").strip().lower()
    return raw not in ("0", "false", "off", "no", "disabled")


def _jev_choice(client, state: dict, labels: list, timeout: float) -> Optional[int]:
    """Single Jev choice call -> index into labels; None on any failure.

    With abstain enabled (JEV_ABSTAIN != '0'), an extra label ``c<N>`` is
    offered; a return value of ``len(labels)`` means Jev abstained (no
    candidate is usable evidence). None still means call failure -> pool.
    """
    abstain = _abstain_enabled()
    j_labels = list(labels)
    if abstain:
        j_labels.append(ABSTAIN_LABEL)
    instructions = (
        "Which candidate memory is the single best evidence for answering "
        "the question? Pick exactly one. Consider directness and specificity."
    )
    if abstain:
        instructions += ABSTAIN_INSTRUCTION
    questions = {
        "best": {
            "type": "choice",
            "instructions": instructions,
            "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))},
        }
    }
    try:
        import os as _os
        # URL 결정: client에 실측된 URL(_jev_api)이 있으면 우선, 없으면 env/기본
        _api = getattr(client, "_jev_api", None) or (
            _os.environ.get("JEV_API_URL") or "https://api.typesafe.ai/v1/systemone"
        )
        resp = client.post(
            _api,
            json={"state": state, "questions": questions, "model": "jev-latest"},
            timeout=timeout,
        )
        # 키 스위칭 (2026-10-04): 429 rate-limit 시 다른 키로 전환 후 1회 재시도
        if resp.status_code == 429:
            rot = getattr(client, "_jev_rotator", None)
            keys = getattr(client, "_jev_keys", None)
            if rot is not None and keys is not None and len(keys) > 1:
                nk = rot.on_429()
                if nk:
                    client.headers["Authorization"] = f"Bearer {nk}"
                    log.info("Jev choice 429 → 키 전환 (다른 계정) 재시도")
                    resp = client.post(
                        _api,
                        json={"state": state, "questions": questions, "model": "jev-latest"},
                        timeout=timeout,
                    )
        if resp.status_code != 200:
            log.info("Jev choice HTTP %s", resp.status_code)
            return None
        ans = (resp.json().get("answers") or {}).get("best") or {}
        choice = ans.get("choice")
        if choice is None:
            return None
        return int(str(choice).lstrip("c"))
    except Exception as exc:
        log.info("Jev choice failed: %s", type(exc).__name__)
        return None


def build_state(query: str, candidates: List[dict]) -> dict:
    headers = []
    for c in candidates:
        headers.append({
            "id": (c.get("id") or "")[:12],
            "type": c.get("memory_type") or "",
            "scope": c.get("scope") or "",
            "importance": float(c.get("importance") or 0.0),
            "source": c.get("source") or "",
            "excerpt": _excerpt(c.get("content") or "", EXCERPT_LIMIT),
        })
    return {"question": query, "candidates": headers}


def _excerpt(content: str, limit: int = 120) -> str:
    text = " ".join(content.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def jev_rerank(
    *,
    query: str,
    pool: List[dict],
    client: Optional[object] = None,
    call_jev: bool = True,
    labels: Optional[List[str]] = None,
    timeout: float = JEV_CHOICE_TIMEOUT_S,
) -> tuple[List[dict], bool]:
    """J1: lift Jev's pick to rank 1, keep pool order for the rest.

    ``pool`` is pre-filtered and ranked (pool order preserved). When Jev is
    disabled (``call_jev=False``) or fails, returns the pool unchanged with
    ``abstained=False``. When Jev picks the abstain label (Run O), returns the
    pool unchanged with ``abstained=True`` — nothing is lifted, and the caller
    can signal "no usable memory" downstream.
    """
    if not pool:
        return [], False
    if not call_jev or client is None:
        return pool, False
    state = build_state(query, pool)
    if labels is None:
        labels = [_excerpt((c.get("content") or ""), 100) or "n/a" for c in pool]
    t0 = time.perf_counter()
    idx = _jev_choice(client, state, labels, timeout=timeout)
    lat = (time.perf_counter() - t0) * 1000
    log.info("Jev choice: idx=%s latency=%.0fms pool=%d", idx, lat, len(pool))
    _jtrace("jev", {
        "query": (query or "")[:120],
        "idx": idx if idx is not None else "none",
        "lat_ms": f"{lat:.0f}",
        "pool": len(pool),
        "pick": (pool[idx].get("id", "")[:12] if idx is not None and 0 <= idx < len(pool) else "") if idx is not None else "",
    })
    if idx is None:
        return pool, False
    idx = int(idx)
    if (_abstain_enabled()
            and idx == len(labels)):
        # Run O abstain: Jev says no candidate is usable evidence.
        _jtrace("abstain", {"query": (query or "")[:120], "pool": len(pool)})
        return pool, True
    if not (0 <= idx < len(pool)):
        return pool, False
    lifted = pool[idx]["id"] != pool[0]["id"]
    _jtrace("lift", {
        "query": (query or "")[:120],
        "lifted": lifted,
        "from_idx": idx,
        "picked_id": str(pool[idx].get("id", ""))[:12],
        "prev_top": str(pool[0].get("id", ""))[:12],
    })
    return [pool[idx]] + [c for i, c in enumerate(pool) if i != idx], False


def jev_enabled() -> bool:
    """JEV_RERANK env: '0'/'false'/'off' disables; default ON."""
    raw = (os.environ.get(JEV_ENV_KEY) or "").strip().lower()
    if raw in ("0", "false", "off", "no", "disabled"):
        return False
    return True