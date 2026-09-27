"""합성 graph 데이터로 graph lane 회수 경로 검증.

스냅샷 DB의 복사본에 facts/graph_edges/memoria_facts를 심고,
_graph_lane_search가 의도대로 회수하는지 각 경로별로 검증한다.
원본 스냅샷/라이브 DB는 건드리지 않는다.
"""
import json, sqlite3, shutil, sys, os
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
from mnemosyne.core.beam import BeamMemory
from mnemosyne.core import beam as beam_mod
from gateway.j1_pipeline import _graph_lane_search

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
TEST_DB = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-test-graph.db"

# 1. 복사본 생성
shutil.copy2(SNAP, TEST_DB)
print("복사본 생성:", TEST_DB)

con = sqlite3.connect(TEST_DB)
cur = con.cursor()

# 2. 시드: 실제 gold 중 설명이 분명한 5개 선택 (내용 확인)
Q = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json", encoding="utf-8"))
gold_ids = []
for q in Q:
    gold_ids.extend(q["gold_ids"])
gold_ids = list(dict.fromkeys(gold_ids))
# 실제 content 확인 후 시드 6개 (stealth/camelai/exa/python/import 관련)
seeds = [
    "09547ea49fc36991",  # Hermes 브라우저 stealth 판단 기준
    "1928d454e0ed168b",  # Hermes 내장 browser_* 도구 라우팅 (camelai?)
    "0ea67a3b101917e5",  # 웹 수집·추출 tavily
    "9d4feaccfa1020b4",  # web_extract 키리스
    "36f843b4b1886e39",  # 게이트웨이 워치독
    "b5f5672a2446d4e8",  # Windows/macOS 공통 회귀
]
gold_ids = [g for g in seeds if g in gold_ids]
print(f"시드 gold: {[g[:12] for g in gold_ids]}")

# 3. 기존 facts/graph_edges/memoria_facts 백업 (검증 후 복원 위해 삭제)
for t in ("facts", "graph_edges", "memoria_facts"):
    cur.execute(f"DELETE FROM {t}")

# 4. 합성 facts: 실제 쿼리셋과 매치되는 트리플
#    - "stealth" 쿼리에 매치: subject='StealthBrowser' object='needed' -> content에 stealth 있는 09547ea49fc3
#    - "camelai" 쿼리에 매치: subject='CamelAI' object='proxy'
#    - "exa" 쿼리에 매치: subject='Exa' object='mojibake'
synthetic_facts = [
    # (fact_id, session_id, subject, predicate, object, timestamp, source_msg_id, confidence)
    ("fact_test_stealth", "default", "StealthBrowser", "is", "needed", "2026-09-01T00:00:00", gold_ids[0], 0.9),
    ("fact_test_camel", "default", "CamelAI", "is", "proxy", "2026-09-01T00:00:00", gold_ids[1], 0.9),
    ("fact_test_exa", "default", "Exa", "causes", "mojibake", "2026-09-01T00:00:00", gold_ids[2], 0.8),
]
for f in synthetic_facts:
    cur.execute(
        "INSERT INTO facts (fact_id, session_id, subject, predicate, object, timestamp, source_msg_id, confidence, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (*f, "2026-09-01 00:00:00"),
    )

# 5. 합성 graph_edges: gist_<gold_id> -> fact_<gold_id>_0 (실제 형식)
for i, gid in enumerate(gold_ids[:3]):
    cur.execute(
        "INSERT INTO graph_edges (source, target, edge_type, weight, timestamp, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (f"gist_{gid}", f"fact_test_{['stealth','camel','exa'][i]}", "ctx", 0.8,
         "2026-09-01T00:00:00", "2026-09-01 00:00:00"),
    )

# 6. 합성 memoria_facts: key-value (버전/메트릭) — gold_ids[3]에 매치
for i, gid in enumerate(gold_ids[3:4]):
    cur.execute(
        "INSERT INTO memoria_facts (session_id, message_idx, fact_type, key, value, context_snippet, importance, timestamp, source_memory_id)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        ("default", 0, "version", "python_version", "3.13.14", "...", 0.7,
         "2026-09-01T00:00:00", gid),
    )
con.commit()
print("합성 데이터 심기 완료")

# 7. 각 경로 검증
b = BeamMemory(session_id="eval", db_path=TEST_DB)

def check(label, query, expect_gold):
    g = _graph_lane_search(b.conn, query, k=10)
    gids = {r["id"] for r in g}
    ok = expect_gold in gids
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: query={query[:35]!r} -> expect={expect_gold[:12]} got={sorted(x[:12] for x in gids)[:5]}")
    return ok

results = []
# 경로 A: facts subject/object 매치
results.append(check("facts subject", "stealth browser needed when", gold_ids[0]))
results.append(check("facts object", "camelai proxy", gold_ids[1]))
results.append(check("facts object2", "exa mojibake why", gold_ids[2]))
# 경로 B: graph_edges gist 스트립 + 관련성 게이트 (gist 메모리 content에 stealth 있어야)
results.append(check("graph_edges ctx", "stealth browser", gold_ids[0]))
# 경로 C: memoria_facts key/value (python_version -> python, version 분리 토큰)
results.append(check("memoria key", "python version what", gold_ids[3]))
# 컨트롤: 무관 쿼리 → gold 미회수 (관련성 게이트)
g = _graph_lane_search(b.conn, "qwertyuiop unrelated gibberish", k=10)
control_ok = not ({r["id"] for r in g}.intersection(set(gold_ids)))
print(f"  [{'PASS' if control_ok else 'FAIL'}] control: 무관 쿼리 gold 미회수")
results.append(control_ok)

n_pass = sum(results)
print(f"\n결과: {n_pass}/{len(results)} PASS")
# 8. 정리: 테스트 DB 삭제 (원본 스냅샷 보존)
con.close()
for _ in range(3):
    try:
        os.remove(TEST_DB)
        break
    except PermissionError:
        import time
        time.sleep(0.3)
print("테스트 DB 정리 완료")
sys.exit(0 if n_pass == len(results) else 1)