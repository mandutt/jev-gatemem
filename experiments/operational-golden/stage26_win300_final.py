"""stage26: win-300 최종 재검증 — harm-가중 재판정 후 확정 실측 (2026-10-06)

배경:
- stage22: win-300 전체 적용 시 op hit@3 70→76 (+6) vs noans 13→20 (+7) → "순효과 0" 기각
- B AI: 분모 다른 두 세트를 건수로 단순 합한 오류. 실 운영 무답 비율 u=22.5% (query_log 실측) 반영 시
  win-300은 모든 h에서 기대 순이득 +2~4%p → 재검증 필요
- 본 러너: win-300 조건으로 op 90 + noans 50 재실측, hit@1/3/5 + noans FPR + abstain_p 로깅

조건: head-100 (현행) 대비 win-300 (전체 후보에 쿼리 윈도우 300자) — 같은 pool, 같은 choice.
"""
import json, os, sys, time, sqlite3, urllib.request, urllib.error
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")

from keyring import SmartRotator
rot = SmartRotator()
print("키 상태:", rot.stats(), flush=True)

URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"
CHOICE_INSTR = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. Consider directness and specificity. "
    "If no candidate is usable evidence for answering the question, pick the last option."
)

def post(url, body, key, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                rot.on_429(); time.sleep(1.5 * (attempt + 1)); continue
            return e.code, {"__msg": str(e)}
        except Exception:
            time.sleep(1.5)
    return -1, {"__msg": "timeout"}

def choice_call_full(key, query, labels):
    j_labels = list(labels) + [ABSTAIN_LABEL]
    body = {"model": MODEL, "state": {"question": query, "candidates": []},
            "questions": {"best": {"type": "choice", "instructions": CHOICE_INSTR,
                                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}}
    status, resp = post(URL, body, key)
    if status != 200:
        return None, f"http-{status}"
    rot.set_cost((resp.get("usage") or {}).get("cost", None))
    ans = (resp.get("answers") or {}).get("best") or {}
    return ans, None

def query_window(content, query, limit):
    if not content:
        return content or ""
    q_tokens = [t for t in query.replace("?", "").split() if len(t) >= 2]
    best = 0
    if q_tokens:
        low = content.lower()
        for t in q_tokens:
            p = low.find(t.lower())
            if p != -1:
                best = max(0, p - limit // 3)
                break
    return content[best:best + limit]

import sqlite_vec
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)
import mnemosyne.core.beam as beam_mod
from mnemosyne.core import embeddings as emb_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search, POOL_BUDGET

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = emb_mod.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return _imp_search(conn, k=k)
    if kind == "graph": return _graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "importance": r[2]}
    return []

def pool_for(query):
    pool = build_lane_pool(recall_raw, query)
    filtered = _filter_and_rank(pool, query) if pool else []
    return filtered[:POOL_BUDGET]

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
op = [base[q] for q in base]
noans = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
print(f"op {len(op)} + noans {len(noans)} = {len(op)+len(noans)}콜 (win-300)", flush=True)

out = []
done = 0
for r in op + [{"query": n["query"], "gold_id": None, "qid": n.get("qid")} for n in noans]:
    q = r["query"]; gid = r.get("gold_id"); qid = r.get("qid")
    rec = {"query": q, "gold_id": gid, "qid": qid, "grp": "op" if gid else "noans"}
    try:
        pool = pool_for(q)
    except Exception as e:
        rec["err"] = f"pool {type(e).__name__}"
        out.append(rec); continue
    if not pool:
        rec["pool_n"] = 0; out.append(rec); continue
    ids = [c.get("id") for c in pool]
    contents = [c.get("content") or "" for c in pool]
    rec["pool_n"] = len(ids)
    rec["pool_ids"] = ids

    # win-300 labels (전체 후보에 쿼리 윈도우 300자)
    labels = [query_window(c or "", q, 300) or "n/a" for c in contents]
    key = rot.next()
    ans, err = choice_call_full(key, q, labels)
    rec["err"] = err
    if err:
        out.append(rec); continue
    ch = ans.get("choice")
    rec["choice"] = ch
    rec["confidence"] = ans.get("confidence")
    rec["probabilities"] = ans.get("probabilities")
    idx = int(str(ch).lstrip("c")) if ch is not None else None
    abs_idx = len(labels)
    rec["abstain"] = (idx == abs_idx)
    if idx is not None and 0 <= idx < len(ids):
        rec["pick_id"] = ids[idx]
        if gid:
            order = [ids[idx]] + [x for i, x in enumerate(ids) if i != idx]
            rec["gold_rank"] = (order.index(gid) + 1) if gid in order else None
    elif idx == abs_idx:
        rec["pick_id"] = None
        if gid:
            rec["gold_rank"] = None
    out.append(rec)
    done += 1
    if done % 30 == 0:
        print(f"  {done}/{len(op)+len(noans)}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "win-300", "records": out},
          open(os.path.join(DATA, "stage26_win300_final.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("저장 완료", flush=True)

# 요약
op_recs = [r for r in out if r["grp"] == "op" and r.get("pool_n")]
noans_recs = [r for r in out if r["grp"] == "noans" and r.get("pool_n")]

def hitk(r, k):
    gr = r.get("gold_rank")
    return gr is not None and gr <= k

h1 = sum(1 for r in op_recs if hitk(r, 1))
h3 = sum(1 for r in op_recs if hitk(r, 3))
h5 = sum(1 for r in op_recs if hitk(r, 5))
abs_n = sum(1 for r in op_recs if r.get("abstain"))
print(f"\n[op win-300] hit@1={h1} hit@3={h3} hit@5={h5} abstain={abs_n}")

fp = sum(1 for r in noans_recs if not r.get("abstain") and r.get("choice") is not None)
abst_no = sum(1 for r in noans_recs if r.get("abstain"))
print(f"[noans win-300] 오주입={fp} abstain={abst_no}")
conn.close()