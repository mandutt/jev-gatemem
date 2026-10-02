"""Run O — Abstain-choice A/B against baseline choice (direct JEV API, parallel calls).

Compares, per golden query (same pool of 40 candidates):
  - baseline: existing 'best' choice question (no abstain option)
  - abstain:  same, plus an extra c40 = "no candidate is usable evidence" option

Outcome classification per arm:
  - 'gold'    : JEV picked the gold id (lift to correct answer)
  - 'wrong'   : JEV picked a non-gold candidate (lift-to-wrong or confirm-top-wrong)
  - 'none'    : JEV abstained (abstain arm only)
  - 'no_pick' : JEV returned no answer at all
  - 'err'     : HTTP/parse failure (None index)

Metrics:
  - abstain rate on NO_ANSWER queries (target: previously misinjected 4/10 -> abstain)
  - abstain rate on gold queries (false abstention cost)
  - gold-pick rate preservation (baseline vs abstain)
  - wrong-pick reduction
  - token usage delta (usage fields from API response)
  - latency p50/p95 per arm

Does NOT touch the live daemon or DB. JEV API key from repo .env (TYPESAFE_API_KEY).
"""
import json, os, sys, time, threading
from collections import Counter, defaultdict

ROOT = "C:/Users/mandu/hermes-made/jev-memory-middleware"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# ---- API key from repo .env ----
KEY = None
try:
    for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
        line = line.strip()
        if line.startswith("TYPESAFE_API_KEY="):
            KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
except FileNotFoundError:
    pass
KEY = os.environ.get("TYPESAFE_API_KEY") or KEY
assert KEY, "TYPESAFE_API_KEY not found in repo .env or env"

API = os.environ.get("JEV_API_URL") or "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT_S = 20

import urllib.request
import gateway.j1_pipeline as j1p        # build_state, _excerpt, _filter_and_rank
import gateway.gateway as gw             # for stage1? we reuse pipeline builders
from core import j1_engine

# ------------------------------------------------------------------ stage1 pool
# Reuse the operational-golden stage1 pipeline: build_lane_pool + _filter_and_rank.
# We need the same recall_raw used by golden_run.py (works against the live DB read-only).
import mnemosyne.core.beam as bm
from mnemosyne.core import embeddings as emb_mod

_b = None
def get_beam():
    global _b
    if _b is None:
        _b = bm.BeamMemory(session_id="golden-eval-o")
    return _b

def recall_raw(kind, arg, k_):
    b = get_beam()
    if kind == "fts":  return bm._fts_search_working(b.conn, arg, k=k_)
    if kind == "vec":
        e = emb_mod.embed([arg])
        if not e or not len(e): return []
        return bm._wm_vec_search(b.conn, e[0], k=k_)
    if kind == "imp":  return j1p._imp_search(b.conn, k=k_)
    if kind == "graph": return j1p._graph_lane_search(b.conn, arg, k=k_)
    if kind == "get":
        row = j1_engine.hydration_get(b, arg)
        return row if isinstance(row, dict) else None
    return []

def stage1_pool(query, k=40):
    pool = j1p.build_lane_pool(recall_raw, query)
    ranked = j1p._filter_and_rank(pool, query) if pool else []
    return ranked[:k]

# ------------------------------------------------------------------ JEV call
def jev_call(state, questions, label_count):
    body = json.dumps({"state": state, "questions": questions, "model": MODEL}).encode("utf-8")
    req = urllib.request.Request(API, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
        lat = (time.perf_counter() - t0) * 1000
        ans = (data.get("answers") or {}).get("best") or {}
        choice = ans.get("choice")
        idx = int(str(choice).lstrip("c")) if choice is not None else None
        usage = data.get("usage") or {}
        if idx is not None and not (0 <= idx < label_count):
            idx = None  # out of range
        return {"idx": idx, "lat_ms": lat, "usage": usage, "error": None}
    except Exception as exc:
        return {"idx": None, "lat_ms": (time.perf_counter() - t0) * 1000,
                "usage": {}, "error": f"{type(exc).__name__}: {exc}"}

def make_questions_baseline(labels):
    return {"best": {"type": "choice",
        "instructions": ("Which candidate memory is the single best evidence for answering "
                         "the question? Pick exactly one. Consider directness and specificity."),
        "criteria": {f"c{i}": labels[i] for i in range(len(labels))}}}

def make_questions_abstain(labels):
    crit = {f"c{i}": labels[i] for i in range(len(labels))}
    crit[f"c{len(labels)}"] = "No candidate is usable evidence for answering the question"
    return {"best": {"type": "choice",
        "instructions": ("Which candidate memory is the single best evidence for answering "
                         "the question? If none of the candidates contains usable evidence, "
                         "pick the 'no candidate' option. Consider directness and specificity."),
        "criteria": crit}}

# ------------------------------------------------------------------ run
def run():
    queries = json.load(open(os.path.join("experiments", "operational-golden", "data", "golden_final_v2.json"),
                             encoding="utf-8"))
    rows = []
    for q in queries:
        cat = q["cat"]
        if cat == "NO_ANSWER":
            rows.append({"gold": None, "cat": cat, "axis": "literal", "query": q["query_literal"]})
        else:
            rows.append({"gold": q["id"], "cat": cat, "axis": "literal", "query": q["query_literal"]})
            rows.append({"gold": q["id"], "cat": cat, "axis": "paraphrase", "query": q["query_paraphrase"]})

    results = []
    for i, row in enumerate(rows, 1):
        query = row["query"]
        try:
            pool = stage1_pool(query, k=40)
        except Exception as exc:
            results.append({**row, "pool_error": f"{type(exc).__name__}: {exc}", "pool": []})
            continue
        if not pool:
            results.append({**row, "pool_empty": True, "pool": []})
            continue
        state = j1p.build_state(query, pool)
        labels = [j1p._excerpt((c.get("content") or ""), 100) or "n/a" for c in pool]
        gold = row["gold"]
        gold_in_pool = gold in {str(c.get("id", "")) for c in pool}
        gold_pool_rank = next((j + 1 for j, c in enumerate(pool) if str(c.get("id", "")) == gold), None)

        # parallel A/B
        qb = make_questions_baseline(labels)
        qa = make_questions_abstain(labels)
        out = {}
        def call(name, questions, nlab):
            out[name] = jev_call(state, questions, nlab)
        t1 = threading.Thread(target=call, args=("base", qb, len(labels)))
        t2 = threading.Thread(target=call, args=("abs", qa, len(labels) + 1))
        t1.start(); t2.start(); t1.join(); t2.join()

        def classify(arm):
            r = out[arm]
            if r["error"]: return "err"
            idx = r["idx"]
            if idx is None: return "no_pick"
            if arm == "abs" and idx == len(labels): return "none"
            pick_id = str(pool[idx].get("id", "")) if 0 <= idx < len(pool) else "?"
            if gold is None: return "wrong" if idx is not None else "no_pick"  # no gold to match
            if pick_id == gold: return "gold"
            return "wrong"

        res = {**row, "pool": [str(c.get("id", ""))[:12] for c in pool],
               "gold_in_pool": gold_in_pool, "gold_pool_rank": gold_pool_rank,
               "base": out["base"], "abs": out["abs"],
               "base_cls": classify("base"), "abs_cls": classify("abs")}
        results.append(res)
        if i % 20 == 0:
            print(f"  ...{i}/{len(rows)}", flush=True)

    # ------------------------------------------------------------------ report
    out_path = os.path.join("experiments", "operational-golden", "abstain_run_O_raw.json")
    json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"saved: {out_path}")

    def metrics(subset, key):
        c = Counter(r[key + "_cls"] for r in subset)
        lats = [r[key]["lat_ms"] for r in subset if not r[key].get("error")]
        lats.sort()
        p = lambda q: lats[int(q * len(lats))] if lats else None
        tok_in = sum((r[key].get("usage") or {}).get("input_tokens") or 0 for r in subset)
        tok_out = sum((r[key].get("usage") or {}).get("output_tokens") or 0 for r in subset)
        return {"counts": dict(c), "n": len(subset), "p50": p(0.50), "p95": p(0.95),
                "tok_in": tok_in, "tok_out": tok_out, "errs": sum(1 for r in subset if r[key].get("error"))}

    gold_rows = [r for r in results if r["gold"] is not None]
    noa_rows = [r for r in results if r["gold"] is None]

    print("\n=== GOLD queries (n=%d) ===" % len(gold_rows))
    print("baseline:", json.dumps(metrics(gold_rows, "base"), ensure_ascii=False))
    print("abstain :", json.dumps(metrics(gold_rows, "abs"), ensure_ascii=False))
    print("\n=== NO_ANSWER queries (n=%d) ===" % len(noa_rows))
    print("baseline:", json.dumps(metrics(noa_rows, "base"), ensure_ascii=False))
    print("abstain :", json.dumps(metrics(noa_rows, "abs"), ensure_ascii=False))

    # pairwise deltas
    print("\n=== pairwise transitions (base_cls -> abs_cls) ===")
    for label, subset in (("GOLD", gold_rows), ("NO_ANSWER", noa_rows)):
        trans = Counter((r["base_cls"], r["abs_cls"]) for r in subset)
        for k, v in sorted(trans.items()):
            print(f"  {label}: {k[0]:>8} -> {k[1]:>8} : {v}")

    # gold preservation: gold picked in base, what happens in abstain?
    g_base_gold = [r for r in gold_rows if r["base_cls"] == "gold"]
    print(f"\nbase gold-picks: {len(g_base_gold)}/{len(gold_rows)}")
    print("  preserved in abstain:", sum(1 for r in g_base_gold if r["abs_cls"] == "gold"))
    print("  flipped to none     :", sum(1 for r in g_base_gold if r["abs_cls"] == "none"))
    print("  flipped to wrong    :", sum(1 for r in g_base_gold if r["abs_cls"] == "wrong"))

    # wrong picks in base — do they abstain?
    w_base = [r for r in gold_rows + noa_rows if r["base_cls"] == "wrong"]
    print(f"\nbase wrong-picks: {len(w_base)}")
    if w_base:
        print("  -> abstain:", sum(1 for r in w_base if r["abs_cls"] == "none"))
        print("  -> gold   :", sum(1 for r in w_base if r["abs_cls"] == "gold"))
        print("  -> wrong  :", sum(1 for r in w_base if r["abs_cls"] == "wrong"))

    # token delta on the 90 gold (compare same rows where both usage present)
    both = [r for r in gold_rows if (r["base"].get("usage") or {}).get("input_tokens")
            and (r["abs"].get("usage") or {}).get("input_tokens")]
    if both:
        delta = sum((r["abs"]["usage"]["input_tokens"] - r["base"]["usage"]["input_tokens"]) for r in both)
        print(f"\ntoken input delta (abstain - base) over {len(both)} rows: {delta:+d} total, {delta/len(both):+.1f}/row")
        print(f"  base mean input: {sum(r['base']['usage']['input_tokens'] for r in both)/len(both):.0f}")
        print(f"  abs  mean input: {sum(r['abs']['usage']['input_tokens'] for r in both)/len(both):.0f}")

if __name__ == "__main__":
    run()