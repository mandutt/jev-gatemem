"""graph/fact lane 실데이터 검증 (read-only, 2026-10-05)

목적: 라이브 DB에 쌓인 실제 facts(30)/graph_edges(32)/memoria_facts(1011)가
_graph_lane_search를 통해 gold 회수(reference)되는지 확인.
- read-only: 라이브 DB를 쓰지 않음 (SELECT만).
- 합성 시드 대신 실제 데이터로: 각 fact/graph edge에서 추출한 쿼리로 회수 확인.
"""
import json, sqlite3, sys, os
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
from mnemosyne.core.beam import BeamMemory
from gateway.j1_pipeline import _graph_lane_search

LIVE_DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"

b = BeamMemory(session_id="eval", db_path=LIVE_DB)
conn = b.conn
conn.row_factory = sqlite3.Row

# ── 1. 실제 데이터 스냅샷 ──
facts = conn.execute(
    "SELECT fact_id, subject, predicate, object, confidence, source_msg_id FROM facts LIMIT 50"
).fetchall()
edges = conn.execute(
    "SELECT source, target, edge_type, weight FROM graph_edges LIMIT 50"
).fetchall()
mf = conn.execute(
    "SELECT key, value, source_memory_id FROM memoria_facts LIMIT 30"
).fetchall()
print(f"facts={len(facts)} / graph_edges={len(edges)} / memoria_facts(샘플)={len(mf)}")

# ── 2. facts에서 쿼리 생성: subject/object/predicate 조합 ──
def fact_query(f):
    # subject/predicate/object 중 의미 있는 것들로 쿼리 구성
    parts = [p for p in (f["subject"], f["predicate"], f["object"]) if p and str(p).strip()]
    if not parts:
        return None
    # 너무 짧은 건 제외
    parts = [p for p in parts if len(str(p)) > 1]
    return " ".join(str(p) for p in parts[:3]) if parts else None

fact_hits = 0
fact_tested = 0
fact_samples = []
for f in facts:
    q = fact_query(f)
    if not q:
        continue
    g = _graph_lane_search(conn, q, k=10)
    gids = {r["id"] for r in g}
    # facts의 source_msg_id(또는 fact_id)가 회수되는지
    expect = f["source_msg_id"] or f["fact_id"]
    hit = any(gid == expect or gid == f["fact_id"] for gid in gids)
    fact_tested += 1
    fact_hits += hit
    fact_samples.append((q[:40], expect, hit, sorted(x[:12] for x in gids)[:4]))
print(f"\n[facts] 회수: {fact_hits}/{fact_tested} ({fact_hits/fact_tested*100:.1f}%)")
for s in fact_samples[:5]:
    print(f"  q={s[0]!r} expect={s[1]!r} hit={s[2]} got={s[3]}")

# ── 3. graph_edges에서 쿼리 생성: source(gist_xxx)에서 골드 추출 ──
edge_hits = 0
edge_tested = 0
edge_samples = []
for e in edges:
    # gist_<goldid> 형태이면 gold id 추출
    src = e["source"]
    tgt = e["target"]
    gold_candidates = []
    for s in (src, tgt):
        if isinstance(s, str) and s.startswith("gist_"):
            gold_candidates.append(s[5:])
    if not gold_candidates:
        continue
    # 대상 메모리 content에서 쿼리 생성 (찾으면)
    q = None
    for gid in gold_candidates:
        row = conn.execute(
            "SELECT content FROM working_memory WHERE id=?", (gid,)
        ).fetchone()
        if row:
            # content에서 첫 문장 일부로 쿼리
            content = row["content"] or ""
            q = " ".join(content.split())[:50]
            break
    if not q:
        continue
    g = _graph_lane_search(conn, q, k=10)
    gids = {r["id"] for r in g}
    hit = any(gid in gids for gid in gold_candidates)
    edge_tested += 1
    edge_hits += hit
    edge_samples.append((q[:30], gold_candidates[0][:12], hit, sorted(x[:12] for x in gids)[:4]))
print(f"\n[graph_edges] 회수: {edge_hits}/{edge_tested} ({edge_hits/edge_tested*100:.1f}%)")
for s in edge_samples[:5]:
    print(f"  q={s[0]!r} expect={s[1]} hit={s[2]} got={s[3]}")

# ── 4. memoria_facts key/value ──
mf_hits = 0
mf_tested = 0
mf_samples = []
for f in mf:
    k, v = f["key"], f["value"]
    q = f"{k} {v}".strip()
    if not q or len(q) < 2:
        continue
    g = _graph_lane_search(conn, q, k=10)
    gids = {r["id"] for r in g}
    expect = f["source_memory_id"]
    hit = expect in gids if expect else False
    mf_tested += 1
    mf_hits += hit
    mf_samples.append((q[:30], expect, hit, sorted(x[:12] for x in gids)[:4]))
print(f"\n[memoria_facts] 회수: {mf_hits}/{mf_tested} ({mf_hits/mf_tested*100:.1f}%)")
for s in mf_samples[:5]:
    print(f"  q={s[0]!r} expect={s[1]} hit={s[2]} got={s[3]}")

# ── 5. 컨트롤: 무관 쿼리 → 회수 없음 ──
g = _graph_lane_search(conn, "qwertyuiop unrelated gibberish zzz", k=10)
control_ok = len(g) == 0 or not any(
    r["id"] in {f["fact_id"] for f in facts} for r in g
)
print(f"\n[control] 무관 쿼리 회수 없음: {'PASS' if control_ok else 'FAIL'} (got {len(g)})")

print("\n=== 요약 ===")
print(f"facts 회수율: {fact_hits}/{fact_tested}")
print(f"graph_edges 회수율: {edge_hits}/{edge_tested}")
print(f"memoria_facts 회수율: {mf_hits}/{mf_tested}")
print(f"control: {'PASS' if control_ok else 'FAIL'}")