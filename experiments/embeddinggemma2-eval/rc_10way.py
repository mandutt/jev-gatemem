"""기계독해 Validation — 400 QA 10-way retrieval: gemma2-q4f16 vs bekko-a8m.

셋업:
- 쿼리  = QA의 question-1 (짧은 질문)
- 문서  = 10개 문단: gold(정답 context) + 9개 distractor(다른 문서의 context)
- 지표  = acc@1 (gold가 코사인 랭킹 1위 비율), MRR
- 문서 풀(고유 gold + 40 distractor) 1회 임베딩 후 인덱싱, 쿼리별 랭킹.

HTML 태그 제거 후 사용. seed 20261007 고정.
Usage: python rc_10way.py
"""
import os, sys, json, glob, re, random
import numpy as np

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")
DATA = r"C:/code/dataset/152.기술과학 문서 기계독해 데이터/01-1.정식개방데이터/Validation/02.라벨링데이터"

rng = random.Random(20261007)
HTML_RE = re.compile(r"<[^>]+>")


def load_all():
    """Validation 전체에서 (context_text, doc_id) 목록 + (question, context_idx) QA 목록."""
    files = glob.glob(os.path.join(DATA, "*", "*.json"))
    contexts = []  # (text, doc_id)
    qas = []       # (question, context_idx)
    for fp in files:
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        ds = d.get("dataset", {})
        doc_id = ds.get("doc_id", os.path.basename(fp))
        for ci in ds.get("context_info", []):
            text = HTML_RE.sub("", ci.get("context", "")).strip()
            if not text:
                continue
            ctx_idx = len(contexts)
            contexts.append((text, doc_id))
            for qa in ci.get("qas", []):
                q = qa.get("question-1") or qa.get("question-2")
                if q:
                    qas.append((q.strip(), ctx_idx))
    return contexts, qas


contexts, qas = load_all()
print("contexts:", len(contexts), "qas:", len(qas), flush=True)

# 400 QA 샘플 (gold context 유일성 유지하며)
rng.shuffle(qas)
sample = qas[:400]
gold_indices = sorted({ci for _, ci in sample})
print("샘플 QA:", len(sample), "고유 gold context:", len(gold_indices), flush=True)

# distractor 풀: gold context와 다른 doc_id의 context 40개
gold_doc_ids = {contexts[ci][1] for ci in gold_indices}
pool = [i for i, (t, did) in enumerate(contexts) if did not in gold_doc_ids]
rng.shuffle(pool)
distractors = pool[:40]
print("distractor 풀:", len(distractors), flush=True)

# 문서 풀: gold + distractor, 인덱스 매핑
doc_items = [contexts[i][0] for i in gold_indices] + [contexts[i][0] for i in distractors]
doc_of = {gi: j for j, gi in enumerate(gold_indices)}
doc_of.update({di: len(gold_indices) + j for j, di in enumerate(distractors)})
print("문서 풀:", len(doc_items), flush=True)

# 10-way 구성: (쿼리, gold_rank_idx)
items = []
for q, ci in sample:
    gold_j = doc_of[ci]
    others = [doc_of[di] for di in distractors if di != ci]
    rng.shuffle(others)
    items.append((q, gold_j, others[:9]))
assert all(len(o) == 9 for _, _, o in items)
print("10-way items:", len(items), flush=True)


def embed_docs_gemma2(m, docs, batch=4):
    dv = []
    for i in range(0, len(docs), batch):
        dv.append(np.array(m.embed(docs[i:i + batch], doc=True), dtype=np.float32))
    return np.concatenate(dv, axis=0)


def run_gemma2():
    sys.path.insert(0, B)
    from embgemma2_runner import EmbGemma2Runner
    m = EmbGemma2Runner(os.path.join(B, "model-src"))
    dn = embed_docs_gemma2(m, doc_items)
    dn = dn / (np.linalg.norm(dn, axis=1, keepdims=True) + 1e-12)
    # 쿼리 벡터 캐시 (같은 질문 반복 최소화)
    qvec_cache = {}
    hits = 0
    rrs = []
    for q, gold_j, others in items:
        if q not in qvec_cache:
            qv = np.array(m.embed([q])[0], dtype=np.float32)
            qvec_cache[q] = qv / (np.linalg.norm(qv) + 1e-12)
        qn = qvec_cache[q]
        cand = [gold_j] + others
        s = dn[cand] @ qn
        rank = int(np.argmax(s)) + 1  # gold의 순위 (1=1위)
        rrs.append(1.0 / rank)
        hits += rank == 1
    return hits, rrs


def run_bekko():
    os.environ["HF_HOME"] = os.path.join(B93, "model-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.path.insert(0, B93)
    from fastembed import TextEmbedding
    from register_custom import register
    register("bench/bekko-a8m")
    m = TextEmbedding(model_name="bench/bekko-a8m", cache_dir=os.path.join(B93, "fe-cache"))
    _obj = getattr(m, "model", m)
    tok = getattr(_obj, "tokenizer", None)
    if tok is not None and hasattr(tok, "enable_truncation"):
        tok.enable_truncation(max_length=512)
    dv = np.array(list(m.embed(doc_items, batch_size=4)), dtype=np.float32)
    dn = dv / (np.linalg.norm(dv, axis=1, keepdims=True) + 1e-12)
    qvec_cache = {}
    hits = 0
    rrs = []
    for q, gold_j, others in items:
        if q not in qvec_cache:
            qv = np.array(list(m.embed([q], batch_size=1))[0], dtype=np.float32)
            qvec_cache[q] = qv / (np.linalg.norm(qv) + 1e-12)
        qn = qvec_cache[q]
        cand = [gold_j] + others
        s = dn[cand] @ qn
        rank = int(np.argmax(s)) + 1
        rrs.append(1.0 / rank)
        hits += rank == 1
    return hits, rrs


results = {}
for name, fn in [("gemma2-q4f16", run_gemma2), ("bench/bekko-a8m", run_bekko)]:
    import time
    t0 = time.time()
    hits, rrs = fn()
    res = {"acc@1": hits / len(items), "MRR": float(np.mean(rrs)),
           "hits": hits, "total": len(items), "elapsed_s": round(time.time() - t0, 1)}
    results[name] = res
    print(name, json.dumps(res, ensure_ascii=False), flush=True)

with open(os.path.join(B, "rc_10way_result.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("RC10 DONE")