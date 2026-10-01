"""합성 벤치 회귀 스윕 — vec≤2 커버리지 예외의 kodialog/kosgd 영향 (오프라인, JEV 호출 0)

Run J 결정의 잔여 검증: 예외가 kodialog 5-way 풀에 미치는 영향.
- baseline 게이트 vs 예외 게이트로 stage1 풀 재판정 (스크래치 DB, 코퍼스 419)
- 지표: 풀 내 정답 커버(pool hit), hit@1/5/10/40, 평균 풀 크기
- 이탈이 유의미하면 → JEV 실호출로 최종 판정 (소액)

eval_mine.py와 동일 조건 (동일 DB, 동일 쿼리 180) — 회귀 테스트로 커밋 대상.
"""
import json, os, sys, time
os.chdir("C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall")
for p in list(sys.path):
    if p in ("", ".", os.getcwd()): sys.path.remove(p)
sys.path.insert(0, "C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_DB", "C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall/scratch_eval.db")
sys.stdout.reconfigure(encoding='utf-8')

from mnemosyne.core.beam import BeamMemory
import mnemosyne.core.beam as beam_mod
from gateway import j1_pipeline as j1p
from core import j1_engine

DB = "C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall/scratch_eval.db"
beam = BeamMemory(session_id='scratch-eval', db_path=DB)

items = json.load(open('scratch_items.json', encoding='utf-8'))
print(f"쿼리: {len(items)}", flush=True)

def recall_raw(kind, arg, k):
    if kind == "fts":
        return beam_mod._fts_search_working(beam.conn, arg, k=k)
    if kind == "vec":
        emb = beam_mod._embeddings.embed([arg])
        if emb is None or not len(emb): return []
        return beam_mod._wm_vec_search(beam.conn, emb[0], k=k)
    if kind == "imp":
        return j1p._imp_search(beam.conn, k=k)
    if kind == "graph":
        return j1p._graph_lane_search(beam.conn, arg, k=k)
    if kind == "get":
        row = j1_engine.hydration_get(beam, arg)
        return row if isinstance(row, dict) else None
    return []

def gold_id(it):
    """아이템의 정답 텍스트 → DB 행 id"""
    ans = it['answer']
    if isinstance(ans, int):
        # kodialog: candidates[answer_idx], koalpaca/kosgd: pool[answer]
        if 'candidates' in it:
            text = it['candidates'][ans]
        else:
            text = it['pool'][ans]
    else:
        text = ans
    # 콘텐츠 매칭은 나중에 ranked 행 content 비교로
    return text

from gateway.j1_pipeline import _tokenize, _STOPWORDS

def gate_custom(pool, query, use_exemption):
    """예외 토글이 가능한 게이트 재현 (원본 _filter_and_rank 시그니처 유지)"""
    saved = j1p.VEC_RANK_EXEMPT
    if not use_exemption:
        j1p.VEC_RANK_EXEMPT = 0
    # _lane_ranks 부착은 build_lane_pool이 이미 했음 (커밋된 코드)
    rows = j1p._filter_and_rank(list(pool), query)
    j1p.VEC_RANK_EXEMPT = saved
    return rows

def eval_variant(use_exemption, limit=0):
    hits = {1: 0, 5: 10 and 5, 10: 0, 40: 0}
    hits = {1: 0, 5: 0, 10: 0, 40: 0}
    tot, pool_sizes, ranks_all = 0, [], []
    per_item = []
    data = items[:limit] if limit else items
    t0 = time.time()
    for it in data:
        tot += 1
        pool = j1p.build_lane_pool(recall_raw, it['query'])
        rows = gate_custom(pool, it['query'], use_exemption)
        pool_sizes.append(len(rows))
        gold_text = gold_id(it)
        # 정답 행 찾기: content가 gold_text로 시작/포함
        rank = None
        for i, r in enumerate(rows, 1):
            c = " ".join((r.get("content") or "").split())
            g = " ".join(gold_text.split())
            if c == g or (g in c and len(g) > 10) or c == g:
                rank = i; break
        per_item.append({'dataset': it['dataset'], 'rank': rank, 'pool': len(rows)})
        if rank is not None:
            ranks_all.append(rank)
            for k in hits:
                if rank <= k: hits[k] += 1
    el = time.time() - t0
    import statistics
    return {
        'use_exemption': use_exemption, 'n': tot,
        'hits': hits,
        'pool_avg': round(statistics.mean(pool_sizes), 1) if pool_sizes else 0,
        'avg_rank': round(statistics.mean(ranks_all), 2) if ranks_all else None,
        'elapsed_s': round(el, 1),
        'per_item': per_item,
    }

print("baseline 평가 중...", flush=True)
base = eval_variant(False)
print(f"baseline: pool_avg={base['pool_avg']} hit@1={base['hits'][1]}/{base['n']} hit@5={base['hits'][5]} hit@40={base['hits'][40]}", flush=True)
print("예외 적용 평가 중...", flush=True)
exc = eval_variant(True)
print(f"예외:     pool_avg={exc['pool_avg']} hit@1={exc['hits'][1]}/{exc['n']} hit@5={exc['hits'][5]} hit@40={exc['hits'][40]}", flush=True)

# 데이터셋별 비교 + 이탈/회복
from collections import defaultdict
def by_ds(per_item):
    agg = defaultdict(lambda: [0, 0, 0, 0])  # n, hit1, hit5, hit40
    for x in per_item:
        a = agg[x['dataset'].split('/')[0]]
        a[0] += 1
        if x['rank'] == 1: a[1] += 1
        if x['rank'] and x['rank'] <= 5: a[2] += 1
        if x['rank'] and x['rank'] <= 40: a[3] += 1
    return agg

print()
print("=== 데이터셋별 hit@40 (풀 커버) ===")
b, e = by_ds(base['per_item']), by_ds(exc['per_item'])
for ds in sorted(set(list(b.keys()) + list(e.keys()))):
    bb, ee = b[ds], e[ds]
    print(f"  {ds:12}: baseline {bb[3]}/{bb[0]} → 예외 {ee[3]}/{ee[0]}")

# per-item 이탈/회복
recovered, exited = [], []
for xb, xe in zip(base['per_item'], exc['per_item']):
    rb, re_ = xb['rank'], xe['rank']
    if rb is None and re_ is not None:
        recovered.append((xe['dataset'], re_))
    elif rb is not None and re_ is None:
        exited.append((xe['dataset'], rb))
    elif rb is not None and re_ is not None and rb <= 5 and re_ > 5:
        exited.append((xe['dataset'], f"{rb}→{re_}"))
print()
print(f"회복: {len(recovered)}, 이탈/밀림: {len(exited)}")
for d, r in exited[:15]:
    print(f"  이탈 [{d}] {r}")
for d, r in recovered[:10]:
    print(f"  회복 [{d}] rank {r}")

json.dump({'baseline': base, 'exception': exc},
          open('bench_regression_result.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print("\n저장: bench_regression_result.json")