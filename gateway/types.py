"""Shared dataclasses for the Memory Gateway (spec §7, §18)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MemoryCandidate:
    """Candidate header DTO — derived from Mnemosyne recall, NOT a DB schema change."""

    id: str
    created_at: str = ""
    memory_type: str = ""
    scope: str = ""
    importance: float = 0.0
    source_agent: str = ""          # metadata_json.source_agent, fallback: source column
    mnemosyne_rank: int = 0
    similarity_score: float = 0.0
    short_excerpt: str = ""         # ~120 chars, type-aware truncation
    # filled by JevScorer when available
    jev_score: Optional[float] = None
    jev_rank: Optional[int] = None


@dataclass
class MemoryRecord:
    """Full hydrated memory (Stage 2)."""

    id: str
    content: str
    created_at: str = ""
    memory_type: str = ""
    scope: str = ""
    importance: float = 0.0
    source: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class RecallHit:
    """Raw hit from the Mnemosyne backend recall."""

    id: str
    content: str
    score: float
    rank: int
    created_at: str = ""
    memory_type: str = ""
    scope: str = ""
    importance: float = 0.0
    source: str = ""
    metadata: dict = field(default_factory=dict)