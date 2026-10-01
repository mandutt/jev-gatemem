"""X2 확장: 외부 데이터셋 4종에서 a8m vs baseline 비교 평가 (모델 1개씩 실행)

프로토콜:
- kodialogbench (4 서브코퍼스 × 300 = 1,200): 대화맥락 → 응답 5지선다 (X1 프로토콜 재현)
- koalpaca (500×2=1,000 텍스트): instruction → output 풀검색(500 후보)
- kosgd (500×2): 직전 4턴 맥락 → 다음 발화 풀검색(500 후보)
- 기계독해 (300×2): 문서 오프닝 200자 → 문서 풀검색(300 후보)

측정: Accuracy@1 / MRR, 임베딩 처리량, 프로세스 메모리(Private Commit / WS, Win32 API)
사용: python embed_dataset_eval2.py <model_alias>
"""
import time, json, os, sys, glob, random
import ctypes, ctypes.wintypes

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
random.seed(42)

from mnemosyne.core.embeddings import TextEmbedding
import numpy as np

DATA = 'C:/code/dataset'
MODEL = sys.argv[1] if len(sys.argv) > 1 else 'bench/bekko-a8m'
LABEL = sys.argv[2] if len(sys.argv) > 2 else 'a8m'


def get_mem():
    """Win32 GetProcessMemoryInfo — psutil 없이 Private Commit/WS 조회"""
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD),
            ("PageFaultCount", ctypes.wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]
    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    hproc = ctypes.windll.kernel32.GetCurrentProcess()
    psapi = ctypes.WinDLL('psapi')
    fn = psapi.GetProcessMemoryInfo
    fn.restype = ctypes.wintypes.BOOL
    fn.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), ctypes.wintypes.DWORD]
    ok = fn(hproc, ctypes.byref(pmc), pmc.cb)
    if not ok:
        return {'private_mb': -1.0, 'ws_mb': -1.0, 'peak_ws_mb': -1.0}
    return {'private_mb': round(pmc.PagefileUsage / 1048576, 1),
            'ws_mb': round(pmc.WorkingSetSize / 1048576, 1),
            'peak_ws_mb': round(pmc.PeakWorkingSetSize / 1048576, 1)}


# ── 데이터셋 로더 ──────────────────────────────────────────────────────────────
def load_kodialogbench(n_per=300):
    items = []
    for sub in ['dailydialog', 'empathetic_dialogues', 'personachat', 'socialdial']:
        f = f'{DATA}/260928testdata/kodialogbench/response_selection/{sub}/test.jsonl'
        with open(f, encoding='utf-8') as fh:
            lines = fh.readlines()[:n_per]
        for line in lines:
            d = json.loads(line)
            ctx = ' '.join(t for _, t in d['dialogue'][-6:])
            items.append({'dataset': f'kodialog/{sub}', 'query': ctx,
                          'candidates': d['options'], 'answer': d['answer_idx'], 'mode': 'choice'})
    return items


def load_koalpaca(n=500):
    pairs = []
    f = f'{DATA}/260928testdata/koalpaca/KoAlpaca_v1.1.jsonl'
    with open(f, encoding='utf-8') as fh:
        for line in fh:
            d = json.loads(line)
            if d.get('instruction') and d.get('output'):
                pairs.append((d['instruction'], d['output']))
    random.shuffle(pairs)
    pairs = pairs[:n]
    pool = [p[1] for p in pairs]
    return [{'dataset': 'koalpaca', 'query': q, 'pool': pool, 'answer': i, 'mode': 'pool'}
            for i, (q, _) in enumerate(pairs)]


def load_kosgd(n=500):
    pairs = []
    for f in sorted(glob.glob(f'{DATA}/260928testdata/kosgd/data/test/dialogues_*.json'))[:10]:
        with open(f, encoding='utf-8') as fh:
            dialogues = json.load(fh)
        for dlg in dialogues:
            turns = dlg['turns']
            for i in range(1, len(turns)):
                if len(turns) >= 2:
                    ctx = ' '.join(t['utterance'] for t in turns[max(0, i - 4):i])
                    pairs.append((ctx, turns[i]['utterance']))
    random.shuffle(pairs)
    pairs = pairs[:n]
    pool = [p[1] for p in pairs]
    return [{'dataset': 'kosgd', 'query': q, 'pool': pool, 'answer': i, 'mode': 'pool'}
            for i, (q, _) in enumerate(pairs)]


def load_machinereading(n=300):
    docs = []
    base = f'{DATA}/152.기술과학 문서 기계독해 데이터/01-1.정식개방데이터/Training/01.원천데이터/TS_생명_LA'
    for f in sorted(glob.glob(base + '/*.json')):
        if len(docs) >= n:
            break
        try:
            d = json.load(open(f, encoding='utf-8'))
            for ci in d['dataset']['context_info']:
                txt = ci.get('context', '')
                if len(txt) > 200:
                    docs.append(txt)
                    break  # 파일당 1건
        except Exception:
            continue
    docs = docs[:n]
    return [{'dataset': 'machinereading', 'query': t[:200], 'pool': docs, 'answer': i, 'mode': 'pool'}
            for i, t in enumerate(docs)]


# ── 임베딩 + 평가 ─────────────────────────────────────────────────────────────
def embed_all(emb, texts, batch=32):
    vecs = []
    for i in range(0, len(texts), batch):
        for v in emb.embed(texts[i:i + batch]):
            arr = np.asarray(v, dtype=np.float32)
            n = np.linalg.norm(arr)
            vecs.append(arr / (n + 1e-9))
    return np.stack(vecs)


def eval_choice(mat_q, mat_c, items):
    """5지선다: 각 아이템 후보 슬라이스, 보정된 코사인"""
    hits, mrr, qi, ci = 0, 0.0, 0, 0
    for it in items:
        k = len(it['candidates'])
        sims = (mat_c[ci:ci + k] @ mat_q[qi]).ravel()
        rank = int(np.where(np.argsort(-sims) == it['answer'])[0][0]) + 1
        if rank == 1:
            hits += 1
        mrr += 1.0 / rank
        qi += 1
        ci += k
    return hits / len(items), mrr / len(items)


def main():
    m0 = get_mem()
    print(f'[{LABEL}] start mem: {m0}')
    t0 = time.monotonic()
    emb = TextEmbedding(model_name=MODEL)
    t_load = time.monotonic() - t0
    m1 = get_mem()
    print(f'[{LABEL}] load={t_load:.1f}s mem(after load): {m1}')

    for ds in ['kodialogbench', 'koalpaca', 'kosgd', 'machinereading']:
        pass  # 데이터셋 로드는 main 하단에서 일괄

    # 데이터 로드
    dsets = {
        'kodialogbench': load_kodialogbench(),
        'koalpaca': load_koalpaca(),
        'kosgd': load_kosgd(),
        'machinereading': load_machinereading(),
    }

    results = {}
    t_start = time.monotonic()
    total_texts = 0
    for name, items in dsets.items():
        t_ds = time.monotonic()
        if items[0]['mode'] == 'choice':
            q_texts = [it['query'] for it in items]
            c_texts = [c for it in items for c in it['candidates']]
            mq = embed_all(emb, q_texts)
            mc = embed_all(emb, c_texts)
            acc, mrr = eval_choice(mq, mc, items)
            n = len(items)
        else:
            q_texts = [it['query'] for it in items]
            pool = items[0]['pool']
            mq = embed_all(emb, q_texts)
            mp = embed_all(emb, pool)
            sims = mq @ mp.T  # (n_q, n_pool)
            ranks = np.argsort(-sims, axis=1)
            acc = float(np.mean([ranks[i, 0] == items[i]['answer'] for i in range(len(items))]))
            mrr = float(np.mean([1.0 / (int(np.where(ranks[i] == items[i]['answer'])[0][0]) + 1) for i in range(len(items))]))
            n = len(items)
        total_texts += len(q_texts) + (len(pool) if items[0]['mode'] == 'pool' else sum(len(it['candidates']) for it in items))
        t_used = time.monotonic() - t_ds
        results[name] = {'n': n, 'acc1': round(acc, 4), 'mrr': round(mrr, 4),
                         's': round(t_used, 1), 'mode': items[0]['mode']}
        print(f'[{LABEL}] {name}: n={n} Acc@1={acc:.4f} MRR={mrr:.4f} ({t_used:.1f}s)')

    # kodialogbench 서브코퍼스별
    kd = [it for it in dsets['kodialogbench']]
    sub_res = {}
    for sub in sorted({it['dataset'] for it in kd}):
        items = [it for it in kd if it['dataset'] == sub]
        q_texts = [it['query'] for it in items]
        c_texts = [c for it in items for c in it['candidates']]
        mq = embed_all(emb, q_texts)
        mc = embed_all(emb, c_texts)
        acc, mrr = eval_choice(mq, mc, items)
        sub_res[sub] = {'acc1': round(acc, 4), 'mrr': round(mrr, 4)}
        print(f'[{LABEL}] {sub}: Acc@1={acc:.4f} MRR={mrr:.4f}')

    t_total = time.monotonic() - t_start
    m2 = get_mem()
    out = {'model': MODEL, 'label': LABEL, 'load_s': round(t_load, 1),
           'mem_start': m0, 'mem_after_load': m1, 'mem_end': m2,
           'total_texts': total_texts, 'embed_total_s': round(t_total, 1),
           'throughput': round(total_texts / t_total, 1) if t_total > 0 else 0,
           'results': results, 'kodialog_sub': sub_res}
    with open(f'experiments/embed_dataset_eval_{LABEL}.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'FINAL_JSON_{LABEL}: {json.dumps({k: out[k] for k in ["model","load_s","mem_start","mem_after_load","mem_end","total_texts","embed_total_s","throughput"]}, ensure_ascii=False)}')


if __name__ == '__main__':
    main()