# -*- coding: utf-8 -*-
# artifact 매치 원인 없는 2건: 어떤 패턴이 artifact로 만들었는지
import sys, re, sqlite3
sys.path.insert(0, r'C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages')
import mnemosyne.core.typed_memory as tm
from mnemosyne.core.typed_memory import classify_memory

DB = r'C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db'
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
ids = ['0ba9505950731a52', '1b798c109b05601d']
for mid in ids:
    row = con.execute('SELECT content FROM working_memory WHERE id=?', (mid,)).fetchone()
    s = row[0]
    text = s.lower()
    print('=' * 72)
    print(f'[{mid}]', s[:60].replace('\n', ' '))
    m = classify_memory(s)
    print('  =>', m.memory_type.value)
    # 전체 텍스트에서 artifact로 분류하게 만든 패턴 (score 계산 포함)
    import mnemosyne.core.typed_memory as tmc
    # classify_memory가 내부적으로 사용하는 함수 재현
    best = None
    for pat, mtype, conf, prio in tm._EN_PATTERNS:
        if re.search(pat, text):
            idx = list(tm.MemoryType).index(mtype)
            score = conf * (1.0 + 0.1 * idx)
            if best is None or score > best[2]:
                best = (pat, mtype, score, conf)
    if best:
        p, mt, sc, cf = best
        mm = re.search(p, text)
        print(f'  BEST: {p[:70]!r} -> {mt.value} score={sc:.3f} conf={cf}')
        print(f'  MATCH: ...{text[max(0,mm.start()-20):mm.end()+20]}...')
    else:
        print('  EN 매치 없음 (KO 어미?)')
        for ending, mtype, conf, prio in getattr(tm, '_KO_ENDINGS', []):
            if re.search(ending, text):
                print(f'  KO: {ending[:60]!r} -> {mtype.value} conf={conf}')