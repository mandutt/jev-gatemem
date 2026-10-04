"""후속 실험 6 — abstain 문구 강화 (leave-gold-out 재측정) (2026-10-04)

사용자 결정: "둘 다: 문구 강화 실측 후 요청서에 반영"

배경: exp7b2에서 leave-gold-out A(choice) 오주입 41.1% (abstain 58.9%만 안전).
→ choice의 abstain 라벨 문구를 강화하면 오주입이 줄어드는지 실측.

문구 변형 3종 (동일 쿼리, leave-gold-out 90건을 3조건에 분할 30건씩):
- BASE  (현행): "If no candidate is usable evidence for answering the question, pick the last option."
- STRICT: "Only pick a candidate that DIRECTLY and FULLY answers the question with concrete evidence.
           Partial relevance, related topics, background context, or memories that merely mention
           the same words are NOT sufficient. If no candidate fully and directly answers,
           you MUST pick the last option (abstain)."
- GATE:  "Rule: a candidate is answerable ONLY if it contains the specific fact/value/rule the
          question asks for. If a candidate only shares the topic, mentions related keywords, or
          gives background, it is NOT an answer. When the question asks for something NOT in the
          candidate list, you MUST abstain by picking the last option."

측정: 각 문구별 leave-gold-out 30건 (무작위 분할, 고정 시드) → abstain 비율 (높을수록 안전).
비용: 90콜 (30×3) FREE 레인.
출력: experiments/operational-golden/data/exp7e_abstain_prompt_raw.json
"""
import json
import os
import sys
import time
import sqlite3
import hashlib
import random
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

PROMPTS = {
    "BASE": (
        "Which candidate memory is the single best evidence for answering the question? "
        "Pick exactly one. Consider directness and specificity. "
        "If no candidate is usable evidence for answering the question, pick the last option."),
    "STRICT": (
        "Which candidate memory is the single best evidence for answering the question? "
        "Only pick a candidate that DIRECTLY and FULLY answers the question with concrete evidence. "
        "Partial relevance, related topics, background context, or memories that merely mention "
        "the same words are NOT sufficient. "
        "If no candidate fully and directly answers, you MUST pick the last option (abstain)."),
    "GATE": (
        "Which candidate memory is the single best evidence for answering the question? "
        "Rule: a candidate is answerable ONLY if it contains the specific fact/value/rule the question asks for. "
        "If a candidate only shares the topic, mentions related keywords, or gives background, "
        "it is NOT an answer. "
        "When the question asks for something NOT in the candidate list, you MUST abstain by picking the last option."),
}
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"
SEED = 42


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


def choice_call(key, query, cands, instr):
    labels = [excerpt(c, 100) or "n/a" for c in cands]
    j_labels = list(labels) + [ABSTAIN_LABEL]
    body = {"model": MODEL, "state": {"question": query, "candidates": []},
            "questions": {"best": {"type": "choice", "instructions": instr,
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
    b = bm.BeamMemory(session_id="exp7e")

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
    print(f"key: len={len(key)} prefix={key[:4]}... | abstain 문구 강화 | 병렬 {WORKERS}", flush=True)

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

    op = json.load(open(os.path.join(DATA, "golden_eval_v2.json"), encoding="utf-8"))
    op_eval = [x for x in op if x.get("gold_id") and x.get("cat") != "NO_ANSWER"]
    print(f"op {len(op_eval)}건 → 3문구에 30건씩 분할 (seed={SEED})", flush=True)

    rng = random.Random(SEED)
    idxs = list(range(len(op_eval)))
    rng.shuffle(idxs)
    split = {name: idxs[i * 30:(i + 1) * 30] for i, name in enumerate(PROMPTS)}

    out = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "abstain-prompt-lgo",
           "corpus_n": len(corpus), "corpus_hash": corp_hash, "seed": SEED, "records": [],
           "lane": {"free": 0, "credit": 0, "unknown": 0}}

    def save():
        json.dump(out, open(os.path.join(DATA, "exp7e_abstain_prompt_raw.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    for name, ii in split.items():
        print(f"\n=== 문구 {name} ({len(ii)}건) ===", flush=True)
        instr = PROMPTS[name]
        for j, k_ in enumerate(ii):
            x = op_eval[k_]
            q = x["query"]
            gold = x["gold_id"]
            try:
                pool = stage1_pool(q, exclude_ids={gold}, k=40)
            except Exception as e:
                out["records"].append({"prompt": name, "qid": x.get("gold_id"), "query": q,
                                       "err": f"pool {type(e).__name__}"})
                save()
                continue
            pool = [p for p in pool if p.get("id") in by_id]
            cands = [c["content"][:MAX_CAND_CHARS] for c in pool][:MAX_CAND]
            if not cands:
                out["records"].append({"prompt": name, "qid": x.get("gold_id"), "query": q, "err": "empty-pool"})
                save()
                continue
            idx, cost, err = choice_call(key, q, cands, instr)
            rec = {"prompt": name, "qid": x.get("gold_id"), "query": q, "gold_removed": gold,
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
            out["records"].append(rec)
            save()
            if (j + 1) % 10 == 0:
                print(f"  {name} {j+1}/{len(ii)}", flush=True)

    rr = [r for r in out["records"] if not r.get("err")]
    print("\n=== abstain 문구 강화 요약 ===")
    for name in PROMPTS:
        sub = [r for r in rr if r["prompt"] == name]
        n = len(sub)
        abst = sum(1 for r in sub if r.get("abstain"))
        wrong = sum(1 for r in sub if r.get("abstain") is False)
        print(f"  {name}: n={n} | abstain(안전)={abst} ({abst/n*100:.1f}%) | 오주입={wrong} ({wrong/n*100:.1f}%)")
    print(f"lane: {out['lane']}")
    print(f"저장: exp7e_abstain_prompt_raw.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())