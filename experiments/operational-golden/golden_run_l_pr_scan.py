"""Run L: PerfectRecall 방식(전체 코퍼스 JEV relevance 스캔)을 운영 골든셋에 적용

- 운영 라이브 DB (mnemosyne.db) 전체 working+episodic 메모리를 코퍼스로
- golden_final_v2.json 90 gold 쿼리 + 무답 10 (Run J/H와 동일 조건)
- jev_recall._rank로 전체 스캔 → 정답 순위 측정
- 비교 대상: Run J (우리 파이프라인, 풀 40 + choice 1회)

주의: production DB 읽기 전용. JEV 실호출 발생 (사용자 승인됨 — 운영 골든셋 재사용).
"""
import json, os, sys, time, statistics
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'C:/Users/mandu/hermes-made/jev-memory-middleware')

# 운영 DB를 코퍼스로 — BeamMemory는 쓰기 없이 읽기만 사용
DB = 'C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db'
os.environ['MNEMOSYNE_JEV_PROVIDER'] = 'typesafe'
KEY = os.environ.get('TYPESAFE_API_KEY', '')
if not KEY:
    import re
    for p in ('%LOCALAPPDATA%/jev-mem/.env', '%LOCALAPPDATA%/jev-mem/bench/run-20261001-s4/.env'):
        pp = os.path.expandvars(p)
        if os.path.exists(pp):
            for line in open(pp, encoding='utf-8'):
                m = re.match(r'\s*TYPESAFE_API_KEY\s*=\s*(.+)', line)
                if m:
                    KEY = m.group(1).strip().strip('"\''); break
        if KEY: break
os.environ['TYPESAFE_API_KEY'] = KEY
print('KEY:', 'OK' if KEY else 'FAIL', flush=True)

from mnemosyne.core import jev, jev_recall
from mnemosyne.core.beam import BeamMemory

beam = BeamMemory(session_id='run-l-pr-scan', db_path=DB)
rows = list(jev_recall.visible_memories(beam, jev_recall._filters(cross_session=True)))
print(f'코퍼스: {len(rows)} 스팬', flush=True)

queries = json.load(open('golden_final_v2.json', encoding='utf-8'))
print(f'골든셋: {len(queries)} 항목', flush=True)

results = []
t0_all = time.monotonic()
for i, q in enumerate(queries, 1):
    gold = q['id'] if q['cat'] != 'NO_ANSWER' else None
    for axis, qtext in (('literal', q['query_literal']), ('paraphrase', q['query_paraphrase'])):
        if q['cat'] == 'NO_ANSWER' and axis == 'paraphrase':
            continue
        t0 = time.monotonic()
        try:
            ranked, scanned = jev_recall._rank(qtext, rows, threshold=0.0)
            # ranked는 content 기반 → gold id로 역매핑 필요. rows의 content→id
            content_map = {r['content']: r for r in rows}
            # ranked 원소에 score 붙음. gold content 찾기
            gold_row = next((r for r in rows if r.get('id') == gold), None)
            rank = None
            top_score = None
            if gold_row:
                gm = {r['content']: r.get('score') for r in ranked}
                gs = gm.get(gold_row['content'])
                if gs is not None:
                    # 정답 점수의 순위 = 자기보다 점수 높은 것 수 +1 (동점 처리: PR 스캔 순서 우선)
                    higher = sum(1 for r in ranked if r.get('score', 0) > gs)
                    rank = higher + 1
                    top_score = ranked[0].get('score') if ranked else None
            rec = {'gold': gold, 'cat': q['cat'], 'axis': axis,
                   'rank': rank, 'gold_score': gs if gold_row else None,
                   'top_score': top_score, 'latency_ms': int((time.monotonic()-t0)*1000)}
        except Exception as e:
            rec = {'gold': gold, 'cat': q['cat'], 'axis': axis, 'error': repr(e)[:200]}
        results.append(rec)
    if i % 10 == 0:
        done = [r for r in results if 'error' not in r]
        ok = sum(1 for r in done if r.get('rank') == 1)
        print(f'  {i}/{len(queries)} acc@1={ok}/{len(done)} ({time.monotonic()-t0_all:.0f}s)', flush=True)

json.dump(results, open('golden_eval_runL_pr_scan.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

ok = [r for r in results if 'error' not in r]
gold_r = [r for r in ok if r['cat'] != 'NO_ANSWER']
na = [r for r in ok if r['cat'] == 'NO_ANSWER']
def pct(x, d): return f"{100*x/d:.1f}%"
a1 = sum(1 for r in gold_r if r.get('rank') == 1)
h5 = sum(1 for r in gold_r if r.get('rank') and r['rank'] <= 5)
covered = sum(1 for r in gold_r if r.get('rank') is not None)
mrr = statistics.mean([1/r['rank'] for r in gold_r if r.get('rank')])
lats = [r['latency_ms'] for r in ok]
m = jev.client().metrics
print(f"\n=== Run L: PR 전체 스캔 × 운영 골든셋 (코퍼스 {len(rows)}) ===")
print(f"커버리지(정답 점수>0): {pct(covered, len(gold_r))}")
print(f"Acc@1: {pct(a1, len(gold_r))} ({a1}/{len(gold_r)})")
print(f"hit@5: {pct(h5, len(gold_r))}")
print(f"MRR: {mrr:.3f}")
print(f"무답 10: 상위 1위 판정 {sum(1 for r in na if r.get('top_score') is not None)} — top_score 존재=JEV가 무관 후보에 점수 부여")
print(f"지연 p50/p95: {statistics.median(lats):.0f}/{sorted(lats)[int(len(lats)*0.95)]:.0f}ms")
print(f"JEV: {m.get('requests')} 요청 / 실패 {m.get('failures')} / $ {m.get('cost_usd')}")
