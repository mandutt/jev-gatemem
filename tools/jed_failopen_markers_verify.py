"""canonical 마커 헬퍼 유닛 검증 — gate 불변·컬럼 불변·직렬화 순서 회귀.

실행: %LOCALAPPDATA%/jev-mem/venv/Scripts/python.exe tools/jed_failopen_markers_verify.py
기대: 8/8 PASS (실 DB 무접촉 — in-memory SQLite)
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("TYPESAFE_API_KEY", "test-key-not-used")

from jev_mem_core.rejudge_markers import (  # noqa: E402
    apply_rejudge_patch, build_verdict_meta, extract_tag_verdict,
    is_canonical_skip, is_rejudged, is_tagged_verdict, now_iso,
)

PASS = 0
FAIL = 0

def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name} {extra}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")

def fresh_conn():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE working_memory (
        id TEXT PRIMARY KEY, metadata_json TEXT, valid_until TEXT)""")
    c.execute("INSERT INTO working_memory (id, metadata_json, valid_until) VALUES (?,?,?)",
              ("m1", json.dumps({"gate": "fail_open:http-402", "incident_id": "inc-x"}),
               None))
    return c

print("=== 1) build_verdict_meta — gate 불변, skip 부가키 ===")
meta = build_verdict_meta({"gate": "fail_open:http-403"}, "keep")
check("keep: gate 유지", meta["gate"] == "fail_open:http-403", meta["gate"])
check("keep: rejudged=keep", meta["rejudged"] == "keep")
check("keep: archived 없음", "archived" not in meta)
ms = build_verdict_meta({"gate": "fail_open:http-402", "archived_at": "OLD"}, "skip")
check("skip: gate 유지", ms["gate"] == "fail_open:http-402")
check("skip: archived=True", ms["archived"] is True)
check("skip: 기존 archived_at 유지", ms.get("archived_at") == "OLD")
check("skip: rejudged_at은 ISO+오프셋", "+" in ms["rejudged_at"] or ms["rejudged_at"].endswith("Z"))

print("=== 2) apply_rejudge_patch — 컬럼 불변 + 직렬화 후 검증 ===")
c = fresh_conn()
ok = apply_rejudge_patch(c, "m1", "keep", model="jev-latest")
check("keep: patch 성공", ok)
row = c.execute("SELECT metadata_json, valid_until FROM working_memory WHERE id='m1'").fetchone()
check("keep: valid_until 컬럼 불변(NULL)", row[1] is None)
d = json.loads(row[0])
check("keep: canonical 반영", d["rejudged"] == "keep" and d["gate"] == "fail_open:http-402")
check("keep: 태그형 gate 없음", not d["gate"].startswith("rejudged:"))
ok = apply_rejudge_patch(c, "m1", "skip", model="jev-latest")
row = c.execute("SELECT metadata_json, valid_until FROM working_memory WHERE id='m1'").fetchone()
check("skip patch 후에도 컬럼 불변(함수 자체는 컬럼 안 건드림)", row[1] is None)
d = json.loads(row[0])
check("skip: archived=True", d["archived"] is True)
check("skip: gate 여전히 원본", d["gate"] == "fail_open:http-402")

print("=== 3) gate 표준 직렬화 매칭 (server skip_staged predicate) ===")
raw = json.dumps(d, ensure_ascii=False, separators=(",", ": "))
check("skip_staged predicate 매칭", '"rejudged": "skip"' in raw)

print("=== 4) 레거시 태그 헬퍼 ===")
check("is_tagged_verdict True", is_tagged_verdict({"gate": "rejudged:skip@jev-latest"}))
check("is_tagged_verdict False", not is_tagged_verdict({"gate": "fail_open:http-402"}))
check("extract_tag_verdict", extract_tag_verdict({"gate": "rejudged:skip@jev-latest"}) == "skip")
check("is_canonical_skip", is_canonical_skip({"rejudged": "skip"}))
check("is_rejudged canonical", is_rejudged({"rejudged": "keep"}))
check("is_rejudged tag", is_rejudged({"gate": "rejudged:keep"}))
check("is_rejudged none", not is_rejudged({"gate": "fail_open:http-402"}))

print()
print(f"=== 결과: {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)