"""stage32: Noul+Choice hybrid 파일럿 — pool 30 + 1콜 (2026-10-06)

설계 (C AI 제안 + stage29/31 API 검증):
- POOL_BUDGET 30 (rank 31~60 gold 0건 실측으로 안전) + noul 30 + choice 1 = 31질문 1요청
- choice: relative selection (최고 증거 1개)
- noul: absolute answerability (후보별 '답인가' 0~1)
- hybrid 정책: noul_top >= tau AND noul_top - noul_second >= delta → choice winner 유지
              아니면 abstain (빈 컨텍스트)
- 측정: op hit@1/3/5 + noans FP, tau/delta 스윕 (0콜 후처리)

비교 대상: 현행 (win-300 + soft gate, pool 60): op hit@3 77, noans hard 16
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
NOUL_PROMPT = "Does this candidate memory directly state or entail the answer to the question? Output a 0-1 score."

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

def hybrid_call(key, query, labels):
    """choice 1 + noul N = N+1 질문 1요청. 반환 (choice_idx, abstain_p, noul_scores, err)."""
    j_labels = list(labels) + [ABSTAIN_LABEL]
    qs = {"best": {"type": "choice", "instructions": CHOICE_INSTR,
                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    for i, lab in enumerate(labels):
        qs[f"n{i}"] = {"type": "noul", "instructions": {"question": NOUL_PROMPT, "candidate": lab}}
    body = {"model": MODEL, "state": {"question": query, "candidates": []}, "questions": qs}
    status, resp = post(URL, body, key)
    if status != 200:
        return None, 0.0, [], f"http-{status}"
    rot.set_cost((resp.get("usage") or {}).get("cost", None))
    ans = resp.get("answers") or {}
    best = ans.get("best") or {}
    ch = best.get("choice")
    abstain_p = 0.0
    probs = best.get("probabilities") or {}
    if probs:
        abstain_p = float(probs.get(f"c{len(j_labels)-1}", 0.0) or 0.0)
    noul = []
    for i in range(len(labels)):
        v = (ans.get(f"n{i}") or {}).get("noul", 0.0)
        noul.append(float(v) if v is not None else 0.0)
    if ch is None:
        return None, abstain_p, noul, "no-choice"
    return int(str(ch).lstrip("c")), abstain_p, noul, None

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
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search

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

def pool_for(query, k=30):
    pool = build_lane_pool(recall_raw, query)
    filtered = _filter_and_rank(pool, query) if pool else []
    return filtered[:k]

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
op = [base[q] for q in base]
noans = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
print(f"op {len(op)} + noans {len(noans)} = {len(op)+len(noans)}콜 (hybrid pool30)", flush=True)

out = []
done = 0
for r in op + [{"query": n["query"], "gold_id": None, "qid": n.get("qid")} for n in noans]:
    q = r["query"]; gid = r.get("gold_id"); qid = r.get("qid")
    rec = {"query": q, "gold_id": gid, "qid": qid, "grp": "op" if gid else "noans"}
    try:
        pool = pool_for(q, k=30)
    except Exception as e:
        rec["err"] = f"pool {type(e).__name__}"
        out.append(rec); continue
    if not pool:
        rec["pool_n"] = 0; out.append(rec); continue
    ids = [c.get("id") for c in pool]
    contents = [c.get("content") or "" for c in pool]
    rec["pool_n"] = len(ids)
    rec["pool_ids"] = ids
    labels = [query_window(c or "", q, 300)[:150] or "n/a" for c in contents]
    key = rot.next()
    idx, abstain_p, noul, err = hybrid_call(key, q, labels)
    rec["err"] = err
    if err:
        out.append(rec); continue
    rec["choice"] = idx
    rec["abstain_p"] = abstain_p
    rec["noul_scores"] = noul
    rec["noul_top"] = max(noul) if noul else 0.0
    # noul top 2
    sorted_noul = sorted(noul, reverse=True)
    rec["noul_second"] = sorted_noul[1] if len(sorted_noul) > 1 else 0.0
    rec["noul_margin"] = rec["noul_top"] - rec["noul_second"]
    abs_idx = len(labels)
    rec["choice_abstain"] = (idx == abs_idx)
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

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "hybrid-pool30", "records": out},
          open(os.path.join(DATA, "stage32_hybrid_pool30.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("저장 완료", flush=True)

# 즉석 요약: choice만 (현행과 동일 조건 pool30)
op_recs = [r for r in out if r["grp"] == "op" and r.get("pool_n")]
noans_recs = [r for r in out if r["grp"] == "noans" and r.get("pool_n")]

def hitk(r, k):
    gr = r.get("gold_rank")
    return gr is not None and gr <= k

h1 = sum(1 for r in op_recs if hitk(r, 1))
h3 = sum(1 for r in op_recs if hitk(r, 3))
h5 = sum(1 for r in op_recs if hitk(r, 5))
abs_n = sum(1 for r in op_recs if r.get("choice_abstain"))
print(f"\n[op pool30 choice-only] hit@1={h1} hit@3={h3} hit@5={h5} abstain={abs_n}")
fp = sum(1 for r in noans_recs if not r.get("choice_abstain"))
print(f"[noans pool30] FP={fp}")

# noul 분포
tops = [r.get("noul_top") or 0 for r in op_recs]
if tops:
    print(f"noul_top: min={min(tops):.2f} max={max(tops):.2f} mean={sum(tops)/len(tops):.2f}")
conn.close()