"""실측: audit stale Tier 2 — 의미적 모순 스윕 파일럿 (소량 JEV)

목적: '최근 저장 메모리가 과거 메모리를 대체/폐기했는가'를 JEV 1콜/메모리로 판정하는
      stale 감사 경로의 실현 가능성 실측.

설계:
  - 대상: working_memory에서 최근 2일 이내 저장된 행 (2026-10-04~05)
  - 대조 컨텍스트: 대상 행과 동일 session_id? → 아니오, 전 세션 대상이므로
    같은 content 어휘를 공유하는 다른 행 3건 (간단 어휘 유사도 기준)을 '후보 대체자'
  - 질문 (choice): 후보 대체자 중 이 메모리를 뒤집거나 대체하는 게 있는가?
  - 판정: YES → stale 후보 / NO → live
  - 금지: 삭제·변경 없음 (플래그만)

비용: 표본 N건 × 1콜 (최대 40콜, free 레인)
raw 저장: experiments/operational-golden/audit_tier2_probe.json
"""
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "experiments", "operational-golden", "audit_tier2_probe.json")

try:
    import httpx
except ImportError:
    httpx = None

API_URL = os.environ.get("JEV_API_URL", "https://api.experientiallabs.ai/v1/systemone")
API_KEY = os.environ.get("EXPLABS_API_KEY") or os.environ.get("TYPESAFE_API_KEY")

def post_systemone(utterance: str, candidates: list, timeout: float = 15.0):
    if httpx is None:
        raise RuntimeError("httpx 없음")
    # Jev systemone 프로토콜: {model, state, questions}만 허용.
    # candidates는 {"id": "t<i>", "label": <텍스트>} 형태.
    cands = [{"id": f"t{i}", "label": (c or "")[:800]} for i, c in enumerate(candidates)]
    body = {
        "model": "jev-latest",
        "state": {"utterance": utterance[:120], "candidates": cands},
        "questions": {
            "stale": {
                "type": "choice",
                "instructions": (
                    "The memory is the current query. A newer memory may replace or contradict it. "
                    "Decide whether any candidate is a newer memory that supersedes this one."
                ),
                "criteria": {
                    "c0": "Live — no candidate replaces or contradicts this memory",
                    "c1": "Stale — a candidate replaces or contradicts this memory",
                },
            }
        },
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}
    r = httpx.post(API_URL, json=body, headers=headers, timeout=timeout)
    return r

def main():
    if not API_KEY:
        print("API key 없음 — 중단")
        return 1

    db = os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT id, content, session_id, timestamp, memory_type FROM working_memory "
        "ORDER BY timestamp DESC"
    ).fetchall()
    con.close()

    # 최근 2일 행 (후보 대체자 포함을 위해 전체 로드)
    cutoff = (datetime.now().timestamp() - 2 * 86400)
    recent = [r for r in rows if _parse_ts(r[3]) > cutoff]
    print(f"전체 {len(rows)} / 최근 2일 {len(recent)}")

    if not recent:
        print("최근 2일 행 없음")
        return 0

    # 표본: 최근 행 중 상위 40건 (content 120자 절단, 대체자 3건씩)
    sample = recent[:40]
    print(f"표본 {len(sample)}건 — 콜 {len(sample)} (free 레인)")

    def _sim(a, b):
        sa, sb = set(re.findall(r"\w+", (a or "").lower())), set(re.findall(r"\w+", (b or "").lower()))
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / min(len(sa), len(sb))

    records = []
    for rid, content, sid, ts, mtype in sample:
        # 후보 대체자: 같은 어휘 공유하는 다른 행 (자기 자신 제외)
        others = [r for r in rows if r[0] != rid]
        scored = sorted(others, key=lambda r: _sim(content, r[1]), reverse=True)[:3]
        cands = [(r[0], (r[1] or "")[:120]) for r in scored if _sim(content, r[1]) > 0.1]
        if not cands:
            records.append({"id": rid, "verdict": "SKIP_NO_CANDIDATES", "reason": "유사 후보 없음"})
            continue
        utt = (content or "")[:120]
        try:
            r = post_systemone(utt, [c[1] for c in cands])
            body = r.json() if r.status_code == 200 else {"error": r.text[:200]}
            if r.status_code == 200:
                ans = (body.get("answers") or {}).get("stale") or {}
                choice = ans.get("choice")
                verdict = "STALE" if choice == "c1" else "LIVE"
                prob = ans.get("probabilities") or {}
                rec = {"id": rid, "utterance": utt, "candidate_ids": [c[0] for c in cands],
                       "verdict": verdict, "choice": choice, "prob_stale": prob.get("c1"),
                       "latency_ms": r.elapsed.total_seconds() * 1000}
            else:
                rec = {"id": rid, "verdict": "ERROR", "status": r.status_code, "error": body}
        except Exception as e:
            rec = {"id": rid, "verdict": "ERROR", "error": str(e)[:200]}
        records.append(rec)
        if (len(records) % 10) == 0:
            print(f"  진행 {len(records)}/{len(sample)}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"),
                   "api": API_URL, "records": records}, f, ensure_ascii=False, indent=1)
    print(f"\n완료 — {OUT}")
    from collections import Counter
    print("verdict 분포:", Counter(r.get("verdict") for r in records))
    return 0

def _parse_ts(s):
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        try:
            return float(s)
        except Exception:
            return 0.0

if __name__ == "__main__":
    sys.exit(main())