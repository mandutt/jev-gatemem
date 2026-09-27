# -*- coding: utf-8 -*-
# 8건 변경의 정확한 매치 위치(span) 출력
import sys, re, sqlite3
sys.path.insert(0, r'C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages')
import mnemosyne.core.typed_memory as tm
from mnemosyne.core.typed_memory import classify_memory

DB = r'C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db'
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
ids = ['c19e6287defe1544', 'e27ce1a2593d2483', 'd148ce2e62524f1f',
       '0a8e1d6bb208cbe7', '0ba9505950731a52', '1b798c109b05601d',
       'f5f85146e2e46356', 'c6fe48b1f7d67397']

for mid in ids:
    row = con.execute('SELECT content FROM working_memory WHERE id=?', (mid,)).fetchone()
    if not row:
        print(f'[{mid}] NOT FOUND'); continue
    s = row[0]
    text = s.lower()
    print('=' * 72)
    print(f'[{mid}]')
    m = classify_memory(s)
    print('  =>', m.memory_type.value, 'conf=', m.confidence)
    hits = []
    for pat, mtype, conf, prio in tm._EN_PATTERNS:
        try:
            for mm in re.finditer(pat, text):
                hits.append((mm.start(), mm.end(), mtype.value, conf, pat[:60]))
        except Exception:
            pass
    for ending, mtype, conf, prio in getattr(tm, '_KO_ENDINGS', []):
        for mm in re.finditer(ending, text):
            hits.append((mm.start(), mm.end(), mtype.value, conf, 'KO:' + ending[:50]))
    hits.sort(key=lambda h: h[0])
    for st, en, t, c, p in hits:
        snippet = text[max(0, st - 15):en + 15].replace('\n', ' ')
        print(f'  [{st:4d}-{en:4d}] {t:6s} conf={c} {p!r}')
        print(f'           ...{snippet}...')