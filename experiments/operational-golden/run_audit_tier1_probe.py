"""실측: audit stale Tier 1 — 환경/설정/포트/경로 메모리의 결정적 stale 검증 (0 JEV 콜)

목적: 저장 메모리에서 '라이브 상태로 기계 검증 가능한' 행들을 추출하여,
      실제 환경과 어긋난(stale) 행이 몇 건인지 실측.

검증 대상 (결정적):
  - env:   content에서 ENV_VAR=... 패턴 추출 → os.environ/레지스트리(EXPLABS/TYPESAFE) 존재 대조
  - port:  content에서 ':47821' 등 포트 → netstat 리슨 여부 (데몬 포트)
  - url:   api.typesafe.ai / api.experientiallabs.ai 언급 → 현재 사용 게이트웨이와 대조
  - model: bench/bekko-embedding-v1-a8m / MiniLM 언급 → 활성 임베딩 모델과 대조
  - db:    mnemosyne.db 경로 언급 → 실 DB 존재 대조

판정:
  - VERIFIED   = 라이브 상태와 일치
  - STALE      = 라이브 상태와 불일치 (예: typesafe URL 언급인데 현재 experientiallabs 사용)
  - UNCHECKABLE = 결정적 검증 불가 (사람 판정 필요 여부 표시)
raw 저장: experiments/operational-golden/audit_tier1_probe.json
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT = os.path.join(ROOT, "experiments", "operational-golden", "audit_tier1_probe.json")

# 라이브 상태 스냅샷
LIVE = {
    "gw_used": "experientiallabs" if os.environ.get("EXPLABS_API_KEY") else "typesafe",
    "explabs_key": bool(os.environ.get("EXPLABS_API_KEY")),
    "explabs_key2": bool(os.environ.get("EXPLABS_API_KEY2")),
    "typesafe_key": bool(os.environ.get("TYPESAFE_API_KEY")),
    "embed_model": "bench/bekko-embedding-v1-a8m",  # config.yaml 기준
    "data_dir": os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db"),
}

def port_listening(port):
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=20,
                           encoding="mbcs", errors="replace")
        return any(re.search(rf"\b{port}\b.*LISTENING", ln) for ln in r.stdout.splitlines())
    except Exception:
        return None

def classify(content):
    c = content.lower()
    checks = []
    # env 변수 언급
    for var in ("EXPLABS_API_KEY", "EXPLABS_API_KEY2", "TYPESAFE_API_KEY", "JEV_API_URL", "MNEMOSYNE_EMBEDDING_MODEL"):
        if re.search(rf"\b{var}\b", c):
            present = bool(os.environ.get(var))
            checks.append(("env", var, present))
    # 게이트웨이 URL
    if "api.typesafe.ai" in c:
        checks.append(("url", "typesafe", LIVE["gw_used"] == "typesafe"))
    if "api.experientiallabs.ai" in c or "experientiallabs" in c:
        checks.append(("url", "experientiallabs", LIVE["gw_used"] == "experientiallabs"))
    # 임베딩 모델
    if "bekko" in c:
        checks.append(("model", "bekko-a8m", "bekko" in LIVE["embed_model"]))
    if "minilm" in c:
        checks.append(("model", "MiniLM", "minilm" in LIVE["embed_model"]))
    # 포트 (4~5자리)
    for m in re.finditer(r"\b(4\d{4})\b", c):
        checks.append(("port", m.group(1), port_listening(m.group(1))))
    # DB 경로
    if "mnemosyne.db" in c:
        checks.append(("db", "mnemosyne.db", os.path.exists(LIVE["data_dir"])))
    return checks

def main():
    db = os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT id, content, session_id, timestamp, memory_type FROM working_memory ORDER BY timestamp DESC"
    ).fetchall()
    con.close()
    print(f"working_memory: {len(rows)} 행")

    results = []
    stats = {"VERIFIED": 0, "STALE": 0, "UNCHECKABLE": 0}
    stale_rows = []
    for rid, content, sid, ts, mtype in rows:
        chk = classify(content or "")
        if not chk:
            stats["UNCHECKABLE"] += 1
            continue
        verdict = "VERIFIED"
        for kind, name, ok in chk:
            if not ok:
                verdict = "STALE"
        results.append({"id": rid, "content": (content or "")[:100], "kind": mtype,
                        "checks": chk, "verdict": verdict})
        stats[verdict] += 1
        if verdict == "STALE":
            stale_rows.append((rid, mtype, chk, (content or "")[:100]))

    print(f"\n검증 가능 행: {len(results)} / {len(rows)}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\nSTALE 상세 ({len(stale_rows)}건):")
    for rid, mtype, chk, snippet in stale_rows[:20]:
        bad = [(k, n) for k, n, ok in chk if not ok]
        print(f"  [{mtype}] id={rid} {bad} :: {snippet[:70]}")

    out = {"generated_at": datetime.now().isoformat(timespec="seconds"),
           "live": LIVE, "total_rows": len(rows), "results": results, "stats": stats}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nraw 저장: {OUT}")

if __name__ == "__main__":
    main()