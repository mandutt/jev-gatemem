# -*- coding: utf-8 -*-
# TYPE_PATTERNS (99개) 전체에서 artifact 매치 원인 찾기
import sys, re, sqlite3
sys.path.insert(0, r'C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages')
import mnemosyne.core.typed_memory as tm
from mnemosyne.core.typed_memory import classify_memory, MemoryType

DB = r'C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db'
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
ids = ['0ba9505950731a52', '1b798c109b05601d']
for mid in ids:
    row = con.execute('SELECT content FROM working_memory WHERE id=?', (mid,)).fetchone()
    s = row[0]
    text = s.lower()
    print('=' * 72)
    print(f'[{mid}]', s[:50].replace('\n', ' '))
    m = classify_memory(s)
    print('  =>', m.memory_type.value, 'conf=', m.confidence, 'matched=', m.matched_pattern[:60] if m.matched_pattern else None)
    # 전체 패턴 매치 + score
    best = []
    for pat, mtype, conf, prio in tm.TYPE_PATTERNS:
        mm = re.search(pat, text)
        if mm:
            mlen = len(mm.group(0))
            c = conf + (0.1 if mlen > 20 else 0.05 if mlen > 10 else 0)
            idx = list(MemoryType).index(mtype)
            score = c * (1.0 + 0.1 * idx)
            best.append((score, mtype.value, c, pat[:60], mm.start()))
    best.sort(reverse=True)
    for sc, t, c, p, st in best[:6]:
        print(f'  score={sc:.3f} {t:6s} conf={c:.2f} @{st} {p!r}')