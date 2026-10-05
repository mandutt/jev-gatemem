"""Stage-24: 하네스 패리티 테스트 (b-ai #5) — 실험 하네스와 운영 RPC 경로가 같은 결과를 내는지.

목적: 이 스레드에서 세 번째로 드러난 "실험 ≠ 운영" 문제(임베딩 폴백, RPC 컷 누락, 게이트 파라미터)를
재발 방지. 같은 쿼리에 대해:
  1) 직접 하네스 (stage23에서 쓴 pool5/gate와 동일 경로)
  2) 운영 데몬 RPC (/v1/prefetch, live daemon)
의 gate-pass/pool 결과를 비교한다.

운영 데몬이 떠 있어야 함 (port 47821). 0콜 (Jev 호출 없음, RPC prefetch는 게이트까지만).
"""
import os, re, sqlite3, json, sys
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import winreg
def hkcu_env(name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except OSError:
        return None
tok = hkcu_env("JEV_MEM_TOKEN") or open(r"C:/Users/mandu/AppData/Local/jev-mem/token").read().strip()

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

import mnemosyne.core.beam as beam_mod
from gateway import j1_pipeline as j1p
from gateway.j1_pipeline import _filter_and_rank, _imp_search, _graph_lane_search, POOL_BUDGET

def stage23_pool(q):
    """stage23의 4-lane (chunk 제외) pool 재현."""
    ranks = {}
    def add(kind, rows):
        for i, r in enumerate(rows, start=1):
            ranks.setdefault(r["id"], {})[kind + "_rank"] = i
    add("fts", beam_mod._fts_search_working(conn, q, k=60))
    qemb = beam_mod._embeddings.embed([q])
    if qemb is not None and len(qemb):
        add("vec", beam_mod._wm_vec_search(conn, qemb[0], k=60))
    add("imp", _imp_search(conn, k=8))
    add("graph", _graph_lane_search(conn, q, k=10))
    K = 60
    rr = {rid: sum(1.0/(K+v) for v in rk.values()) for rid, rk in ranks.items()}
    order = sorted(rr, key=lambda x: -rr[x])
    out = []
    for rid in order:
        r = conn.execute("SELECT id, content, source, importance FROM working_memory WHERE id=?", (rid,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, source, importance FROM episodic_memory WHERE id=?", (rid,)).fetchone()
        if r:
            out.append({"id": r[0]})
            if len(out) >= POOL_BUDGET:
                break
    return {r["id"] for r in out}

def rpc_prefetch(q):
    """운영 데몬 파이프라인 호출 (실제 운영 경로)."""
    import urllib.request
    body = json.dumps({"agent": "parity", "query": q, "session_id": "parity-test",
                       "options": {"max_chars": 0}}).encode()
    req = urllib.request.Request("http://127.0.0.1:47821/v1/prefetch", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {tok}"})
    r = json.load(urllib.request.urlopen(req, timeout=60))
    # prefetch 응답에서 게이트 통과 id 집합 추출
    ids = set()
    def walk(o):
        if isinstance(o, dict):
            if "id" in o and isinstance(o.get("id"), str) and len(o["id"]) == 16:
                ids.add(o["id"])
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(r)
    return ids

# gold 19 + op-90 일부 쿼리로 패리티 비교
queries = []
gold_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_final_gold.json")
for g in json.load(open(gold_path, encoding="utf-8"))[:8]:
    queries.append(g["query"])
goldset = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "golden_eval_v3.json"), encoding="utf-8"))
for g in goldset[:12]:
    queries.append(g["query"])

print(f"=== parity: harness pool vs RPC prefetch (20 queries) ===")
agree = 0
for q in queries:
    try:
        hp = stage23_pool(q)
        rp = rpc_prefetch(q)
        inter = len(hp & rp)
        union = len(hp | rp)
        ok = inter / union if union else 1.0
        agree += 1 if ok >= 0.9 else 0
        flag = "OK " if ok >= 0.9 else "MISMATCH"
        print(f"  [{flag}] {q[:30]!r}: jaccard={ok:.2f} (harness {len(hp)}, rpc {len(rp)}, inter {inter})")
    except Exception as e:
        print(f"  [ERR] {q[:30]!r}: {str(e)[:80]}")
print(f"\nparity agree (>=0.9 jaccard): {agree}/{len(queries)}")
conn.close()