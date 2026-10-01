# 정규화 실험 (Run N): 어절 기반 어간 정규화 커버리지 — JEV 0회 오프라인 시뮬
#
# 가설: 현행 _tokenize는 한글을 음절(글자) 단위로 쪼개므로 어미 변형은 이미 흡수되지만,
#       반대로 흔한 글자(는/데/해)가 overlap을 노이즈하게 채움. 어절 기반 + 어미 제거(stemming)
#       정규화로 커버리지/overlap을 계산하면 탈락 9건이 회복되는가? 오답 유입은 없는가?
#
# 비교 대상:
#   A. 현행 (음절 단위, 게이트 (1, 0.0), vec≤2 예외 overlap>=1)
#   B. 어절 토큰 + 조사 제거 + 어미 어간 정규화 커버리지 (동일 게이트 파라미터)
#
import json, os, sys, re, sqlite3
os.chdir("C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall")
for p in list(sys.path):
    if p in ("", ".", os.getcwd()): sys.path.remove(p)
sys.path.insert(0, "C:/Users/mandu/hermes-made/jev-memory-middleware")
sys.stdout.reconfigure(encoding='utf-8')

from mnemosyne.core.beam import BeamMemory
import mnemosyne.core.beam as beam_mod
from gateway import j1_pipeline as j1p

DB = "C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
beam = BeamMemory(session_id='run-n-sim', db_path=DB)
queries = json.load(open('golden_final_v2.json', encoding='utf-8'))
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
id2content = {r[0]: r[1] for r in con.execute("SELECT id, content FROM working_memory")}
id2content.update({r[0]: r[1] for r in con.execute("SELECT id, content FROM episodic_memory")})
con.close()

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
        return {"id": arg, "content": id2content.get(arg, "")} if arg in id2content else None
    return []

# ---------- 정규화 토크나이저 (B안) ----------
_JOSA = re.compile(r'(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만|까지|부터|에게|께|한테|랑|이랑|보다|처럼|마다|조차|밖에|이나|나|이며|이랑)$')
# 어미 어간: 대표 어미 접미만 제거 (공격적 스테밍 X — 하다/되다/이다 계열 + 대표 어미만)
_EOMI = re.compile(
    r'(했는데|하는데|인데|였는데|지만|하지만|하면|되면|했는지|되는지|인지|하는지|하는가|되는가|'
    r'했다|한다|한다|된다|이다|한다|했어|했어요|해요|해줘|하세요|입니다|습니다|ㅂ니다|'
    r'하는|된는|할|된|한|해|돼|여|요|다|게|고|며|며)$')

def ko_stem(word: str) -> str:
    """보수적 어간 추출: 조사 제거 → 대표 어미 제거 (2회 반복). 최소 2자 보존."""
    w = word
    for _ in range(2):
        prev = w
        w = _JOSA.sub('', w)
        if len(w) >= 3:
            w = _EOMI.sub('', w)
        if w == prev or len(w) < 2:
            break
    return w if len(w) >= 2 else word  # 너무 짧아지면 원형 유지

_EWORD = re.compile(r'[가-힣]{2,}|[a-zA-Z][\w.\-/:]*|\d[\d.]*')

def norm_tokens(text: str) -> set:
    c = (text or "").strip()
    if c.upper().startswith(("[USER]", "[ASSISTANT]", "[IDENTITY]")):
        c = c.split("]", 1)[1].strip()
    c = c.lower()
    out = set()
    for m in _EWORD.findall(c):
        w = m
        if re.fullmatch(r'[가-힣]+', w):
            w = ko_stem(w)
        if len(w) > 1 and w not in j1p._STOPWORDS:
            out.add(w)
    return out

# ---------- 게이트 복제 (A/B 동일 구조, 토크나이저만 다름) ----------
from collections import Counter

def gate(rows, query, tokenize, min_distinctive=1, min_coverage=0.30, vec_exempt=2):
    q_tokens = tokenize(query) - j1p._STOPWORDS
    if not q_tokens: return []
    out = []
    for row in rows:
        r = j1p._synthesize_histories(row)
        content = (r.get("content") or "").strip()
        if not content or len(content.split()) <= 1: continue
        if content.upper().startswith(("[ASSISTANT]",)): continue
        overlap = q_tokens & tokenize(content)
        lr = r.get("_lane_ranks") or {}
        vr = lr.get("vec_rank")
        exempt = vr is not None and vr <= vec_exempt and len(overlap) >= 1
        if len(overlap) < min_distinctive and not exempt: continue
        if len(overlap) / len(q_tokens) < min_coverage and not exempt: continue
        out.append(r)
    return out

def gold_rank(rows, gold_content):
    g = " ".join(gold_content.split())
    for i, r in enumerate(rows, 1):
        c = " ".join((r.get("content") or "").split())
        if c == g or (g in c and len(g) > 10): return i
    return None

# ---------- 실행: A/B 두 게이트 + 최종 정렬 재현(_filter_and_rank의 나머지 점수) ----------
saved_tok = j1p._tokenize
results = {'A': {'hit': 0, 'pool_miss': [], 'pool_sizes': []},
           'B': {'hit': 0, 'pool_miss': [], 'pool_sizes': []}}
changed = []
n_q = 0
for q in queries:
    if q['cat'] == 'NO_ANSWER': continue
    n_q += 1
    gold_content = id2content.get(q['id']) or ""
    for axis, qtext in (('literal', q['query_literal']), ('paraphrase', q['query_paraphrase'])):
        pool = j1p.build_lane_pool(recall_raw, qtext)
        rows = list(pool)
        for tag, tokfn in (('A', saved_tok), ('B', norm_tokens)):
            if tag == 'B':
                j1p._tokenize = tokfn  # 내부 게이트도 B 토크나이저 사용하도록 교체
            ranked = j1p._filter_and_rank(list(rows), qtext)
            j1p._tokenize = saved_tok
            rank = gold_rank(ranked, gold_content)
            results[tag]['pool_sizes'].append(len(ranked))
            if rank is not None:
                results[tag]['hit'] += 1
            else:
                results[tag]['pool_miss'].append({'cat': q['cat'], 'axis': axis, 'q': qtext[:40]})

print(f"쿼리 수: {n_q*2} (gold {n_q} × 2축)")
for tag, name in (('A', '현행(음절 단위)'), ('B', '정규화(어절+어간)')):
    r_ = results[tag]
    avg_pool = sum(r_['pool_sizes']) / len(r_['pool_sizes'])
    print(f"{name}: Pool Recall {r_['hit']}/{n_q*2} = {r_['hit']/(n_q*2)*100:.1f}%  avg_pool {avg_pool:.1f}  탈락 {len(r_['pool_miss'])}건")

a_miss = {(m['cat'], m['axis']) for m in results['A']['pool_miss']}
b_miss = {(m['cat'], m['axis']) for m in results['B']['pool_miss']}
recovered = a_miss - b_miss
new_miss = b_miss - a_miss
print(f"\nB에서 회복: {len(recovered)}건 → {sorted(recovered)}")
print(f"B에서 신규 탈락: {len(new_miss)}건 → {sorted(new_miss)}")
print(f"\nB 탈락 {len(b_miss)}건 상세:")
for m in results['B']['pool_miss']:
    print(f"  [{m['cat']}/{m['axis']}] {m['q']}")
