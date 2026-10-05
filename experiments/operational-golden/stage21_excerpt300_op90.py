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
    if i == len(labels): return -1, None
    if not (0 <= i < len(labels)): return None, "bad-idx"
    return i, None

def get_content(conn, gid):
    r = conn.execute("SELECT content FROM working_memory WHERE id=?", (gid,)).fetchone()
    if r: return r["content"]
    r = conn.execute("SELECT content FROM episodic_memory WHERE id=?", (gid,)).fetchone()
    return r["content"] if r else None

def query_window(content, query, limit):
    """쿼리 단어 기반 윈도우: 쿼리 토큰이 content에서 처음 등장하는 위치 기준 ±limit/2."""
    if not content:
        return content or ""
    q_tokens = [t for t in query.replace("?", "").split() if len(t) >= 2]
    best = 0
    if q_tokens:
        low = content.lower()
        pos = -1
        for t in q_tokens:
            p = low.find(t.lower())
            if p != -1:
                pos = p
                break
        if pos != -1:
            best = max(0, pos - limit // 3)
    return content[best:best + limit]

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
print(f"op 쿼리 {len(base)}건", flush=True)

conn = sqlite3.connect(f"file:{r'C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db'}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

def compute_hit3(idx, pool_ids, gold_id, abstain):
    if abstain or idx is None or idx < 0:
        return False, "abstain/miss"
    if idx >= len(pool_ids):
        return False, "bad-idx"
    # choice가 고른 후보 기준 gold까지의 거리: 골든셋 hit@3 = gold가 상위 3안
    # choice가 1위로 lift한 후보가 gold면 rank 1. gold가 pool에 있고 choice가 다른 걸 1위로
    # 골랐으면 그 사이 거리 측정. runR raw gold_rank 산식과 동일하게:
    order = [pool_ids[idx]] + [x for i, x in enumerate(pool_ids) if i != idx]
    gr = (order.index(gold_id) + 1) if gold_id in order else None
    return (gr is not None and gr <= 3), gr

out = []
done = 0
for q, r in base.items():
    gid = r["gold_id"]; pool_ids = r.get("pool_ids") or []
    if not pool_ids or gid not in pool_ids:
        # gold가 pool 밖이면 excerpt 변화와 무관 — 기록만
        out.append({"query": q, "gold_in_pool": False, "head100_gr": None, "win300_gr": None, "skip": "gold-not-in-pool"})
        continue
    pool_contents = []
    for pid in pool_ids:
        c = get_content(conn, pid)
        pool_contents.append(c or "n/a")

    # head-100 (현행)
    labels100 = [(c or "")[:100] or "n/a" for c in pool_contents]
    key = rot.next()
    idx100, err100 = choice_call(key, q, labels100)
    gr100 = None
    if err100 is None and idx100 is not None and idx100 >= 0:
        order = [pool_ids[idx100]] + [x for i, x in enumerate(pool_ids) if i != idx100]
        gr100 = (order.index(gid) + 1) if gid in order else None
    abst100 = (idx100 == -1)

    # win-300 (전체에 적용)
    labels300 = [query_window(c or "", q, 300) or "n/a" for c in pool_contents]
    key = rot.next()
    idx300, err300 = choice_call(key, q, labels300)
    gr300 = None
    if err300 is None and idx300 is not None and idx300 >= 0:
        order = [pool_ids[idx300]] + [x for i, x in enumerate(pool_ids) if i != idx300]
        gr300 = (order.index(gid) + 1) if gid in order else None
    abst300 = (idx300 == -1)

    out.append({"query": q, "gold_in_pool": True, "cat": r.get("cat"),
                "head100_gr": gr100, "head100_abstain": abst100, "head100_err": err100,
                "win300_gr": gr300, "win300_abstain": abst300, "win300_err": err300})
    done += 1
    if done % 15 == 0:
        print(f"  {done}/{len(base)}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "records": out},
          open(os.path.join(DATA, "stage21_excerpt300_op90.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("저장 완료", flush=True)

# 요약
gold_in = [o for o in out if o.get("gold_in_pool")]
h100 = sum(1 for o in gold_in if o.get("head100_gr") is not None and o["head100_gr"] <= 3)
h300 = sum(1 for o in gold_in if o.get("win300_gr") is not None and o["win300_gr"] <= 3)
print(f"\ngold pool 내 {len(gold_in)}건: head-100 hit@3 {h100} / win-300 hit@3 {h300}")
a100 = sum(1 for o in gold_in if o.get("head100_abstain"))
a300 = sum(1 for o in gold_in if o.get("win300_abstain"))
print(f"abstain: head-100 {a100} / win-300 {a300}")
conn.close()