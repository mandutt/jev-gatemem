import json, os, sys, time, sqlite3, urllib.request, urllib.error, winreg
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")

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

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}

# 대상 9건: abstain(gold pool 안) 3 + rerank-miss(gold pool 안, rank>3) 6
targets = []
for r in base.values():
    gid = r.get("gold_id")
    pool = r.get("pool_ids") or []
    if r.get("choice_abstain") and gid in pool:
        targets.append(("abstain", r))
    elif not r.get("choice_abstain") and not r.get("err") and gid in pool and (r.get("gold_rank") or 99) > 3:
        targets.append(("rerank-miss", r))
print(f"대상 {len(targets)}건", flush=True)

conn = sqlite3.connect(f"file:{r'C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db'}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

out = []
for kind, r in targets:
    q = r["query"]; gid = r["gold_id"]; pool_ids = r["pool_ids"]
    gold_content = get_content(conn, gid)

    # runR raw에는 pool content가 없다 → gold content만으로 "gold가 답인지" 확인 불가.
    # 대신: JEV choice를 excerpt 100 vs 300으로 다시 호출하려면 pool 전체 content 필요.
    # runR raw의 pool_ids로 DB에서 content 로드 → labels 재구성
    pool_contents = []
    for pid in pool_ids[:40]:
        c = get_content(conn, pid)
        pool_contents.append(c or "n/a")

    # 기존(100자) 결과 재현 + 300자 결과
    for mode, limit in [("head100", 100), ("win300", 300)]:
        labels = [(c or "")[:limit] or "n/a" for c in pool_contents]
        key = rot.next()
        idx, err = choice_call(key, q, labels)
        hit = None
        if err is None and idx is not None and idx >= 0:
            if idx < len(pool_ids) and pool_ids[idx] == gid:
                hit = True  # gold를 1위로
        rec = {"kind": kind, "query": q, "gold_id": gid, "mode": mode,
               "idx": idx, "err": err,
               "gold_at_idx": (idx is not None and idx >= 0 and idx < len(pool_ids) and pool_ids[idx] == gid)}
        out.append(rec)
        print(f"[{kind:12}] {mode}: idx={idx} err={err} gold_pick={rec['gold_at_idx']} | {q[:35]}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "records": out},
          open(os.path.join(DATA, "stage20_excerpt300_pilot.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\n저장 완료", flush=True)
conn.close()