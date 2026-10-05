"""Stage-24b: 하네스 패리티 (보정) — gate-pass 12건이 RPC 렌더 context에 포함되는지.

stage24는 RPC 응답이 id 목록이 아니라 렌더된 context 문자열임을 발견.
따라서: 하네스 stage23 pool+gate 결과와 RPC context에 렌더된 행(프리픽스 [YYYY-M..] (importance..) 추출)
의 부분집합 일치를 본다. 구체적으로 gold 19의 gate-pass 여부를 RPC context에서 확인.
0콜 (Jev 미호출, prefetch만).
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

def harness_gate(q):
    """stage23과 동일한 4-lane pool + gate (chunk 제외)."""
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
            out.append({"id": r[0], "content": r[1], "source": r[2], "importance": r[3]})
            if len(out) >= POOL_BUDGET:
                break
    f = _filter_and_rank(out, q, min_distinctive=2, min_coverage=0.30)[:POOL_BUDGET]
    return {r["id"] for r in f}, {r["id"] for r in out}

def rpc_context(q):
    import urllib.request
    body = json.dumps({"agent": "parity2", "query": q, "session_id": "parity-test2",
                       "options": {"max_chars": 0}}).encode()
    req = urllib.request.Request("http://127.0.0.1:47821/v1/prefetch", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {tok}"})
    r = json.load(urllib.request.urlopen(req, timeout=60))
    return r.get("context", "")

def ctx_row_ids(ctx):
    """렌더된 context에서 [날짜] (importance..) 행들 — id는 content 뒤에 없지만 각 행의 첫 줄로 매칭은 어려움.
    대신: context에 포함된 행의 'id'는 렌더에서 안 나오므로, gold 행 content의 시그니처(첫 40자)로 매칭한다."""
    return ctx

def content_sig(content):
    m = re.match(r"^\[[^\]]*\]\s*\[?[0-9]{4}-", content)
    s = content
    s = re.sub(r"^\[[^\]]*\]\s*", "", s)
    return s[:60]

gold_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_final_gold.json")
gold = json.load(open(gold_path, encoding="utf-8"))
print("=== parity: gold 19 — harness gate-pass vs RPC context 포함 ===")
agree = 0
for g in gold:
    q = g["query"]; target = g["row_id"]
    gset, pset = harness_gate(q)
    ctx = rpc_context(q)
    # gold 행 content의 시그니처가 context에 있는지
    r = conn.execute("SELECT content FROM working_memory WHERE id=?", (target,)).fetchone()
    if not r:
        r = conn.execute("SELECT content FROM episodic_memory WHERE id=?", (target,)).fetchone()
    if not r:
        print(f"  {target[:14]}: row 없음"); continue
    sig = content_sig(r["content"])
    # context에 시그니처 포함 여부 (앞 60자)
    in_ctx = sig in ctx
    in_gate = target in gset
    ok = (in_gate == in_ctx)
    agree += ok
    print(f"  {'OK ' if ok else 'MISMATCH'} {target[:14]}: harness_gate={in_gate} rpc_ctx={in_ctx}")
print(f"\nparity agree: {agree}/19")
conn.close()