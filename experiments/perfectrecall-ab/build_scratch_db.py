"""스크래치 DB 재구축 (경량): 코퍼스=후보만, 쿼리는 별도 저장
- kodialogbench: 4서브 × 15아이템 = 60 (쿼리 60, 후보 300)
- koalpaca: 40 / kosgd: 40 / 기계독해: 40 (쿼리+풀)
코퍼스 스팬 ≈ 420, 쿼리 180
"""
import json, os, sys, random, glob
sys.stdout.reconfigure(encoding='utf-8')

DATA = 'C:/code/dataset'
random.seed(42)

def load():
    items = []
    for sub in ['dailydialog', 'empathetic_dialogues', 'personachat', 'socialdial']:
        f = f'{DATA}/260928testdata/kodialogbench/response_selection/{sub}/test.jsonl'
        with open(f, encoding='utf-8') as fh:
            lines = fh.readlines()[:15]
        for line in lines:
            d = json.loads(line)
            ctx = ' '.join(t for _, t in d['dialogue'][-6:])
            items.append({'dataset': f'kodialog/{sub}', 'query': ctx,
                          'candidates': d['options'], 'answer': d['answer_idx']})
    pairs = []
    with open(f'{DATA}/260928testdata/koalpaca/KoAlpaca_v1.1.jsonl', encoding='utf-8') as fh:
        for line in fh:
            d = json.loads(line)
            if d.get('instruction') and d.get('output'):
                pairs.append((d['instruction'], d['output']))
    random.shuffle(pairs)
    pairs = pairs[:40]
    pool = [p[1] for p in pairs]
    for i, (q, _) in enumerate(pairs):
        items.append({'dataset': 'koalpaca', 'query': q, 'pool': pool, 'answer': i})
    pairs = []
    for f in sorted(glob.glob(f'{DATA}/260928testdata/kosgd/data/test/dialogues_*.json'))[:10]:
        with open(f, encoding='utf-8') as fh:
            dialogues = json.load(fh)
        for dlg in dialogues:
            turns = dlg['turns']
            for i in range(1, len(turns)):
                ctx = ' '.join(t['utterance'] for t in turns[max(0, i - 4):i])
                pairs.append((ctx, turns[i]['utterance']))
    random.shuffle(pairs)
    pairs = pairs[:40]
    pool = [p[1] for p in pairs]
    for i, (q, _) in enumerate(pairs):
        items.append({'dataset': 'kosgd', 'query': q, 'pool': pool, 'answer': i})
    docs = []
    base = f'{DATA}/152.기술과학 문서 기계독해 데이터/01-1.정식개방데이터/Training/01.원천데이터/TS_생명_LA'
    for f in sorted(glob.glob(base + '/*.json')):
        if len(docs) >= 40:
            break
        try:
            d = json.load(open(f, encoding='utf-8'))
            for ci in d['dataset']['context_info']:
                txt = ci.get('context', '')
                if len(txt) > 200:
                    docs.append(txt)
                    break
        except Exception:
            continue
    docs = docs[:40]
    for i, t in enumerate(docs):
        items.append({'dataset': 'machinereading', 'query': t[:200], 'pool': docs, 'answer': i})
    return items

def main(out_db):
    items = load()
    print(f'아이템: {len(items)}')
    corpus = []
    for it in items:
        corpus.extend(it['pool'] if 'pool' in it else it['candidates'])
    corpus = list(dict.fromkeys(corpus))
    print(f'코퍼스 고유 스팬: {len(corpus)}')
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'perfectrecall'))
    from mnemosyne.core.beam import BeamMemory
    for p in ([out_db] + [out_db + s for s in ('-wal', '-shm')]):
        if os.path.exists(p):
            os.remove(p)
    beam = BeamMemory(session_id='scratch-eval', db_path=out_db)
    for t in corpus:
        beam.remember(content=t, source='scratch-eval', importance=0.5, scope='global')
    print(f'적재 완료 → {out_db} ({len(corpus)} 스팬)')
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'scratch_items.json'), 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False)
    print('아이템 저장: scratch_items.json')

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'scratch_eval.db')