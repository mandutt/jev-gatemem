# -*- coding: utf-8 -*-
# 라이브 DB 전체 재분류: 수정 전(백업) vs 수정 후 — 정확한 전체 보고
import sqlite3, importlib.util
from collections import Counter

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

old = load(r'C:\Users\mandu\AppData\Local\Temp\tm_old_backup.py', 'tm_old')
new = load(r'C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages\mnemosyne\core\typed_memory.py', 'tm_new')

DB = r'C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db'
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
rows = con.execute('SELECT id, content FROM working_memory').fetchall()

trans = Counter()
examples = {}
for mid, content in rows:
    if not content or not content.strip():
        continue
    a = old.classify_memory(content).memory_type.value
    b = new.classify_memory(content).memory_type.value
    if a != b:
        trans[(a, b)] += 1
        examples.setdefault((a, b), []).append((mid, content[:100]))

print(f'전체: {len(rows)} 행, 변경: {sum(trans.values())}건')
for (a, b), n in trans.most_common():
    print(f'  {a:14s} -> {b:14s} x{n}')

print('\n=== 변경 샘플 (각 유형 3개씩) ===')
for (a, b), exs in list(examples.items())[:8]:
    print(f'--- {a} -> {b} ---')
    for mid, c in exs[:3]:
        print(f'  [{mid}] {c}')