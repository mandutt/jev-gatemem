"""라이브 J1 파이프라인 trace — jev-mem이 실제 prefetch에서 어떻게 개입하는지 단계별 실측.

- Hermes 런타임 venv python으로 실행 (mnemosyne 3.15.1 + mnemosyne_hermes + httpx)
- 현재 세션의 실제 prefetch와 동일한 경로(harnesses/hermes_j1._prefetch_with_j1의 recall_raw 시그니처)를 재현
- lane별 기여, gate 전후, Jev choice 입력(라벨), lift 결과를 stdout으로 출력
"""
import sys
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
sys.path.insert(0, str(REPO))

from mnemosyne.core import beam as beam_mod
from gateway import j1_pipeline as j1

# TYPESAFE_API_KEY: Hermes .env에서 읽기
env_path = Path(r"C:\Users\mandu\AppData\Local\hermes\.env")
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            if k.strip() == "TYPESAFE_API_KEY":
                import os
                os.environ.setdefault("TYPESAFE_API_KEY", v.strip().strip('"').strip("'"))

import os
import sqlite3

DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row


def recall_raw(kind: str, arg, k: int):
    """hermes_j1._prefetch_with_j1의 recall_raw와 동일 계약."""
    if kind == "fts":
        return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        emb = beam_mod._embeddings.embed([arg])
        if emb is None or not len(emb):
            return []
        return beam_mod._wm_vec_search(conn, emb[0], k=k)
    if kind == "imp":
        return j1._imp_search(conn, k=k)
    if kind == "graph":
        return j1._graph_lane_search(conn, arg, k=k)
    if kind == "get":
        for tbl in ("working_memory", "episodic_memory"):
            row = conn.execute(
                f"SELECT id, content, source, timestamp, session_id, importance,"
                f" metadata_json, veracity, created_at, memory_type, scope"
                f" FROM {tbl} WHERE id = ?",
                (arg,),
            ).fetchone()
            if row:
                d = dict(row)
                d["metadata"] = row["metadata_json"]
                d["memory_store"] = tbl
                return d
        return None
    return []


QUERY = sys.argv[1] if len(sys.argv) > 1 else (
    "jev-mem이 므네모슈네와 어떻게 연동되는지, 메모리 회상 파이프라인"
)

print(f"=== QUERY: {QUERY!r} ===\n")

# 1) lane별 기여
pool = j1.build_lane_pool(recall_raw, QUERY)
print(f"1. build_lane_pool -> {len(pool)} candidates (RRF 병합)")

# lane별 raw 카운트 (직접 조회)
for kind, fn in [
    ("fts", lambda: beam_mod._fts_search_working(conn, QUERY, k=j1.LANE_FTS_BUDGET)),
    ("vec", lambda: beam_mod._wm_vec_search(conn, beam_mod._embeddings.embed([QUERY])[0], k=j1.LANE_VEC_BUDGET)),
    ("imp", lambda: j1._imp_search(conn, k=j1.LANE_IMP_BUDGET)),
    ("graph", lambda: j1._graph_lane_search(conn, QUERY, k=j1.LANE_GRAPH_BUDGET)),
]:
    try:
        hits = fn()
        print(f"   lane {kind:5s}: raw {len(hits)} hits")
    except Exception as e:
        print(f"   lane {kind:5s}: ERROR {type(e).__name__}: {e}")

# 2) gate (보수적 필터)
filtered = j1._filter_and_rank(pool, QUERY)
print(f"\n2. _filter_and_rank (gate) -> {len(filtered)} / {len(pool)} 통과")

# 3) Jev에 보내는 입력 (top POOL_DEFAULT_TOP)
top = filtered[: j1.POOL_DEFAULT_TOP]
print(f"\n3. Jev choice 입력: {len(top)} candidates (labels 상위 5개만 표시)")
for i, c in enumerate(top[:5]):
    ex = " ".join((c.get("content") or "").split())[:90]
    print(f"   [{i}] id={c.get('id','')[:12]} type={c.get('memory_type')} imp={c.get('importance')} :: {ex}")

# 4) Jev 호출 (TYPESAFE_API_KEY 있으면)
key = os.environ.get("TYPESAFE_API_KEY", "")
print(f"\n4. TYPESAFE_API_KEY: {'설정됨(len=%d)' % len(key) if key else '없음 -> Jev 호출 스킵'}")
import httpx, time

ranked = []
if key:
    client = httpx.Client(
        timeout=httpx.Timeout(5.0, connect=5.0),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    ranked, _ = j1.jev_rerank(
        query=QUERY,
        pool=top,
        client=client,
        call_jev=True,
        timeout=j1.JEV_CHOICE_TIMEOUT_S,
    )
    print(f"   Jev 호출 후: {len(ranked)} candidates (lift 발생 시 순서 변경)")
    # lift 여부 판별
    if len(ranked) > 1 and ranked[0]["id"] != top[0]["id"]:
        print(f"   ★ LIFT: Jev가 idx={next(i for i,c in enumerate(top) if c['id']==ranked[0]['id'])} 후보를 top-1로 승격")
    else:
        print("   (top-1 유지: Jev choice가 이미 1순위를 선택하거나 pool order 보존)")
    client.close()
else:
    ranked = top
    print("   (Jev OFF -> pool order 그대로)")

# 5) 최종 top-5 (prefetch 주입분)
print(f"\n5. 최종 prefetch top-5:")
for i, c in enumerate(ranked[:5]):
    ex = " ".join((c.get("content") or "").split())[:100]
    print(f"   [{i}] {c.get('id','')[:12]} :: {ex}")

print("\nDONE")