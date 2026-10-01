"""Run H: pool_ids 노출 검증 + 정밀 골든셋 재측정

이제 /v1/prefetch options.pool_ids=true로:
- stage1 풀 ids (RRF 순위)
- JEV rerank 후 final_ids (lift 관찰)

측정:
1. hit@5/MRR on final_ids (JEV rerank 후 실제 최종 순위)
2. JEV lift율: final[0] != pool[0]인 비율
3. 무답 오주입: JEV choice가 무관 후보를 1위로 lift하는가 (관찰용)
"""
import json, os, sys, time
sys.stdout.reconfigure(encoding='utf-8')

JEV = "http://127.0.0.1:47821"
TOKEN = open(os.path.expandvars(r'%LOCALAPPDATA%/jev-mem/token')).read().strip()
import urllib.request, statistics

def prefetch(query, pool_ids=True):
    req = urllib.request.Request(JEV + "/v1/prefetch",
        data=json.dumps({"agent": "golden-eval", "query": query[:8000],
                         "options": {"rerank": True, "max_chars": 0, "pool_ids": pool_ids}}).encode('utf-8'),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))

def main():
    queries = json.load(open('golden_final_v2.json', encoding='utf-8'))
    results = []
    t0 = time.time()
    for i, q in enumerate(queries, 1):
        for axis, qtext in (('literal', q['query_literal']), ('paraphrase', q['query_paraphrase'])):
            if q['cat'] == 'NO_ANSWER' and axis == 'paraphrase':
                continue
            gold = q['id'] if q['cat'] != 'NO_ANSWER' else None
            try:
                r = prefetch(qtext)
                meta = r.get('meta', {})
                pool = meta.get('pool_ids') or []
                final = meta.get('final_ids') or []
                rec = {'gold': gold, 'cat': q['cat'], 'axis': axis, 'query': qtext,
                       'pool_n': len(pool), 'final_n': len(final),
                       'pool_rank': pool.index(gold)+1 if gold in pool else None,
                       'final_rank': final.index(gold)+1 if gold in final else None,
                       'lift': (final and pool and final[0] != pool[0]),
                       'rerank': meta.get('rerank'),
                       'latency_ms': meta.get('latency_ms')}
            except Exception as e:
                rec = {'gold': gold, 'cat': q['cat'], 'axis': axis, 'query': qtext, 'error': repr(e)[:150]}
            results.append(rec)
        if i % 10 == 0:
            print(f"  {i}/{len(queries)} ({time.time()-t0:.0f}s)", flush=True)
    json.dump(results, open('golden_eval_v3.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    ok = [r for r in results if 'error' not in r]
    gold_r = [r for r in ok if r['cat'] != 'NO_ANSWER']
    na = [r for r in ok if r['cat'] == 'NO_ANSWER']
    def pct(x): return f"{100*x:.1f}%"

    print(f"\n=== Run H: pool_ids 정밀 측정 (n={len(gold_r)} + {len(na)} no-answer) ===")
    # JEV rerank 후 최종 지표
    fr = [r for r in gold_r if r['final_rank'] is not None]
    f5 = [r for r in gold_r if r['final_rank'] and r['final_rank'] <= 5]
    mrr = statistics.mean([1/r['final_rank'] for r in fr]) if fr else 0
    print(f"Final hit@5 (rerank 후): {pct(len(f5)/len(gold_r))}")
    print(f"Final MRR: {mrr:.3f}")
    print(f"Final Acc@1: {pct(len([r for r in gold_r if r['final_rank']==1])/len(gold_r))}")
    # stage1 비교
    pr = [r for r in gold_r if r['pool_rank'] is not None]
    p5 = [r for r in gold_r if r['pool_rank'] and r['pool_rank'] <= 5]
    print(f"Pool Recall (참고): {pct(len(pr)/len(gold_r))}, Pool hit@5: {pct(len(p5)/len(gold_r))}")
    # lift
    lifts = [r for r in ok if r.get('lift')]
    print(f"JEV lift 발생율: {pct(len(lifts)/len(ok))} ({len(lifts)}/{len(ok)})")
    # lift가 hit@5에 기여했나
    lift_helped = [r for r in gold_r if r['lift'] and r['pool_rank'] and r['pool_rank'] > 5 and r['final_rank'] and r['final_rank'] <= 5]
    lift_hurt = [r for r in gold_r if r['lift'] and r['pool_rank'] and r['pool_rank'] <= 5 and (r['final_rank'] is None or r['final_rank'] > 5)]
    print(f"lift로 hit5 진입: {len(lift_helped)} / lift로 hit5 이탈: {len(lift_hurt)}")
    # 무답: JEV가 무관 후보를 lift했는가
    na_lift = [r for r in na if r.get('lift')]
    print(f"무답 lift (무관 후보 1위 lift): {len(na_lift)}/{len(na)}")
    lat = sorted(r['latency_ms'] for r in ok if r.get('latency_ms'))
    if lat: print(f"latency p50 {lat[len(lat)//2]}ms / p95 {lat[int(len(lat)*.95)]}ms")

if __name__ == '__main__':
    main()