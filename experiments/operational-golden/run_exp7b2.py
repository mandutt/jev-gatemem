"""후속 실험 2b — leave-gold-out A(choice) 측정 (B 제안 완전 이행) (2026-10-04)

B: "op 90건에서 gold 행을 제거하고 A와 C(τ별)의 오주입률을 재세요"
- exp7b (pointwise) 완료: τ=0.65에서도 45.6% 오주입
- 본 실행: 동일 leave-gold-out 조건에서 A(choice 1콜, abstain 포함) 측정

gold를 제거한 pool에 choice를 실행 → abstain 선택 = 안전, 오답 선택 = 오주입.
5차 B(full choice)에서 op 29건 중 27건 오답 선택 관측과 대조 가능.

출력: experiments/operational-golden/data/exp7b2_lgo_choice_raw.json
"""
import json
import os
import sys
import time
import sqlite3
import hashlib
import urllib.request
import urllib.error
import winreg

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "experiments/operational-golden/data")
LIVE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
MAX_CRIT = 64
MAX_CAND = MAX_CRIT - 1
MAX_CAND_CHARS = 1350
WORKERS = 3
SLEEP = 0.0
CHOICE_INSTR = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. Consider directness and specificity. "
    "If no candidate is usable evidence for answering the question, pick the last option.")
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"


def resolve_key():
    k = os.environ.get("EXPLABS_API_KEY", "")
    try:
        hk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        try:
            rk, _ = winreg.QueryValueEx(hk, "EXPLABS_API_KEY")
            if rk:
                k = rk
        finally:
            winreg.CloseKey(hk)
    except FileNotFoundError:
        pass
    return k.strip().strip('"')


def excerpt(text, limit=100):
    t = (text or "").replace("\n", " ").strip()
    return t[:limit]


def post(url, body, key, timeout=180.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    for attempt in range(6):
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                try:
                    wait = float(ra) if ra else 60.0
                except ValueError:
                    wait = 60.0
                print(f"    429 → {wait:.0f}s 드레인 대기 (attempt {attempt+1}/6)", flush=True)
                time.sleep(wait)
                continue
            return e.code, {"__msg": e.read().decode()[:200]}
        except Exception as e:
            if attempt == 5:
                return -1, {"__msg": f"{type(e).__name__}"}
            time.sleep(1.5)
    return 429, {"__msg": "rate limited"}


def choice_call(key, query, cands):
    labels = [excerpt(c, 100) or "n/a" for c in cands]
    j_labels = list(labels) + [ABSTAIN_LABEL]
    body = {"model": MODEL, "state": {"question": query, "candidates": []},
            "questions": {"best": {"type": "choice", "instructions": CHOICE_INSTR,
                                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}}
    status, resp = post(URL, body, key)
    if status != 200:
        return None, None, f"http-{status}"
    cost = (resp.get("usage") or {}).get("cost", None)
    ans = (resp.get("answers") or {}).get("best") or {}
    ch = ans.get("choice")
    if ch is None:
        return None, cost, "no-choice"
    i = int(str(ch).lstrip("c"))
    if i == len(labels):
        return -1, cost, None
    if not (0 <= i < len(labels)):
        return None, cost, "bad-idx"
    return i, cost, None


def get_beam_refs():
    sys.path.insert(0, ROOT)
    os.environ.setdefault("MNEMOSYNE_DB", LIVE_DB)
    import gateway.j1_pipeline as j1p
    import mnemosyne.core.beam as bm
    from mnemosyne.core import embeddings as emb_mod
    b = bm.BeamMemory(session_id="exp7b2")

    def recall_raw(kind, arg, k_):
        if kind == "fts":
            return bm._fts_search_working(b.conn, arg, k=k_)
        if kind == "vec":
            e = emb_mod.embed([arg])
            if e is None or not len(e):
                return []
            return bm._wm_vec_search(b.conn, e[0], k=k_)
        if kind == "imp":
            return j1p._imp_search(b.conn, k=k_)
        if kind == "graph":
            return j1p._graph_lane_search(b.conn, arg, k=k_)
        if kind == "get":
            from core import j1_engine
            row = j1_engine.hydration_get(b, arg)
            return row if isinstance(row, dict) else None
        return []
    return recall_raw, j1p


def stage1_pool(query, exclude_ids, k=40):
    recall_raw, j1p = get_beam_refs()
    pool = j1p.build_lane_pool(recall_raw, query)
    pool = [p for p in pool if p.get("id") not in exclude_ids]
    ranked = j1p._filter_and_rank(pool, query) if pool else []
    return ranked[:k]


def main():
    key = resolve_key()
    if not key:
        print("FAIL: no key")
        return 2
    print(f"key: len={len(key)} prefix={key[:4]}... | leave-gold-out A(choice) | 병렬 {WORKERS}", flush=True)

    conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content, memory_type, scope, importance, source FROM working_memory"
        " WHERE valid_until IS NULL AND content IS NOT NULL AND content != ''"
        " ORDER BY created_at").fetchall()
    conn.close()
    corpus = [dict(r) for r in rows]
    by_id = {c["id"]: c for c in corpus}
    corp_hash = hashlib.sha256(json.dumps([c["id"] for c in corpus], ensure_ascii=False).encode()).hexdigest()[:16]
    print(f"코퍼스: {len(corpus)}행 / 해시={corp_hash}", flush=True)

    out = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "A-choice-leave-gold-out",
           "corpus_n": len(corpus), "corpus_hash": corp_hash, "records": [],
           "lane": {"free": 0, "credit": 0, "unknown": 0}}

    def save():
        json.dump(out, open(os.path.join(DATA, "exp7b2_lgo_choice_raw.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    op = json.load(open(os.path.join(DATA, "golden_eval_v2.json"), encoding="utf-8"))
    op_eval = [x for x in op if x.get("gold_id") and x.get("cat") != "NO_ANSWER"]
    print(f"\n=== leave-gold-out A(choice) {len(op_eval)}건 ===", flush=True)

    for i, x in enumerate(op_eval):
        q = x["query"]
        gold = x["gold_id"]
        try:
            pool = stage1_pool(q, exclude_ids={gold}, k=40)
        except Exception as e:
            out["records"].append({"src": "op", "qid": x.get("gold_id"), "query": q,
                                   "err": f"pool {type(e).__name__}"})
            save()
            continue
        pool = [p for p in pool if p.get("id") in by_id]
        cands = [c["content"][:MAX_CAND_CHARS] for c in pool][:MAX_CAND]
        if not cands:
            out["records"].append({"src": "op", "qid": x.get("gold_id"), "query": q, "err": "empty-pool"})
            save()
            continue
        idx, cost, err = choice_call(key, q, cands)
        rec = {"src": "lgo-choice", "qid": x.get("gold_id"), "query": q, "gold_removed": gold,
               "n_pool": len(cands), "err": err}
        if cost is not None:
            out["lane"]["free" if cost == 0.0 else ("credit" if cost else "unknown")] += 1
        if idx is None:
            rec["abstain"] = None
            rec["chosen"] = None
        elif idx == -1:
            rec["abstain"] = True
            rec["chosen"] = None
        else:
            rec["abstain"] = False
            rec["chosen"] = pool[idx]["id"]
            rec["chosen_excerpt"] = (pool[idx]["content"] or "")[:80]
            # gold가 실수로 pool에 남아있지 않은지 확인 (제거 검증)
            rec["gold_in_pool"] = any(c["id"] == gold for c in pool)
        out["records"].append(rec)
        save()
        if (i + 1) % 10 == 0:
            print(f"  lgo-choice {i+1}/{len(op_eval)}", flush=True)

    rr = [r for r in out["records"] if not r.get("err")]
    n = len(rr)
    abst = sum(1 for r in rr if r.get("abstain"))
    wrong = sum(1 for r in rr if r.get("abstain") is False)
    gold_leak = sum(1 for r in rr if r.get("gold_in_pool"))
    print("\n=== leave-gold-out A(choice) 요약 ===")
    print(f"n={n} | abstain(안전)={abst} ({abst/n*100:.1f}%) | 오답 선택(오주입)={wrong} ({wrong/n*100:.1f}%)")
    print(f"gold_in_pool(제거 검증 결함): {gold_leak}건")
    print(f"lane: {out['lane']} | corpus: {out['corpus_n']}행")
    print(f"저장: exp7b2_lgo_choice_raw.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())