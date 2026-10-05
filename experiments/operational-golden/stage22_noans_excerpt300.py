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

def choice_call(key, query, labels):
    j_labels = list(labels) + [ABSTAIN_LABEL]
    body = {"model": MODEL, "state": {"question": query, "candidates": []},
            "questions": {"best": {"type": "choice", "instructions": CHOICE_INSTR,
                                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}}
    status, resp = post(URL, body, key)
    if status != 200:
        return None, f"http-{status}"
    rot.set_cost((resp.get("usage") or {}).get("cost", None))
    ans = (resp.get("answers") or {}).get("best") or {}
    ch = ans.get("choice")
    if ch is None: return None, "no-choice"
    i = int(str(ch).lstrip("c"))
    if i == len(labels): return -1, None  # abstain
    if not (0 <= i < len(labels)): return None, "bad-idx"
    return i, None

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

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
noans = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
print(f"hard noans {len(noans)}건", flush=True)

# 파이프라인 pool 조립 (데몬 venv, read-only) — stage19 방식
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
import sqlite_vec, numpy as np
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

out = []
done = 0
for na in noans:
    q = na["query"]
    qid = na.get("qid")
    try:
        pool = pool_for(q)
    except Exception as e:
        out.append({"qid": qid, "query": q, "err": f"pool {type(e).__name__}: {e}"})
        continue
    if not pool:
        out.append({"qid": qid, "query": q, "pool_n": 0, "head100": "no-pool", "win300": "no-pool"})
        continue
    ids = [c.get("id") for c in pool]
    contents = [c.get("content") or "" for c in pool]

    labels100 = [(c or "")[:100] or "n/a" for c in contents]
    key = rot.next()
    idx100, err100 = choice_call(key, q, labels100)
    labels300 = [query_window(c or "", q, 300) or "n/a" for c in contents]
    key = rot.next()
    idx300, err300 = choice_call(key, q, labels300)

    rec = {"qid": qid, "query": q, "pool_n": len(ids),
           "head100_idx": idx100, "head100_err": err100, "head100_abstain": (idx100 == -1),
           "win300_idx": idx300, "win300_err": err300, "win300_abstain": (idx300 == -1)}
    out.append(rec)
    done += 1
    if done % 10 == 0:
        print(f"  {done}/{len(noans)}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "records": out},
          open(os.path.join(DATA, "stage22_noans_excerpt300.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("저장 완료", flush=True)

# 요약: 오주입 = abstain 아닌 선택 (gold 없음)
def fp(recs, key):
    n = sum(1 for r in recs if r.get(key + "_abstain") is False and r.get(key + "_err") is None and r.get(key + "_idx") is not None)
    abst = sum(1 for r in recs if r.get(key + "_abstain") is True)
    return n, abst

recs_ok = [r for r in out if "pool_n" in r]
fp100, ab100 = fp(recs_ok, "head100")
fp300, ab300 = fp(recs_ok, "win300")
print(f"\n[head-100] 오주입 {fp100}/{len(recs_ok)} ({fp100/len(recs_ok)*100:.1f}%) abstain {ab100}")
print(f"[win-300 ] 오주입 {fp300}/{len(recs_ok)} ({fp300/len(recs_ok)*100:.1f}%) abstain {ab300}")
conn.close()