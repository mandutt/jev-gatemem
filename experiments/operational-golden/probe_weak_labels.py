"""실측: fit 피드백 루프 — 자동 약한 라벨 (weak label) 후보 추출 (0 JEV 콜)

목적: fit/드리프트 감지에 쓸 '사람 개입 없는' 라벨 신호가 실재하는지,
      후보가 몇 건이나 존재하는지 실측.

신호:
  α: supersede — superseded_by가 있는 과거 저장 = '나중에 뒤집힌 저장' (약한 '틀렸음')
     단, 재판정/fail-open 마커(metadata gate=fail_open*, rejudged*)는 제외 (장애 산출물).
  β: 사용자 교정 발화 — trace write-gate 항목 중 utterance가 교정 신호 패턴으로 시작
     (아니|잠깐|정정|틀렸|수정해|고쳐|방금 건|그건 아니), 판정 KEEP = '저장해선 안 됐던 것'
     (약한 '틀렸음'); SKIP = 후속 교정이 저장 게이트를 통과했을 수 있음.

raw 저장: experiments/operational-golden/weak_label_probe.json (1차 산출물)
판정: α·β 후보가 0건이면 '자동 약한 라벨 부재' → fit은 사람 판정 시트에만 의존.
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
# 2026-10-07부터 일별 로테이션 (stage97) — 오늘 날짜 파일 + 옛 고정 경로 폴백
from datetime import date as _date
_TRACE_TODAY = os.path.expandvars(rf"%LOCALAPPDATA%/hermes/logs/jev_trace_{_date.today():%Y%m%d}.log")
TRACE = _TRACE_TODAY if os.path.exists(_TRACE_TODAY) else os.path.expandvars(r"%LOCALAPPDATA%/hermes/logs/jev_trace.log")
OUT = os.path.join(ROOT, "experiments", "operational-golden", "weak_label_probe.json")

CORRECTION_PATTERN = re.compile(
    r"^(아니[요]?[.,!~]?|잠깐[만]?[.,!~]?|정정|틀렸|수정해|고쳐[줘요]?|방금 건|그건 아니|잠시[만]?[.,!~]?)",
    re.IGNORECASE,
)

def load_trace(path):
    events = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)\|(write-gate|write-gate-as|gate)\|(.+)$", line)
        if not m:
            continue
        ts, kind, body = m.group(1), m.group(2), m.group(3)
        fields = {}
        for part in body.split():
            if "=" in part:
                k, _, v = part.partition("=")
                fields[k] = v
        events.append({"ts": ts, "kind": kind, "utterance": fields.get("utterance", ""),
                       "keep": fields.get("keep", ""), "reason": fields.get("reason", "")})
    return events

def alpha_candidates(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT id, content, session_id, timestamp, metadata_json, memory_type, "
        "       superseded_by, valid_until FROM working_memory "
        "WHERE superseded_by IS NOT NULL OR valid_until IS NOT NULL"
    ).fetchall()
    con.close()
    out = []
    for rid, content, sid, ts, meta, mtype, sup, vu in rows:
        try:
            md = json.loads(meta) if meta else {}
        except Exception:
            md = {}
        # 재판정/fail-open 마커 제외 (장애 산출물은 '틀렸음' 신호가 아님)
        gate = md.get("gate", "")
        rejudged = md.get("rejudged")
        if "fail_open" in str(gate) or rejudged:
            continue
        out.append({"id": rid, "content": (content or "")[:120], "session_id": sid,
                    "timestamp": ts, "memory_type": mtype, "superseded_by": sup,
                    "valid_until": vu, "meta": {k: md.get(k) for k in ("gate", "rejudged", "source_timestamp", "backfilled_at") if k in md}})
    return out

def beta_candidates(events):
    out = []
    for e in events:
        if not e["utterance"]:
            continue
        if CORRECTION_PATTERN.match(e["utterance"].strip()):
            out.append({"ts": e["ts"], "kind": e["kind"], "keep": e["keep"],
                        "reason": e["reason"], "utterance": e["utterance"][:120]})
    return out

def main():
    print("== 파트 1: α supersede (약한 '틀렸음') ==")
    db = os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db")
    alpha = alpha_candidates(db)
    print(f"superseded/valid_until 행: {len(alpha)} (재판정/fail-open 제외 후)")
    kinds = {}
    for a in alpha:
        kinds[a["memory_type"]] = kinds.get(a["memory_type"], 0) + 1
    print("type 분포:", kinds)
    # 샘플 5건
    for a in alpha[:5]:
        print(f"  [{a['memory_type']}] {a['content'][:70]}")

    print("\n== 파트 2: β 교정 발화 ==")
    events = load_trace(TRACE)
    print(f"trace 이벤트: {len(events)} (write-gate/write-gate-as/gate)")
    beta = beta_candidates(events)
    print(f"교정 패턴 발화: {len(beta)}")
    for b in beta[:10]:
        print(f"  [{b['kind']} keep={b['keep']} {b['ts'][:16]}] {b['utterance'][:60]}")

    out = {"generated_at": datetime.now().isoformat(timespec="seconds"),
           "trace_file": TRACE, "db": db,
           "alpha_count": len(alpha), "beta_count": len(beta),
           "alpha": alpha, "beta": beta}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nraw 저장: {OUT}")

if __name__ == "__main__":
    main()