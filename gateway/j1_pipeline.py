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
import re
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
# 2026-10-05: POOL_BUDGET 40 → 60 (stage14/15 실측) — [ASSISTANT] 제외 해제 후
# gold 19 gate 8→12 (+4), op-90 회귀 0, noans 오주입 0. 단 80/100은 abstain
# 폭증으로 역효과 (stage15: cut 80+ NO-PICK 전멸) — 60이 실질 상한.
POOL_BUDGET = 60          # candidates fed to Jev choice
# JEV state excerpt cap (chars). Env override: JEV_EXCERPT_LIMIT. Default 120.
EXCERPT_LIMIT = int(os.environ.get("JEV_EXCERPT_LIMIT", "120"))
POOL_DEFAULT_TOP = 60     # pool-alone fallback returns this many
JEV_CHOICE_TIMEOUT_S = 5.0   # hard cap; MemoryManager also bounds external prefetch
JEV_ENV_KEY = "JEV_RERANK"
# Run O (2026-10-03): abstain label on the Jev choice question. Default ON;
ABSTAIN_ENV_KEY = "JEV_ABSTAIN"
# 2026-10-06 (stage26/27): soft abstain gate τ — choice가 abstain이 아니어도
# abstain 라벨 확률이 이 값보다 높으면 빈 컨텍스트로 (noans 오주입 방어).
_SOFT_ABSTAIN_TAU = float(os.environ.get("JEV_SOFT_ABSTAIN_TAU", "0.3"))
# 2026-10-06 (stage32): hybrid 모드(choice+noul 1요청)에서 noul 최대 후보 수.
# API 실측: noul 30(질문 31)까지 200, 40(41)부터 400 — MAX_QS 한도.
HYBRID_MAX_CANDIDATES = int(os.environ.get("JEV_HYBRID_MAX_CANDIDATES", "30"))
# 2026-10-06 (stage33): 2콜 구조 — noul top-N만 추려 재choice.
# 실측: op hit@3 79(+2), noans 12(-4) vs 1콜. 토큰: 2콜째 criteria 6개뿐이라 +20%.
NEXT_CALL_TOP_N = int(os.environ.get("JEV_NEXT_CALL_TOP_N", "5"))
# 2026-10-06 (stage33): 2콜째 noul top-N 게이트 — abstain if noul_top < τ.
# 실측: τ=0.3~0.5에서 op 79/78 유지, noans 12/9. τ=0.3 기본 (noans 방어 + op 유지).
_NOUL_TAU = float(os.environ.get("JEV_NOUL_TAU", "0.3"))
# 2026-10-06 (stage33): 2콜째 abstain_p 게이트 — abstain if 2nd choice abstain_p > τ.
# 실측: τ2=0.3에서 noans 14→12 (op 79 유지).
_NEXT_ABSTAIN_TAU = float(os.environ.get("JEV_NEXT_ABSTAIN_TAU", "0.3"))
# 2콜 모드 기본값 (2026-10-06): stage36 3회 반복에서 기각 (hit@3 75 vs 현행 77,
# noans FP 18 vs 16). 1콜 hybrid도 stage37에서 기각 (noans FP 20).
# 현행 pool60 choice-only + win-300 + soft gate 유지. env JEV_TWO_CALL=1로 실험 재현 가능.
TWO_CALL = os.environ.get("JEV_TWO_CALL", "0") != "0"
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
# 2026-10-05: [ASSISTANT] 제외 해제 (실측 9) — 게이트가 이미 어휘·커버리지로 무관
# assistant 행을 걸러내므로 제외는 이중 안전장치일 뿐이었고, op-90 회귀 0·noans 오주입 0
# 으로 확인됨. 해제로 장문 assistant 보고서(사용자가 나중에 찾는 답) 회수 gold 1/19→8/19.
_PREFETCH_EXCLUDED_PREFIXES = ()
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
                     min_distinctive: int = 1, min_coverage: float = 0.0) -> List[dict]:
    """Conservative prefetch gate (lexical + source quality), matching
    mnemosyne_hermes's automatic-injection thresholds. Rows keep relevance.

    (2026-10-06) 기본값 (2, 0.30) → (1, 0.0) 완화 반영: core/j1_engine.py는 이미
    완화값으로 호출 중이었으나 gateway/러너 경로는 기본값(2, 0.30)이라 짧은 라이브
    쿼리에서 pool 0~5로 줄어 abstain 폭증(stage48 실측: 93% abstain). 완화는
    vec-rank exemption과 별개로, 어휘 overlap 1개만 있어도 통과 + coverage 무제한."""
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


def _jev_choice(client, state: dict, labels: list, timeout: float):
    """Single Jev choice call -> (idx, abstain_p, probs); None idx on failure.

    With abstain enabled (JEV_ABSTAIN != '0'), an extra label ``c<N>`` is
    offered; a return value of ``len(labels)`` means Jev abstained (no
    candidate is usable evidence). None still means call failure -> pool.

    Returns (idx, abstain_p, probabilities):
      idx: int label index, or len(labels) for abstain, or None on failure
      abstain_p: float probability of the abstain label (0.0 if no probs)
      probabilities: raw dict of cN -> p (may be empty)
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
            return None, 0.0, {}
        ans = (resp.json().get("answers") or {}).get("best") or {}
        choice = ans.get("choice")
        probs = ans.get("probabilities") or {}
        # abstain 확률: 마지막 라벨의 probability (없으면 confidence fallback)
        abstain_p = 0.0
        if probs:
            abstain_p = float(probs.get(f"c{len(j_labels) - 1}", 0.0) or 0.0)
        elif ans.get("confidence") is not None and abstain:
            abstain_p = float(ans["confidence"])
        if choice is None:
            return None, abstain_p, probs
        return int(str(choice).lstrip("c")), abstain_p, probs
    except Exception as exc:
        log.info("Jev choice failed: %s", type(exc).__name__)
        return None, 0.0, {}


def _jev_hybrid(client, state: dict, labels: list, timeout: float):
    """Jev hybrid call: choice(1) + noul(N) in one request — stage32.

    Returns (idx, abstain_p, noul_scores, err):
      idx: int label index of choice winner, or len(labels) abstain, or None
      abstain_p: probability of the abstain label
      noul_scores: list of N floats, one per candidate (absolute answerability)
      err: None or short error string ('http-400', 'no-choice', ...)
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
    questions: dict = {
        "best": {
            "type": "choice",
            "instructions": instructions,
            "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))},
        }
    }
    # noul 평가 질문 (absolute answerability) — 후보별 1개
    for i, lab in enumerate(labels):
        questions[f"n{i}"] = {
            "type": "noul",
            "instructions": {
                "question": (
                    "Does this candidate memory directly state or entail the "
                    "answer to the question? Output a 0-1 score."
                ),
                "candidate": lab,
            },
        }
    try:
        import os as _os
        _api = getattr(client, "_jev_api", None) or (
            _os.environ.get("JEV_API_URL") or "https://api.typesafe.ai/v1/systemone"
        )
        resp = client.post(
            _api,
            json={"state": state, "questions": questions, "model": "jev-latest"},
            timeout=timeout,
        )
        if resp.status_code == 429:
            rot = getattr(client, "_jev_rotator", None)
            keys = getattr(client, "_jev_keys", None)
            if rot is not None and keys is not None and len(keys) > 1:
                nk = rot.on_429()
                if nk:
                    client.headers["Authorization"] = f"Bearer {nk}"
                    resp = client.post(
                        _api,
                        json={"state": state, "questions": questions, "model": "jev-latest"},
                        timeout=timeout,
                    )
        if resp.status_code != 200:
            return None, 0.0, [], f"http-{resp.status_code}"
        ans = (resp.json().get("answers") or {})
        best = ans.get("best") or {}
        choice = best.get("choice")
        probs = best.get("probabilities") or {}
        abstain_p = 0.0
        if probs:
            abstain_p = float(probs.get(f"c{len(j_labels) - 1}", 0.0) or 0.0)
        elif best.get("confidence") is not None and abstain:
            abstain_p = float(best["confidence"])
        noul = []
        for i in range(len(labels)):
            v = (ans.get(f"n{i}") or {}).get("noul", 0.0)
            noul.append(float(v) if v is not None else 0.0)
        if choice is None:
            return None, abstain_p, noul, "no-choice"
        return int(str(choice).lstrip("c")), abstain_p, noul, None
    except Exception as exc:
        log.info("Jev hybrid failed: %s", type(exc).__name__)
        return None, 0.0, [], type(exc).__name__


def build_state(query: str, candidates: List[dict]) -> dict:
    headers = []
    for c in candidates:
        headers.append({
            "id": (c.get("id") or "")[:12],
            "type": c.get("memory_type") or "",
            "scope": c.get("scope") or "",
            "importance": float(c.get("importance") or 0.0),
            "source": c.get("source") or "",
            # 2026-10-06: state excerpt도 쿼리 윈도우 300자 (라벨과 일치).
            "excerpt": _excerpt(_query_window(c.get("content") or "", query, 300), 150),
        })
    return {"question": query, "candidates": headers}


def _excerpt(content: str, limit: int = 120) -> str:
    text = " ".join(content.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _query_window(content: str, query: str, win: int = 300) -> str:
    """쿼리 인지 윈도우: 본문에서 쿼리와 어휘 겹침이 최대인 win자 구간을 반환.

    stage17/18 (2026-10-05): 장문 라벨용. 50자 스텝 슬라이딩 + 토큰 겹침 스코어.
    메타 프리픽스([ASSISTANT] 등)는 스킵. 로컬 계산(쿼리당 수십 ms)이라 무시 가능.
    """
    m = re.match(r"^(\[[^\]]*\]\s*)?", content or "")
    c = (content or "")[m.end():] if m else (content or "")
    qt = _tokenize(query) - _STOPWORDS
    if not qt or len(c) <= win:
        return c[:win]
    best_start, best_score = 0, -1
    step = 50
    for start in range(0, len(c) - win + 1, step):
        seg = c[start:start + win]
        seg_toks = _tokenize(seg)
        score = len(qt & seg_toks)
        if score > best_score:
            best_score, best_start = score, start
    return c[best_start:best_start + win]


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
        # 2026-10-06 (stage26/27): 전 후보 쿼리 윈도우 300자로 전면 확장.
        # 실측: op hit@3 72→77(+5), hit@5 74→80, abstain 9→3. 단 noans 오주입
        # 13→22 증가 → abstain_p>0.3 soft gate(빈 컨텍스트)로 상쇄 (hard 16, easy 0 FP).
        labels = [
            _excerpt(_query_window((c.get("content") or ""), query, 300), 150)
            or "n/a"
            for c in pool
        ]
    t0 = time.perf_counter()
    if TWO_CALL and len(pool) > HYBRID_MAX_CANDIDATES:
        # 2콜 구조 (2026-10-06, stage32/33):
        #  1콜: choice + noul 30 (절대 answerability) — API 한도(31질문) 최대치
        #  2콜: noul top-5만 추려 재choice (소량 토큰 — 정밀 재판)
        # 실측: op hit@3 79(+2 over 1콜), noans 12(-4), abstain 8.
        top_n = HYBRID_MAX_CANDIDATES
        pool_1 = pool[:top_n]
        state_1 = build_state(query, pool_1)
        labels_1 = [
            _excerpt(_query_window((c.get("content") or ""), query, 300), 150)
            or "n/a"
            for c in pool_1
        ]
        idx1, abstain_p1, noul, err1 = _jev_hybrid(client, state_1, labels_1, timeout=timeout)
        _jtrace("jev-hybrid", {
            "query": (query or "")[:120],
            "idx": idx1 if idx1 is not None else "none",
            "abstain_p": f"{abstain_p1:.2f}",
            "err": err1 or "",
        })
        if err1:
            # hybrid 실패 → 1콜 choice 폴백 (기존 구조)
            log.info("hybrid failed (%s) → choice fallback", err1)
            idx, abstain_p, probs = _jev_choice(client, state, labels, timeout=timeout)
            lat = (time.perf_counter() - t0) * 1000
            log.info("Jev choice(fallback): idx=%s abstain_p=%.2f latency=%.0fms pool=%d",
                     idx, abstain_p, lat, len(pool))
            if idx is None:
                return pool, False
            idx = int(idx)
            if _abstain_enabled() and idx == len(labels):
                _jtrace("abstain", {"query": (query or "")[:120], "pool": len(pool)})
                return pool, True
            if _abstain_enabled() and abstain_p > _SOFT_ABSTAIN_TAU:
                _jtrace("soft-abstain", {"query": (query or "")[:120], "pool": len(pool),
                                         "abstain_p": f"{abstain_p:.2f}"})
                return pool, True
            if not (0 <= idx < len(pool)):
                return pool, False
            return [pool[idx]] + [c for i, c in enumerate(pool) if i != idx], False
        if idx1 == len(labels_1) or abstain_p1 > _SOFT_ABSTAIN_TAU:
            # 1콜째 abstain (명시 또는 soft) → abstain (빈 컨텍스트)
            _jtrace("abstain", {"query": (query or "")[:120], "pool": len(pool)})
            return pool, True
        if idx1 is not None and 0 <= idx1 < len(pool_1):
            _jtrace("lift", {
                "query": (query or "")[:120], "lifted": True, "from_idx": idx1,
                "picked_id": str(pool_1[idx1].get("id", ""))[:12],
                "prev_top": str(pool[0].get("id", ""))[:12],
            })
        # 2콜째: noul top-N 재choice (소량 토큰)
        noul_order = sorted(range(len(noul)), key=lambda i: noul[i], reverse=True)
        top_idx = noul_order[:NEXT_CALL_TOP_N]
        top_labels = [labels_1[i] for i in top_idx]
        top_cands = [pool_1[i] for i in top_idx]
        state_2 = build_state(query, top_cands)
        idx2, abstain_p2, _probs2 = _jev_choice(client, state_2, top_labels, timeout=timeout)
        err2 = None
        _jtrace("jev-2nd", {
            "query": (query or "")[:120],
            "idx": idx2 if idx2 is not None else "none",
            "abstain_p": f"{abstain_p2:.2f}",
            "err": err2 or "",
        })
        if err2 or idx2 is None:
            # 2콜째 실패 → 1콜째 결과 사용
            if idx1 is not None and 0 <= idx1 < len(pool_1):
                return [pool_1[idx1]] + [c for i, c in enumerate(pool_1) if i != idx1], False
            return pool, False
        idx2 = int(idx2)
        # 2콜째 게이트: 명시 abstain 또는 noul/abstain_p 게이트
        if idx2 == len(top_labels):
            _jtrace("abstain", {"query": (query or "")[:120], "pool": len(pool)})
            return pool, True
        noul_top = max(noul) if noul else 0.0
        if noul_top < _NOUL_TAU or abstain_p2 > _NEXT_ABSTAIN_TAU:
            _jtrace("soft-abstain-2nd", {
                "query": (query or "")[:120], "pool": len(pool),
                "noul_top": f"{noul_top:.2f}", "abstain_p": f"{abstain_p2:.2f}"})
            return pool, True
        if 0 <= idx2 < len(top_cands):
            picked = top_cands[idx2]
            # 2콜째 선택을 전체 pool에 반영 (rank 1로 lift)
            return [picked] + [c for c in pool if c.get("id") != picked.get("id")], False
        return pool, False
    if os.environ.get("JEV_HYBRID_ENABLED", "0") != "0" and len(pool) <= HYBRID_MAX_CANDIDATES:
        # 1콜 hybrid (2026-10-06, stage32/37): choice + noul N 병렬 (N ≤ 30).
        # 3회 반복 실측에서 현행 pool60 choice-only 대비 열위 확정(hit@3 77 동일,
        # noans FP 20 vs 16) → 기본 비활성. env JEV_HYBRID_ENABLED=1로 재현 가능.
        # (2026-10-06 외부 AI 검토: 기각 구조가 운영에 남아 있던 잔재 — 가드 추가)
        idx, abstain_p, noul, err = _jev_hybrid(client, state, labels, timeout=timeout)
        lat = (time.perf_counter() - t0) * 1000
        log.info("Jev hybrid: idx=%s abstain_p=%.2f latency=%.0fms pool=%d",
                 idx, abstain_p, lat, len(pool))
        _jtrace("jev-hybrid", {
            "query": (query or "")[:120],
            "idx": idx if idx is not None else "none",
            "abstain_p": f"{abstain_p:.2f}",
            "lat_ms": f"{lat:.0f}",
            "pool": len(pool),
            "err": err or "",
        })
        if err or idx is None:
            return pool, False
        idx = int(idx)
        if _abstain_enabled() and idx == len(labels):
            _jtrace("abstain", {"query": (query or "")[:120], "pool": len(pool)})
            return pool, True
        if _abstain_enabled() and abstain_p > _SOFT_ABSTAIN_TAU:
            _jtrace("soft-abstain", {"query": (query or "")[:120], "pool": len(pool),
                                     "abstain_p": f"{abstain_p:.2f}"})
            return pool, True
        # noul 게이트 (2026-10-06, stage32 τ 스윕): 관련 후보가 없으면 abstain.
        if noul:
            noul_top = max(noul)
            if noul_top < _NOUL_TAU:
                _jtrace("soft-abstain-noul", {"query": (query or "")[:120],
                                              "pool": len(pool),
                                              "noul_top": f"{noul_top:.2f}"})
                return pool, True
        if not (0 <= idx < len(pool)):
            return pool, False
        return [pool[idx]] + [c for i, c in enumerate(pool) if i != idx], False
    idx, abstain_p, probs = _jev_choice(client, state, labels, timeout=timeout)
    lat = (time.perf_counter() - t0) * 1000
    log.info("Jev choice: idx=%s abstain_p=%.2f latency=%.0fms pool=%d",
             idx, abstain_p, lat, len(pool))
    _jtrace("jev", {
        "query": (query or "")[:120],
        "idx": idx if idx is not None else "none",
        "lat_ms": f"{lat:.0f}",
        "pool": len(pool),
        "abstain_p": f"{abstain_p:.2f}",
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
    # 2026-10-06 (stage26/27): soft abstain gate — choice가 abstain이 아니어도
    # abstain 라벨 확률이 높으면(τ=0.3) 빈 컨텍스트로. 실측: noans hard 22→16 FP,
    # easy 0 FP, op 손실 0.
    if _abstain_enabled() and abstain_p > _SOFT_ABSTAIN_TAU:
        _jtrace("soft-abstain", {"query": (query or "")[:120], "pool": len(pool),
                                 "abstain_p": f"{abstain_p:.2f}"})
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