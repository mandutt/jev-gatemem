"""stage27: 독립 noans 셋 (쉬운 50건) 재검증 — 사전 고정 τ=0.3 (2026-10-06)

목적: stage26에서 튜닝된 "win-300 + abstain_p>0.3 → 빈 컨텍스트" 규칙을
calibration에 안 쓴 독립 noans 셋으로 검증.

- 셋: golden_noanswer_queries.json (쉬운 50건, hard와 qid 겹침 0)
- 조건: win-300 excerpt, choice 호출, abstain_p 로깅
- 사전 고정 τ=0.3 (stage26 시뮬레이션에서 최적 — 재튜닝 금지)
- 측정: abstain_p>0.3 → 빈 컨텍스트 시 오주입 수 (FP)
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
noans = json.load(open(os.path.join(DATA, "golden_noanswer_queries.json"), encoding="utf-8"))
print(f"독립 noans {len(noans)}건 (win-300 + τ=0.3 사전 고정)", flush=True)

TAU = 0.3  # 사전 고정
out = []
done = 0
for n in noans:
    q = n["query"]; qid = n.get("qid")
    rec = {"query": q, "qid": qid}
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
    labels = [query_window(c or "", q, 300) or "n/a" for c in contents]
    key = rot.next()
    ans, err = choice_call_full(key, q, labels)
    rec["err"] = err
    if err:
        out.append(rec); continue
    ch = ans.get("choice")
    rec["choice"] = ch
    rec["confidence"] = ans.get("confidence")
    probs = ans.get("probabilities") or {}
    rec["probabilities"] = probs
    abs_p = probs.get(f"c{len(probs)-1}", 0)
    rec["abstain_p"] = abs_p
    idx = int(str(ch).lstrip("c")) if ch is not None else None
    rec["abstain_choice"] = (idx == len(labels))
    # 최종 노출 판정: choice abstain OR abstain_p > TAU → 빈 컨텍스트
    rec["exposed"] = not (rec["abstain_choice"] or abs_p > TAU)
    out.append(rec)
    done += 1
    if done % 10 == 0:
        print(f"  {done}/{len(noans)}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "win300+tau0.3", "tau": TAU, "records": out},
          open(os.path.join(DATA, "stage27_easy_noans_verify.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("저장 완료", flush=True)

# 요약
ok = [r for r in out if r.get("pool_n")]
fp = sum(1 for r in ok if r.get("exposed"))
abs_choice = sum(1 for r in ok if r.get("abstain_choice"))
abs_gate = sum(1 for r in ok if not r.get("exposed"))
print(f"\n[독립 noans 쉬운 50건]")
print(f"  choice abstain: {abs_choice}")
print(f"  abstain_p>0.3 게이트로 추가 차단: {abs_gate - abs_choice}")
print(f"  최종 오주입(노출): {fp}/50 ({fp/len(ok)*100:.1f}%)")
conn.close()