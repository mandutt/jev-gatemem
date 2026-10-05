"""stage24: 조건부 win-300 + pair 게이트 (JEV 2콜) 파일럿 — 2026-10-05

배경:
- stage21: win-300 전체 적용 시 gold hit@3 70→76 (abstain 3건 해소)
- stage22: win-300 전체 적용 시 noans 오주입 13→20 (악화) → 전체 적용 기각
- stage23: 오주입은 전부 "과거 이력/시점" 질문이 주제 근접 미끼에 속은 것 (PLAUS/IRREL)

가설 (option 2):
  1차(head-100) → abstain이면 2차(win-300) → 2차 결과에 pair entailment 게이트
  ("직접 답인가 YES/NO")를 추가하면:
    - noans 오주입: 2차에서 선택된 미끼가 게이트 NO로 걸러짐 → 오주입 감소
    - gold 회복: 2차에서 gold 선택 시 게이트 YES로 유지 → 회복 유지
  위 두 조건이 동시에 성립하는지 실측.

측정 대상 (API call):
- noans hard 50건: 1차 choice(head-100) → abstain만 2차 choice(win-300) → 2차 선택에 게이트
- gold abstain 3건 (stage21 대상): 동일 3단계 → 회복 유지 확인

비용: noans 50 + gold 3 = 53콜 1차 + abstain분 2차 + 2차분 게이트 ≈ 최대 130콜 (free lane)
출력: data/stage24_conditional_win300_gate.json
"""
import json, os, sys, time, sqlite3, urllib.request, urllib.error
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")
os.environ["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/bekko-a8m"

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
GATE_PROMPT = (
    "Does this memory directly state or entail the answer to the question? "
    "Answer YES if it contains the specific fact/value/rule the question asks for. "
    "Answer NO if it only shares the topic, related keywords, or background."
)
GATE_LABELS = ["YES", "NO"]

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
    if i == len(labels): return -1, None
    if not (0 <= i < len(labels)): return None, "bad-idx"
    return i, None

def gate_call(key, query, candidate_text):
    body = {"model": MODEL, "state": {"question": query, "candidate": candidate_text},
            "questions": {"gate": {"type": "choice", "instructions": GATE_PROMPT,
                                   "criteria": {"c0": GATE_LABELS[0], "c1": GATE_LABELS[1]}}}}
    status, resp = post(URL, body, key)
    if status != 200:
        return None, f"http-{status}"
    rot.set_cost((resp.get("usage") or {}).get("cost", None))
    ans = (resp.get("answers") or {}).get("gate") or {}
    ch = ans.get("choice")
    if ch is None: return None, "no-choice"
    i = int(str(ch).lstrip("c"))
    if not (0 <= i < len(GATE_LABELS)): return None, "bad-idx"
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

# ---- pool 조립 (데몬 venv, read-only) ----
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
noans = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
rawR = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in rawR["records"] if r.get("alpha") == 0.0}
gold_abs = [r for r in base.values() if r.get("choice_abstain")]
print(f"noans {len(noans)} + gold abstain {len(gold_abs)}건", flush=True)

def pipeline(q, gid=None):
    """1차 head-100 → abstain시 2차 win-300 → 2차 선택에 게이트."""
    rec = {"query": q, "gold_id": gid}
    try:
        pool = pool_for(q)
    except Exception as e:
        rec["err"] = f"pool {type(e).__name__}"
        return rec
    if not pool:
        rec["pool_n"] = 0
        return rec
    ids = [c.get("id") for c in pool]
    contents = [c.get("content") or "" for c in pool]
    rec["pool_n"] = len(ids)

    # 1차: head-100
    labels100 = [(c or "")[:100] or "n/a" for c in contents]
    key = rot.next()
    idx1, err1 = choice_call(key, q, labels100)
    rec["s1_idx"] = idx1; rec["s1_err"] = err1; rec["s1_abstain"] = (idx1 == -1)
    if err1 is None and idx1 is not None and idx1 >= 0:
        # 1차 선택 → gold 회복 판정 (골드 쿼리만)
        if gid:
            order = [ids[idx1]] + [x for i, x in enumerate(ids) if i != idx1]
            rec["s1_gold_rank"] = (order.index(gid) + 1) if gid in order else None
        rec["final"] = "s1-pick"
        return rec

    # 2차: win-300 (1차 abstain만)
    labels300 = [query_window(c or "", q, 300) or "n/a" for c in contents]
    key = rot.next()
    idx2, err2 = choice_call(key, q, labels300)
    rec["s2_idx"] = idx2; rec["s2_err"] = err2; rec["s2_abstain"] = (idx2 == -1)
    if err2 is None and idx2 is not None and idx2 >= 0:
        if gid:
            order = [ids[idx2]] + [x for i, x in enumerate(ids) if i != idx2]
            rec["s2_gold_rank"] = (order.index(gid) + 1) if gid in order else None
        # 게이트: 2차 선택 후보의 win-300 텍스트로 YES/NO
        cand_text = query_window(contents[idx2], q, 300)
        key = rot.next()
        gidx, gerr = gate_call(key, q, cand_text)
        rec["gate_idx"] = gidx; rec["gate_err"] = gerr
        rec["gate_yes"] = (gidx == 0)
        rec["final"] = "s2-gate-yes" if gidx == 0 else "s2-gate-no"
    else:
        rec["final"] = "abstain"
    return rec

out = []
done = 0
for na in noans:
    r = pipeline(na["query"])
    r["grp"] = "noans"; r["qid"] = na.get("qid")
    out.append(r)
    done += 1
    if done % 10 == 0: print(f"  noans {done}/{len(noans)}", flush=True)
for gr in gold_abs:
    r = pipeline(gr["query"], gid=gr["gold_id"])
    r["grp"] = "gold"
    out.append(r)
    done += 1
    print(f"  gold {done - len(noans)}/{len(gold_abs)}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "records": out},
          open(os.path.join(DATA, "stage24_conditional_win300_gate.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("저장 완료", flush=True)

# 요약
noans_recs = [r for r in out if r["grp"] == "noans" and r.get("pool_n")]
fp = sum(1 for r in noans_recs if r.get("final") in ("s1-pick", "s2-gate-yes"))
print(f"\n[noans] 오주입(s1-pick + s2-gate-yes): {fp}/{len(noans_recs)}")
s1fp = sum(1 for r in noans_recs if r.get("final") == "s1-pick")
s2fp = sum(1 for r in noans_recs if r.get("final") == "s2-gate-yes")
s2no = sum(1 for r in noans_recs if r.get("final") == "s2-gate-no")
s2abs = sum(1 for r in noans_recs if r.get("final") == "abstain")
print(f"  s1-pick {s1fp} | s2-gate-yes {s2fp} | s2-gate-no(차단) {s2no} | abstain {s2abs}")

gold_recs = [r for r in out if r["grp"] == "gold" and r.get("pool_n")]
rec_ok = sum(1 for r in gold_recs if (r.get("s2_gold_rank") or 99) <= 3 and r.get("final") in ("s2-gate-yes",))
print(f"\n[gold abstain 3건] 2차+게이트 통과 후 hit@3: {rec_ok}/{len(gold_recs)}")
for r in gold_recs:
    print(f"  {r['query'][:45]} | s2_idx={r.get('s2_idx')} s2_gold_rank={r.get('s2_gold_rank')} gate={r.get('gate_idx')} final={r.get('final')}")
conn.close()