"""stage33: 2콜 구조 — noul top-5 재choice (2026-10-06)

설계: 1콜째 stage32 hybrid(pool30, choice+noul 31질문)에서
      noul top-5만 추려 2콜째 choice 재실행 (criteria 5 + abstain = 6개, 소량 토큰)
목표: choice miss 6건 중 gold가 noul top-5에 있던 경우 구제 (0콜 상한 +6)
측정: op hit@1/3/5 + noans FP (2콜 구조 전체)
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
CHOICE_INSTR_SHORT = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. If no candidate is usable evidence, pick the last option."
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

def choice_only(key, query, labels):
    """choice 1호출 (criteria N+1) → (idx, abstain_p, err). 토큰 소량."""
    j_labels = list(labels) + [ABSTAIN_LABEL]
    qs = {"best": {"type": "choice", "instructions": CHOICE_INSTR_SHORT,
                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    body = {"model": MODEL, "state": {"question": query, "candidates": []}, "questions": qs}
    status, resp = post(URL, body, key)
    if status != 200:
        return None, 0.0, f"http-{status}"
    rot.set_cost((resp.get("usage") or {}).get("cost", None))
    ans = resp.get("answers") or {}
    best = ans.get("best") or {}
    ch = best.get("choice")
    abstain_p = 0.0
    probs = best.get("probabilities") or {}
    if probs:
        abstain_p = float(probs.get(f"c{len(j_labels)-1}", 0.0) or 0.0)
    if ch is None:
        return None, abstain_p, "no-choice"
    return int(str(ch).lstrip("c")), abstain_p, None

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw32 = json.load(open(os.path.join(DATA, "stage32_hybrid_pool30.json"), encoding="utf-8"))
recs32 = raw32["records"]

# noul top-5 재선택 (2콜째 후보)
out = []
done = 0
for r in recs32:
    q = r["query"]; gid = r.get("gold_id")
    rec = {"query": q, "gold_id": gid, "qid": r.get("qid"), "grp": "op" if gid else "noans"}
    rec["s1"] = {k: r.get(k) for k in ["choice", "choice_abstain", "abstain_p", "pool_ids", "pool_n", "err"] if r.get(k) is not None}
    if r.get("err"):
        out.append(rec); continue
    if not r.get("pool_ids"):
        out.append(rec); continue
    ids = r["pool_ids"]
    contents = [r.get("_labels", [])] if False else None
    # noul top-5 순위
    noul = r["noul_scores"]
    order = sorted(range(len(noul)), key=lambda i: noul[i], reverse=True)[:5]
    top_ids = [ids[i] for i in order]
    labels = [r.get("w300", {}).get(str(ids[i]), f"cand {i}") for i in order]  # w300 미저장 시 placeholder
    # 실제로는 w300이 없으므로 재구성 필요 — pool/content 재조회
    out.append(rec)

print(f"재구성 필요 — stage32에 w300 라벨 미저장. pool 재조회 및 2콜째 실행", flush=True)
conn = sqlite3.connect(r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db")
conn.row_factory = sqlite3.Row
def get_content(mid):
    row = conn.execute("SELECT content FROM working_memory WHERE id=?", (mid,)).fetchone()
    if not row:
        row = conn.execute("SELECT content FROM episodic_memory WHERE id=?", (mid,)).fetchone()
    return row["content"] if row else ""

def qwindow(content, query, limit=300):
    if not content: return ""
    q_tokens = [t for t in query.replace("?", "").split() if len(t) >= 2]
    best = 0
    if q_tokens:
        low = content.lower()
        for t in q_tokens:
            p = low.find(t.lower())
            if p != -1:
                best = max(0, p - limit // 3); break
    return content[best:best + limit]

results = []
for r in recs32:
    q = r["query"]; gid = r.get("gold_id")
    rec = {"query": q, "gold_id": gid, "grp": "op" if gid else "noans", "qid": r.get("qid")}
    rec["s1_choice"] = r.get("choice"); rec["s1_abstain"] = r.get("choice_abstain")
    rec["s1_abstain_p"] = r.get("abstain_p"); rec["pool_ids"] = r.get("pool_ids")
    if r.get("err") or not r.get("pool_ids"):
        rec["err"] = r.get("err") or "no-pool"
        results.append(rec); continue
    ids = r["pool_ids"]
    noul = r.get("noul_scores") or []
    if not noul:
        rec["err"] = "no-noul"; results.append(rec); continue
    order = sorted(range(len(noul)), key=lambda i: noul[i], reverse=True)[:5]
    top_ids = [ids[i] for i in order]
    labels = [qwindow(get_content(mid), q, 300)[:150] or "n/a" for mid in top_ids]
    key = rot.next()
    idx, abstain_p, err = choice_only(key, q, labels)
    rec["s2_choice"] = idx
    rec["s2_abstain"] = (idx == len(labels)) if idx is not None else None
    rec["s2_abstain_p"] = abstain_p
    rec["s2_err"] = err
    if idx is not None and 0 <= idx < len(top_ids):
        rec["pick_id"] = top_ids[idx]
        if gid:
            order2 = [top_ids[idx]] + [x for i, x in enumerate(top_ids) if i != idx]
            rec["gold_rank"] = (order2.index(gid) + 1) if gid in order2 else None
    elif idx == len(labels):
        rec["pick_id"] = None
        if gid: rec["gold_rank"] = None
    rec["top5_noul"] = [round(noul[i], 3) for i in order]
    results.append(rec)
    done += 1
    if done % 30 == 0:
        print(f"  {done}/{len(recs32)}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "2call-noul5-rechoice", "records": results},
          open(os.path.join(DATA, "stage33_2call_noul5.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
conn.close()
print("저장 완료", flush=True)

# 요약: 2콜 최종 = s2 결과 (게이트 τ 적용 전 raw)
op_recs = [r for r in results if r["grp"] == "op" and r.get("pool_ids")]
noans_recs = [r for r in results if r["grp"] == "noans" and r.get("pool_ids")]
def hitk(r, k):
    gr = r.get("gold_rank")
    return gr is not None and gr <= k
h1 = sum(1 for r in op_recs if hitk(r, 1))
h3 = sum(1 for r in op_recs if hitk(r, 3))
h5 = sum(1 for r in op_recs if hitk(r, 5))
abs2 = sum(1 for r in op_recs if r.get("s2_abstain"))
fp = sum(1 for r in noans_recs if r.get("s2_abstain") is False or (r.get("s2_abstain") is None and not r.get("err")))
print(f"\n[op 2콜] hit@1={h1} hit@3={h3} hit@5={h5} s2-abstain={abs2}")
print(f"[noans 2콜] FP={fp} (s2 choice가 abstain 아닌 경우)")