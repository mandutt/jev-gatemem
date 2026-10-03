"""재판정 마커(metadata) 공용 헬퍼 — canonical 단일 포맷 (2026-10-03).

Canonical 포맷 (v0.2.0 이후 신규 기록부 표준):
    {
      "gate": "fail_open:http-402",   // 장애 원인 — 불변. 재판정이 절대 덮지 않음
      "rejudged": "keep" | "skip",    // 재판정 결과 — 단일 필드 (태그형 폐지)
      "rejudged_at": "ISO8601",        // 판정 시각
      "archived": true,                // skip 전용
      "archived_at": "..."             // 기존 값 유지 (있을 경우)
    }

불변식:
  1. "gate" 필드는 재판정/후행 tool이 절대 overwrite하지 않는다 (원인 보존).
  2. 모든 mutation 이후에 json.dumps — mutation 전 직렬화는 이후 키 누락
     (실측: 403_apply.py archived 2건 유실).
  3. metadata_json만 UPDATE하며 valid_until **컬럼**은 절대 건드리지 않는다
     (recall 필터는 컬럼을 본다 — 실수로 NULL/now로 덮으면 live recall 누출/유실).

소비 predicate 호환: canonical 행은 기존 태그형/JSON형 LIKE 전부와 매칭되므로
기존 소비처(server skip_staged 3중 LIKE 등)는 그대로 동작한다.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

# P1/tools 경로가 기록한 레거시 형식 (감사용 상수 — 신규 기록 금지)
LEGACY_TAG_PREFIX = "rejudged:"     # "gate": "rejudged:skip@jev-latest"


def now_iso() -> str:
    """canonical 타임스탬프 — 로컬 +09:00 명시 (오프셋 없는 값 금지)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_tagged_verdict(meta: Dict[str, Any]) -> bool:
    """gate가 레거시 태그형('rejudged:...')인가 (감사/마이그레이션용)."""
    g = str(meta.get("gate") or "")
    return g.startswith(LEGACY_TAG_PREFIX)


def extract_tag_verdict(meta: Dict[str, Any]) -> str:
    """레거시 태그형 gate에서 verdict 추출 ('rejudged:skip@jev-latest' -> 'skip')."""
    g = str(meta.get("gate") or "")
    if not g.startswith(LEGACY_TAG_PREFIX):
        return ""
    body = g[len(LEGACY_TAG_PREFIX):]
    return body.split("@")[0].strip()


def build_verdict_meta(meta: Dict[str, Any], verdict: str, *,
                       model: str = "jev-latest",
                       rejudged_at: str | None = None) -> Dict[str, Any]:
    """canonical 재판정 메타 구성 — gate 불변, 결과만 신규/갱신.

    - verdict: "keep" | "skip"
    - gate는 절대 변경하지 않는다 (원인 보존 불변식).
    - skip: archived=True 추가 (기존 archived_at 유지, 없으면 지금).
    - rejudged_at: 명시 시 그대로, 없으면 now_iso().
    """
    out = dict(meta)
    # 불변식 1 — gate 보존 (없으면 원인 미상으로 두되 덮지 않음)
    out["rejudged"] = verdict
    out["rejudged_at"] = rejudged_at or now_iso()
    if verdict == "skip":
        out["archived"] = True
        out.setdefault("archived_at", now_iso())
    # 반환 — 직렬화는 호출자가 mutation 완료 후 수행 (불변식 2)
    return out


def apply_rejudge_patch(conn, memory_id: str, verdict: str, *,
                        model: str = "jev-latest",
                        rejudged_at: str | None = None) -> bool:
    """canonical 반영 — 단일 트랜잭션, gate 불변, metadata_json만 UPDATE.

    Args:
        conn: mnemosyne.db 쓰기 연결 (row_factory 없어도 무방).
        memory_id: 대상 행 id.
        verdict: "keep" | "skip"
        model / rejudged_at: 기록용 (선택).

    Returns:
        True = 반영됨, False = 행 없음/파싱 불가 (변경 없음).

    주의:
        - valid_until 컬럼은 갱신하지 않는다 — skip이라도 이 함수는 메타만
          바꾼다. 컬럼 반영(recall 제외)은 호출자가 명시적으로 함께 처리할 것
          (P3 recover 경로는 같은 트랜잭션에서 valid_until=now 기록 — 단,
          이 함수 호출 후 별도 UPDATE로).
    """
    row = conn.execute(
        "SELECT metadata_json FROM working_memory WHERE id=?", (memory_id,)
    ).fetchone()
    if not row:
        return False
    try:
        meta = json.loads(row[0] or "{}")
    except Exception:
        return False
    meta = build_verdict_meta(meta, verdict, model=model, rejudged_at=rejudged_at)
    # mutation 완료 후 직렬화 (불변식 2) — 공백 표준: separators=(',', ': ')
    conn.execute(
        "UPDATE working_memory SET metadata_json=? WHERE id=?",
        (json.dumps(meta, ensure_ascii=False, separators=(",", ": ")), memory_id))
    return True


def is_canonical_skip(meta: Dict[str, Any]) -> bool:
    """canonical skip 판정 (rejudged == skip)."""
    return meta.get("rejudged") == "skip"


def is_rejudged(meta: Dict[str, Any]) -> bool:
    """어떤 형식이든 재판정 완료 여부 (canonical 필드 + 레거시 태그형)."""
    if meta.get("rejudged") in ("keep", "skip"):
        return True
    return is_tagged_verdict(meta)