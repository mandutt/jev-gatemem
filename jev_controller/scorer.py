"""Jev scorer — TypeSafe System One via OpenRouter Decisions API (spec §19).

One API call per query: N score questions over the same state (candidate
headers). Fallback contract: any failure/timeout --> None (caller degrades to
Mnemosyne-only). Never raises on network trouble.

Reference: https://openrouter.ai/docs/guides/community/jev (2026-09-27)
POST /api/alpha/decisions  {model, state, questions}
questions: {id: {type: "score", instructions, criteria: [..]}}
answer: {id: {type: "score", score: 0..3 float, probabilities, confidence}}
"""
from __future__ import annotations

import json
import time
from typing import Optional

import httpx

_DEFAULT_MODEL = "typesafe/jev-1.13"
_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
_TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
_SCALE_3 = [
    "Irrelevant to the question (would not help answer it)",
    "Marginally related (background only, low value)",
    "Relevant (useful evidence for answering the question)",
    "Exactly what was asked for (direct answer to the question)",
]
_SCALE_5 = [
    "Irrelevant — completely unrelated to the question",
    "Barely related — a passing mention only, no useful information",
    "Somewhat related — background context, low value",
    "Relevant — useful evidence that helps answer the question",
    "Highly relevant — strong evidence, likely part of the answer",
    "Exactly what was asked for — directly answers the question",
]


class JevScorer:
    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL, endpoint: str = _ENDPOINT,
                 timeout: float = 15.0, batch_size: int = 25, mode: str = "auto",
                 scale: str = "3"):
        """mode: 'openrouter' (Decisions API), 'typesafe' (api.typesafe.ai/v1/systemone),
        or 'auto' (pick typesafe when api_key looks like a TypeSafe key or endpoint is
        the typesafe one; otherwise openrouter). scale: '3' or '5' (score rubric width)."""
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout
        self.batch_size = batch_size
        self.mode = mode
        self.scale = scale
        if mode == "auto":
            self.mode = "typesafe" if endpoint == _TYPESAFE_ENDPOINT else "openrouter"
        self._client = None

    # -- HTTP --------------------------------------------------------------
    def _client_sync(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- scoring -----------------------------------------------------------
    def score_candidates(self, query: str, candidates: list, *, dry_run: bool = False) -> Optional[dict]:
        """Score candidates for relevance to query. Returns {candidate_id: float 0..3}
        or None on any failure (caller falls back to Mnemosyne-only)."""
        if not candidates:
            return {}
        if dry_run:
            # no network: deterministic placeholder scores (for wiring tests)
            return {c.id: 0.0 for c in candidates}

        state = self._build_state(query, candidates)
        scale = _SCALE_5 if self.scale == "5" else _SCALE_3
        questions = {
            f"rel_{i}": {
                "type": "score",
                "instructions": (
                    "How relevant is this memory as evidence for answering the question? "
                    "Consider topic match, specificity, and whether it would change the answer. "
                    "Use the full scale — reserve the top score for memories that directly answer it."
                ),
                "criteria": scale,
            }
            for i in range(len(candidates))
        }
        try:
            if self.mode == "typesafe":
                payload = {"state": state, "questions": questions}
                if self.model:
                    payload["model"] = self.model
            else:
                payload = {"model": self.model, "state": state, "questions": questions}
            resp = self._client_sync().post(
                self.endpoint,
                json=payload,
            )
            if resp.status_code != 200:
                print(f"[JevScorer] HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
        except Exception as exc:  # network / timeout / parse
            print(f"[JevScorer] call failed: {type(exc).__name__}: {exc}")
            return None

        answers = data.get("answers") or {}
        scores = {}
        for i, cand in enumerate(candidates):
            ans = answers.get(f"rel_{i}") or {}
            if ans.get("type") != "score":
                scores[cand.id] = 0.0
            else:
                scores[cand.id] = float(ans.get("score") or 0.0)
        return scores

    @staticmethod
    def _build_state(query: str, candidates: list) -> dict:
        """State = question + candidate headers (spec §18: headers only, no full text)."""
        headers = []
        for c in candidates:
            headers.append({
                "id": c.id[:12],
                "type": c.memory_type or "",
                "scope": c.scope or "",
                "importance": c.importance,
                "source": c.source_agent or "",
                "excerpt": c.short_excerpt or "",
            })
        return {"question": query, "candidates": headers}