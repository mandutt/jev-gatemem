"""assistant 발화 저장 게이트 — 최종 확정 버전 (G-AS).

결정: P8 원본 프롬프트(jev_classify.py 동일) + context 타입 필터.

실측 근거 (gold50, TypeSafe API jev-latest):
- P8 원본 G1: precision 0.725 / recall 0.935 / F1 0.817 (FP 11건)
- FP 11건 중 context 1건 → context 필터로 FP 10건, precision 0.744 (recall 보존)
- commitment 필터는 TP 6건을 잃어 recall 0.742로 폭락 → 채택 안 함 (결과물 보존 최우선)
- P8-AS 전용 프롬프트(v1/v2)는 recall 0.355~0.387로 폭락 → 폐기

게이트 규칙 (assistant 전용):
  store == STORE && type != context  →  저장 (KEEP)
  그 외                              →  SKIP

API: TypeSafe systemone (jev-latest) — 9router(localhost:20128) 아님!
     (로컬 라우터 사용 시 간헐적 400 "Invalid JSON or schema" 발생 실측)
"""
import json
import os
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
DATA = HERE / "data"

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

TYPES = [
    "fact", "preference", "decision", "commitment", "goal", "event",
    "instruction", "relationship", "context", "learning", "observation",
    "error", "artifact", "NO_STORE",
]

# P8 원본 프롬프트 (jev_classify.py에서 복사 — assistant도 동일 분류기 사용)
from jev_classify import STORE_INSTRUCTIONS, CLASSIFY_INSTRUCTIONS  # noqa: E402

GATE_NAME = "G-AS (P8 + context 필터): store==STORE && type!=context"


def jev_classify_p8(utterance: str, timeout: float = 60.0) -> dict:
    """P8 원본 분류 (TypeSafe API, jev-latest)."""
    state = {
        "utterance": utterance,
        "candidates": [{"id": f"t{i}", "label": t} for i, t in enumerate(TYPES)],
    }
    questions = {
        "store": {
            "type": "choice",
            "instructions": STORE_INSTRUCTIONS,
            "criteria": {"c0": "STORE", "c1": "NO_STORE"},
        },
        "classify": {
            "type": "choice",
            "instructions": CLASSIFY_INSTRUCTIONS,
            "criteria": {f"c{i}": t for i, t in enumerate(TYPES)},
        },
    }
    t0 = time.perf_counter()
    last_err = None
    payload = {"state": state, "questions": questions, "model": MODEL}
    for attempt in range(3):
        try:
            resp = httpx.post(
                API,
                headers={
                    "Authorization": f"Bearer {os.environ.get('TYPESAFE_API_KEY', '')}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            if resp.status_code == 200:
                break
            last_err = f"HTTP {resp.status_code}: {resp.text[:150]}"
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:150]}"
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"after 3 attempts: {last_err}")
    lat_ms = (time.perf_counter() - t0) * 1000
    data = resp.json()
    answers = data.get("answers") or {}

    def _pick(key: str):
        a = answers.get(key) or {}
        choice = a.get("choice")
        probs = a.get("probabilities") or {}
        if choice is None:
            return None, None, probs
        c = str(choice).lstrip("c")
        try:
            return int(c), probs.get(choice, probs.get(f"c{int(c)}")), probs
        except ValueError:
            return None, None, probs

    store_idx, store_prob, store_probs = _pick("store")
    type_idx, type_prob, type_probs = _pick("classify")

    return {
        "store": "STORE" if store_idx == 0 else ("NO_STORE" if store_idx == 1 else None),
        "store_confidence": store_prob,
        "store_probs": store_probs,
        "type": TYPES[type_idx] if type_idx is not None and 0 <= type_idx < len(TYPES) else None,
        "type_confidence": type_prob,
        "type_probs": type_probs,
        "latency_ms": round(lat_ms, 1),
    }


def gate_keep(r: dict) -> bool:
    """G-AS 게이트: store==STORE && type!=context."""
    return r["jev"].get("store") == "STORE" and r["jev"].get("type") != "context"


def main():
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("!! TYPESAFE_API_KEY 미설정")
        return 2

    rows = [json.loads(l) for l in open(DATA / "ab_assistant_gold50.jsonl", encoding="utf-8")]
    verdicts = json.load(open(DATA / "ab_assistant_gold50.json", encoding="utf-8"))["verdicts"]
    for i, r in enumerate(rows):
        r["gold"] = "STORE" if verdicts.get(str(i)) == "store" else "NO_STORE"

    # 기존 P8 분류 결과 재사용 (ab_assistant_classified.jsonl — TypeSafe로 이미 분류됨)
    classified = {}
    for r in [json.loads(l) for l in open(DATA / "ab_assistant_classified.jsonl", encoding="utf-8")]:
        classified[r["id"]] = r["jev"]
    missing = [r for r in rows if r["id"] not in classified]
    print(f"기존 분류 재사용: {len(rows)-len(missing)}/{len(rows)}건")

    if missing:
        print(f"누락 {len(missing)}건 — TypeSafe로 새 분류...")
        for r in missing:
            try:
                classified[r["id"]] = jev_classify_p8(r["utterance"])
                print(f"  {r['id']}: OK")
            except Exception as e:
                print(f"  {r['id']}: FAIL {str(e)[:60]}")
                classified[r["id"]] = {"store": None, "type": None}

    for r in rows:
        r["jev"] = classified[r["id"]]

    # 게이트 평가
    n = len(rows)
    gold_store = sum(1 for r in rows if r["gold"] == "STORE")

    kept = [r for r in rows if gate_keep(r)]
    tp = sum(1 for r in kept if r["gold"] == "STORE")
    fp = len(kept) - tp
    missed = [r for r in rows if r["gold"] == "STORE" and not gate_keep(r)]
    recall = tp / gold_store if gold_store else 0
    precision = tp / len(kept) if kept else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print(f"\n=== G-AS 최종 검증 (gold50) ===")
    print(f"gold: STORE={gold_store} NO_STORE={n-gold_store}")
    print(f"KEEP={len(kept)} ({len(kept)/n*100:.1f}%) | TP={tp} FP={fp}")
    print(f"precision={precision:.3f} recall={recall:.3f} F1={f1:.3f}")
    if missed:
        print(f"\nMISSED {len(missed)}건 (gold=STORE인데 SKIP):")
        for r in missed:
            print(f"  [{r['jev'].get('type')} conf={r['jev'].get('store_confidence',0):.2f}] {r['utterance'][:70]}")
    fpm = [r for r in rows if gate_keep(r) and r["gold"] == "NO_STORE"]
    if fpm:
        print(f"\nFP {len(fpm)}건 (과다저장):")
        for r in fpm:
            print(f"  [{r['jev'].get('type')} conf={r['jev'].get('store_confidence',0):.2f}] {r['utterance'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())