"""무료 레버 ① — excerpt 길이별 JEV state 토큰 실측 (JEV 호출 0회, 라이브 DB)

R5 §4-4 "후보 텍스트 절단(150~200자) 시 토큰 절감" 실측.
현재 _excerpt=120. 후보 120/160/200/300/400/500자 시의 state 토큰을
tiktoken이 아닌 실측 근사(한글 1자≈1토큰, 영문 4자≈1토큰 근사 대신
정확 비교를 위해 문자수 기준 상대비 + JEV 실제 청구는 문자 기반이므로
문자수로 보고)로 계산. golden_runJ의 pool 40 기준.

추가로: 절단이 정답 판별력을 해치는지 — 120자 절단 시 gold 내용이
잘려나가는지 라이브 DB에서 확인 (gold 메모리 45건의 실제 길이).
"""
import json, sqlite3, os, sys
os.chdir("C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall")
sys.stdout.reconfigure(encoding='utf-8')

res = json.load(open('golden_eval_runJ.json', encoding='utf-8'))
DB = 'C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db'
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)

# Run J의 gold 45건 (무답 10 제외, axis literal 기준으로 유니크)
golds = []
seen = set()
for r in res:
    if r.get('pool_n') and r['gold'] not in seen:
        golds.append(r['gold']); seen.add(r['gold'])
print(f"gold 메모리: {len(golds)}")

rows = {r[0]: r[1] for r in con.execute("SELECT id, content FROM working_memory")}
# gold id가 어떤 테이블인지 확인
found = [g for g in golds if g in rows]
print(f"working_memory에서 발견: {len(found)}")
if len(found) < len(golds):
    rows_ep = {r[0]: r[1] for r in con.execute("SELECT id, content FROM episodic_memory")}
    found2 = [g for g in golds if g in rows_ep]
    print(f"episodic에서 발견: {len(found2)}")
    allrows = {**rows, **rows_ep}
else:
    allrows = rows

# 1) gold 콘텐츠 길이 — 절단이 gold를 자르는가
gold_lens = sorted(len(allrows.get(g, '')) for g in golds if g in allrows)
if gold_lens:
    import statistics
    print(f"\ngold 콘텐츠 길이: median={statistics.median(gold_lens)}, p75={gold_lens[int(len(gold_lens)*0.75)]}, p90={gold_lens[int(len(gold_lens)*0.9)]}, max={gold_lens[-1]}")
    for limit in (120, 160, 200, 300, 500):
        cut = sum(1 for L in gold_lens if L > limit)
        print(f"  >{limit}자 잘림: {cut}/{len(gold_lens)} ({cut/len(gold_lens)*100:.0f}%)")

# 2) JEV state 문자수 시뮬레이션: pool 40 × excerpt 길이
# Run J 평균 pool_n
pool_ns = [r['pool_n'] for r in res if r.get('pool_n')]
avg_pool = sum(pool_ns) / len(pool_ns)
print(f"\n평균 pool_n: {avg_pool:.1f}")
# 운영 DB 콘텐츠 길이 분포로 풀 샘플 근사: 무작위 40행 추출 문자수
import random
random.seed(42)
all_lens = [len(v) for v in allrows.values()]
def sim_chars(limit, n_items=40, n_sims=200):
    tot = 0
    for _ in range(n_sims):
        s = 0
        for _ in range(n_items):
            L = random.choice(all_lens)
            s += min(L, limit)
        tot += s
    return tot / n_sims
base = sim_chars(120)
print("\nexcerpt 한도별 JEV state 문자수 (pool 40 기준, 200회 시뮬):")
for limit in (120, 160, 200, 300, 500, 10000):
    c = sim_chars(limit)
    print(f"  {limit:>5}자: {c:8.0f}자  ({(c-base)/base*100:+.1f}% vs 현행 120)")
con.close()
