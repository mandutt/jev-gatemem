"""EmbeddingGemma 2 q4f16 vs bekko-a8m vs baseline — gold-50 quality eval.
Same protocol as s3_p3_gold.py (fixed seed 20260930, 20 gold queries, corpus = snapshot
working_memory first 400 rows), plus the 90-query operational golden set if present.
Usage: python gold_eval.py
"""
import os, sys, json, sqlite3, random
import numpy as np

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")

DB = os.path.join(B93, "data", "mnemosyne.db")
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = conn.execute(
    "SELECT id, content FROM working_memory WHERE content IS NOT NULL AND length(content) > 0 ORDER BY id LIMIT 400"
).fetchall()
conn.close()
texts = [r[1] for r in rows]
print("corpus:", len(texts), "docs", flush=True)

rng = random.Random(20260930)
sample = rng.sample(range(len(texts)), 20)
gold = []
for i in sample:
    t = texts[i]
    q = t.split("\n")[0][:80] if "\n" in t else t[:80]
    gold.append((q, i))
print("gold:", len(gold), "queries", flush=True)


def run_gemma2():
    sys.path.insert(0, B)
    from embgemma2_runner import EmbGemma2Runner
    m = EmbGemma2Runner(os.path.join(B, "model-src"))
    qvecs = np.array(m.embed([q for q, _ in gold], batch_size=4), dtype=np.float32)
    dvecs = np.array(m.embed(texts, batch_size=4, doc=True), dtype=np.float32)
    return qvecs, dvecs


def run_fastembed(alias, prefixes=("", "")):
    os.environ["HF_HOME"] = os.path.join(B93, "model-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.path.insert(0, B93)
    from fastembed import TextEmbedding
    if alias == "bench/bekko-a8m":
        from register_custom import register
        register(alias)
    m = TextEmbedding(model_name=alias, cache_dir=os.path.join(B93, "fe-cache"))
    _obj = getattr(m, "model", m)
    tok = getattr(_obj, "tokenizer", None)
    if tok is not None and hasattr(tok, "enable_truncation"):
        tok.enable_truncation(max_length=512)
    pq, pd = prefixes
    qvecs = np.array(list(m.embed([pq + q if pq else q for q, _ in gold], batch_size=4)), dtype=np.float32)
    dvecs = np.array(list(m.embed([pd + t if pd else t for t in texts], batch_size=4)), dtype=np.float32)
    return qvecs, dvecs


def score(qvecs, dvecs):
    dn = dvecs / (np.linalg.norm(dvecs, axis=1, keepdims=True) + 1e-12)
    per = []
    for (q, gi), qv in zip(gold, qvecs):
        qn = qv / (np.linalg.norm(qv) + 1e-12)
        s = dn @ qn
        rank = int(np.where(np.argsort(-s) == gi)[0][0]) + 1
        per.append({"rank": rank, "rr": 1.0 / rank})
    return {
        "recall@1": float(np.mean([1 if p["rank"] <= 1 else 0 for p in per])),
        "recall@5": float(np.mean([1 if p["rank"] <= 5 else 0 for p in per])),
        "recall@10": float(np.mean([1 if p["rank"] <= 10 else 0 for p in per])),
        "MRR": float(np.mean([p["rr"] for p in per])),
        "per_query": per,
    }


results = {}
print("running gemma2 ...", flush=True)
results["gemma2-q4f16"] = score(*run_gemma2())
print("gemma2 ok", flush=True)
print("running bekko ...", flush=True)
results["bench/bekko-a8m"] = score(*run_fastembed("bench/bekko-a8m"))
print("bekko ok", flush=True)
print("running baseline ...", flush=True)
results["baseline"] = score(*run_fastembed("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"))
print("baseline ok", flush=True)

# paired bootstrap CI (MRR deltas) — gemma2 vs bekko
rng_bs = np.random.default_rng(20260930)
def boot(a, b, n=10000):
    a = np.array(a); b = np.array(b)
    m = len(a); ds = []
    for _ in range(n):
        idx = rng_bs.integers(0, m, m)
        ds.append(a[idx].mean() - b[idx].mean())
    ds = np.sort(np.array(ds))
    return float(ds[int(0.025 * n)]), float(ds[int(0.975 * n)])

results["bootstrap_95ci_MRR_delta"] = {
    "gemma2_vs_bekko": boot([p["rr"] for p in results["gemma2-q4f16"]["per_query"]],
                            [p["rr"] for p in results["bench/bekko-a8m"]["per_query"]]),
    "gemma2_vs_baseline": boot([p["rr"] for p in results["gemma2-q4f16"]["per_query"]],
                               [p["rr"] for p in results["baseline"]["per_query"]]),
}
for k in ("gemma2-q4f16", "bench/bekko-a8m", "baseline"):
    agg = {kk: vv for kk, vv in results[k].items() if kk != "per_query"}
    print(k, json.dumps(agg, ensure_ascii=False))
print("CI:", json.dumps(results["bootstrap_95ci_MRR_delta"]))

with open(os.path.join(B, "gold_eval_result.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("GOLD DONE")