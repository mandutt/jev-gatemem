"""op-90 하이브리드(lexical BM25 + vec) — gemma2-q8/q4f16 vs bekko, vw 스윕.
S3 방식 그대로: char-level BM25 + vec, 각각 min-max 정규화 후 vw*fused.
측정: 전체 84쿼리 + 고/저오버랩 그룹별 (op90_overlap_decomp 방식 재현).
0콜. 문서 임베딩 1회 (캐시 없음, q8 약 10분).
Usage: python hybrid_op90.py
"""
import os, sys, json, sqlite3, re
import numpy as np

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")
REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden"

sys.path.insert(0, B)
from embgemma2_runner import EmbGemma2Runner

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
items = [(r["q"], r["gold"]) for r in raw["base"] if r["gold"] in id_pos]
print("items:", len(items), flush=True)
queries = [q for q, _ in items]

# BM25 lexical lane
from rank_bm25 import BM25Okapi

def tok_fn(s):
    return [c for c in s.lower() if c.strip()]

bm25 = BM25Okapi([tok_fn(t) for t in texts])
lex_scores = np.array([bm25.get_scores(tok_fn(q)) for q in queries])
lex_norm = np.array([(s - s.min()) / (s.max() - s.min() + 1e-12) for s in lex_scores])

# vec 임베딩
def embed_docs(m, docs, batch=4):
    dv = []
    for i in range(0, len(docs), batch):
        dv.append(np.array(m.embed(docs[i:i + batch], doc=True), dtype=np.float32))
    return np.concatenate(dv, axis=0)

def embed_queries(m, qs, batch=4):
    return np.array(m.embed(qs, batch_size=batch), dtype=np.float32)

def vec_rank_matrix(dn, qv):
    """(nq, nd) cosine 후 min-max 정규화 행렬."""
    sims = dn @ qv.T  # (nd, nq) -> 전치 후 (nq, nd)
    sims = sims.T
    norms = np.array([(r - r.min()) / (r.max() - r.min() + 1e-12) for r in sims])
    return norms

def evaluate(vw, vec_norm, gold_positions, groups):
    """vw 가중 하이브리드 랭킹. groups: {name: [item_idx,...]}"""
    fused = vw * vec_norm + (1 - vw) * lex_norm
    out = {}
    for gname, idxs in groups.items():
        r1 = r5 = 0; mrr = 0.0
        for i in idxs:
            order = np.argsort(-fused[i])
            rank = int(np.where(order == gold_positions[i])[0][0]) + 1
            r1 += rank == 1; r5 += rank <= 5; mrr += 1.0 / rank
        n = len(idxs)
        out[gname] = {"n": n, "hit@1": r1 / n, "hit@5": r5 / n, "MRR": mrr / n}
    return out


# 그룹 정의 (overlap 분해 재현)
def bigrams(s):
    s = re.sub(r"\s+", "", s.lower())
    return set(s[i:i + 2] for i in range(len(s) - 1))

def overlap_ratio(q, gold):
    g = bigrams(gold); qb = bigrams(q)
    return len(qb & g) / len(qb) if qb else 0.0

groups = {"all": list(range(len(items))), "high": [], "low": []}
for i, (q, gid) in enumerate(items):
    (groups["high"] if overlap_ratio(q, id_text[gid]) >= 0.3 else groups["low"]).append(i)
print("groups: all=%d high=%d low=%d" % (len(groups["all"]), len(groups["high"]), len(groups["low"])), flush=True)

gold_positions = [id_pos[g] for _, g in items]

# 모델별 실행
results = {}
for name, mfile in [("gemma2-q8", "model_quantized.onnx"), ("gemma2-q4f16", "model_q4f16.onnx")]:
    print(f"[{name}] 문서 임베딩 시작 ...", flush=True)
    m = EmbGemma2Runner(os.path.join(B, "model-src"), model_file=mfile)
    dn = embed_docs(m, texts)
    dn = dn / (np.linalg.norm(dn, axis=1, keepdims=True) + 1e-12)
    qv = embed_queries(m, queries)
    qv = qv / (np.linalg.norm(qv, axis=1, keepdims=True) + 1e-12)
    vec_norm = vec_rank_matrix(dn, qv)
    results[name] = {"vec_only": evaluate(0.0, vec_norm, gold_positions, groups) if False else None}
    for vw in [0.0, 0.3, 0.5, 0.7, 1.0]:
        key = f"vw{vw}"
        results[name][key] = evaluate(vw, vec_norm, gold_positions, groups)
    print(name, "done", flush=True)

# bekko: fastembed
os.environ["HF_HOME"] = os.path.join(B93, "model-cache")
os.environ["HF_HUB_OFFLINE"] = "1"
sys.path.insert(0, B93)
from fastembed import TextEmbedding
from register_custom import register
register("bench/bekko-a8m")
mb = TextEmbedding(model_name="bench/bekko-a8m", cache_dir=os.path.join(B93, "fe-cache"))
_obj = getattr(mb, "model", mb)
tok = getattr(_obj, "tokenizer", None)
if tok is not None and hasattr(tok, "enable_truncation"):
    tok.enable_truncation(max_length=512)
print("[bekko] 문서 임베딩 ...", flush=True)
dvb = np.array(list(mb.embed(texts, batch_size=4)), dtype=np.float32)
dnb = dvb / (np.linalg.norm(dvb, axis=1, keepdims=True) + 1e-12)
qvb = np.array(list(mb.embed(queries, batch_size=4)), dtype=np.float32)
qnb = qvb / (np.linalg.norm(qvb, axis=1, keepdims=True) + 1e-12)
vec_norm_b = vec_rank_matrix(dnb, qnb)
results["bekko"] = {}
for vw in [0.0, 0.3, 0.5, 0.7, 1.0]:
    results["bekko"][f"vw{vw}"] = evaluate(vw, vec_norm_b, gold_positions, groups)
print("bekko done", flush=True)

print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "vec_only"} for k, v in results.items()}, ensure_ascii=False, indent=2))
with open(os.path.join(B, "hybrid_op90_result.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("HYBRID DONE")