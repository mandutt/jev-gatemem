"""Analyze abstain_run_O_raw.json — re-report without the pool-empty bug."""
import json, os
from collections import Counter

ROOT = "C:/Users/mandu/hermes-made/jev-memory-middleware"
path = os.path.join(ROOT, "experiments", "operational-golden", "abstain_run_O_raw.json")
results = json.load(open(path, encoding="utf-8"))

# rows without base_cls: pool_error / pool_empty
ok = [r for r in results if "base_cls" in r and "abs_cls" in r]
skipped = [r for r in results if "base_cls" not in r]
print(f"total={len(results)} analyzed={len(ok)} skipped={len(skipped)}")
if skipped:
    for r in skipped[:10]:
        print("  skip:", r.get("cat"), r.get("axis"), r.get("pool_error") or r.get("pool_empty"))

def metrics(subset, key):
    c = Counter(r[key + "_cls"] for r in subset)
    lats = sorted(r[key]["lat_ms"] for r in subset if not r[key].get("error"))
    p = lambda q: lats[int(q * len(lats))] if lats else None
    tok_in = sum((r[key].get("usage") or {}).get("input_tokens") or 0 for r in subset)
    tok_out = sum((r[key].get("usage") or {}).get("output_tokens") or 0 for r in subset)
    return {"counts": dict(c), "n": len(subset), "p50": p(0.50), "p95": p(0.95),
            "tok_in": tok_in, "tok_out": tok_out,
            "errs": sum(1 for r in subset if r[key].get("error"))}

gold_rows = [r for r in ok if r["gold"] is not None]
noa_rows = [r for r in ok if r["gold"] is None]

print("\n=== GOLD queries (n=%d) ===" % len(gold_rows))
print("baseline:", json.dumps(metrics(gold_rows, "base"), ensure_ascii=False))
print("abstain :", json.dumps(metrics(gold_rows, "abs"), ensure_ascii=False))
print("\n=== NO_ANSWER queries (n=%d) ===" % len(noa_rows))
print("baseline:", json.dumps(metrics(noa_rows, "base"), ensure_ascii=False))
print("abstain :", json.dumps(metrics(noa_rows, "abs"), ensure_ascii=False))

print("\n=== pairwise transitions (base_cls -> abs_cls) ===")
for label, subset in (("GOLD", gold_rows), ("NO_ANSWER", noa_rows)):
    trans = Counter((r["base_cls"], r["abs_cls"]) for r in subset)
    for k, v in sorted(trans.items()):
        print(f"  {label}: {k[0]:>8} -> {k[1]:>8} : {v}")

g_base_gold = [r for r in gold_rows if r["base_cls"] == "gold"]
print(f"\nbase gold-picks: {len(g_base_gold)}/{len(gold_rows)}")
if g_base_gold:
    print("  preserved in abstain:", sum(1 for r in g_base_gold if r["abs_cls"] == "gold"))
    print("  flipped to none     :", sum(1 for r in g_base_gold if r["abs_cls"] == "none"))
    print("  flipped to wrong    :", sum(1 for r in g_base_gold if r["abs_cls"] == "wrong"))
    print("  flipped to no_pick  :", sum(1 for r in g_base_gold if r["abs_cls"] == "no_pick"))

w_base = [r for r in gold_rows + noa_rows if r["base_cls"] == "wrong"]
print(f"\nbase wrong-picks: {len(w_base)}")
if w_base:
    print("  -> abstain:", sum(1 for r in w_base if r["abs_cls"] == "none"))
    print("  -> gold   :", sum(1 for r in w_base if r["abs_cls"] == "gold"))
    print("  -> wrong  :", sum(1 for r in w_base if r["abs_cls"] == "wrong"))
    print("  -> no_pick:", sum(1 for r in w_base if r["abs_cls"] == "no_pick"))

# abstain-picked rows: what were they in base?
none_rows = [r for r in gold_rows + noa_rows if r["abs_cls"] == "none"]
print(f"\nabstain picks (abs_cls=none): {len(none_rows)}")
if none_rows:
    print("  base was gold :", sum(1 for r in none_rows if r["base_cls"] == "gold"))
    print("  base was wrong:", sum(1 for r in none_rows if r["base_cls"] == "wrong"))
    print("  base was none :", sum(1 for r in none_rows if r["base_cls"] == "none"))

# token delta on gold rows with both usage
both = [r for r in gold_rows if (r["base"].get("usage") or {}).get("input_tokens")
        and (r["abs"].get("usage") or {}).get("input_tokens")]
if both:
    delta = sum((r["abs"]["usage"]["input_tokens"] - r["base"]["usage"]["input_tokens"]) for r in both)
    print(f"\ntoken input delta (abs - base) over {len(both)} rows: {delta:+d} total, {delta/len(both):+.1f}/row")
    print(f"  base mean input: {sum(r['base']['usage']['input_tokens'] for r in both)/len(both):.0f}")
    print(f"  abs  mean input: {sum(r['abs']['usage']['input_tokens'] for r in both)/len(both):.0f}")
    print(f"  base mean output: {sum(r['base']['usage'].get('output_tokens') or 0 for r in both)/len(both):.0f}")
    print(f"  abs  mean output: {sum(r['abs']['usage'].get('output_tokens') or 0 for r in both)/len(both):.0f}")

# NO_ANSWER detail: which rows abstained
print("\n=== NO_ANSWER per-row ===")
for r in noa_rows:
    print(f"  {r['abs_cls']:>6} | base={r['base_cls']:>6} | {r['query'][:60]}")