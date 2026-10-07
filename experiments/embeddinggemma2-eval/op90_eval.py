"""Operational golden (op-90) retrieval eval — gemma2-q4f16 vs bekko-a8m.
Queries + gold memory ids from stage54_op90_regress.json (90 unique).
Gold text = working_memory row with that id (snapshot DB).
Metrics: gold rank in vec-only cosine ranking over the snapshot corpus (first N rows
or all rows); hit@1/@5/@10, MRR. Same protocol lineage as S3 gold eval.
Usage: python op90_eval.py
"""
import os, sys, json, sqlite3
import numpy as np

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")
REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden"

DB = os.path.join(B93, "data", "mnemosyne.db")
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = conn.execute(
    "SELECT id, content FROM working_memory WHERE content IS NOT NULL AND length(content) > 0 ORDER BY id"
).fetchall()
conn.close()
id_text = {r[0]: r[1] for r in rows}
all_ids = [r[0] for r in rows]
texts = [r[1] for r in rows]
id_pos = {mid: i for i, mid in enumerate(all_ids)}
print("corpus:", len(texts), flush=True)

raw = json.load(open(os.path.join(REPO, "data", "stage54_op90_regress.json"), encoding="utf-8"))
items = [(r["q"], r["gold"]) for r in raw["base"]]
items = [(q, g) for q, g in items if g in id_pos]
print("valid op-90 items:", len(items), flush=True)


def run_gemma2():
    sys.path.insert(0, B)
    from embgemma2_runner import EmbGemma2Runner
    m = EmbGemma2Runner(os.path.join(B, "model-src"))
    dvecs = np.array(m.embed(texts, batch_size=4, doc=True), dtype=np.float32)
    dn = dvecs / (np.linalg.norm(dvecs, axis=1, keepdims=True) + 1e-12)
    per = []
    for q, g in items:
        qv = np.array(m.embed([q], batch_size=1)[0], dtype=np.float32)
        qn = qv / (np.linalg.norm(qv) + 1e-12)
        s = dn @ qn
        rank = int(np.where(np.argsort(-s) == id_pos[g])[0][0]) + 1
        per.append({"rank": rank, "rr": 1.0 / rank})
    return per


def run_fastembed(alias):
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
    dvecs = np.array(list(m.embed(texts, batch_size=4)), dtype=np.float32)
    dn = dvecs / (np.linalg.norm(dvecs, axis=1, keepdims=True) + 1e-12)
    per = []
    for q, g in items:
        qv = np.array(list(m.embed([q], batch_size=1))[0], dtype=np.float32)
        qn = qv / (np.linalg.norm(qv) + 1e-12)
        s = dn @ qn
        rank = int(np.where(np.argsort(-s) == id_pos[g])[0][0]) + 1
        per.append({"rank": rank, "rr": 1.0 / rank})
    return per


def agg(per):
    return {
        "hit@1": float(np.mean([1 if p["rank"] <= 1 else 0 for p in per])),
        "hit@5": float(np.mean([1 if p["rank"] <= 5 else 0 for p in per])),
        "hit@10": float(np.mean([1 if p["rank"] <= 10 else 0 for p in per])),
        "MRR": float(np.mean([p["rr"] for p in per])),
    }


print("running gemma2 ...", flush=True)
per_g = run_gemma2()
print("gemma2 done", flush=True)
print("running bekko ...", flush=True)
per_b = run_fastembed("bench/bekko-a8m")
print("bekko done", flush=True)

results = {
    "gemma2-q4f16": agg(per_g),
    "bench/bekko-a8m": agg(per_b),
    "n": len(items),
    "per_query": {i: {"gemma2": p1["rank"], "bekko": p2["rank"]}
                  for i, (p1, p2) in enumerate(zip(per_g, per_b))},
}
print(json.dumps({k: v for k, v in results.items() if k != "per_query"}, indent=2, ensure_ascii=False))
# rank-1 flip 대조
flips = [i for i, (p1, p2) in enumerate(zip(per_g, per_b)) if (p1["rank"] <= 1) != (p2["rank"] <= 1)]
print("rank-1 flips:", len(flips), flips[:20])
with open(os.path.join(B, "op90_result.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("OP90 DONE")