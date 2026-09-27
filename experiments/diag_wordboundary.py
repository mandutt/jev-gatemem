# -*- coding: utf-8 -*-
# 어떤 패턴이 새로 매치됐는지 진단
import sys, re
sys.path.insert(0, r'C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages')
from mnemosyne.core.typed_memory import classify_memory
import mnemosyne.core.typed_memory as tm

samples = [
    '[codex session] task: 너는 이 프로젝트의 Technical Lead이자 AI Orchestrator다.',
    '[USER] 전체라고 하면, 통계자료가 끝없이 쌓이는 것 아닐까? 굳이 그 정도까지 보존할 필요는 없고, 6개월 정도까지만 보여주고 그 이후로는 자료를 없애는 쪽',
    'StateM: wrapper hermes-made/statem-skill/, bench statem-bench/, commit 8c3309a',
    '[USER] @url:`https://github.com/mnemosyne-oss/mnemosyne` 깃허브에서 보면, readme에 이런 내용이 있어.',
]
for s in samples:
    text = s.lower()
    print('---')
    print('TEXT:', s[:70].replace('\n', ' '))
    for pat, mtype, conf, prio in tm._EN_PATTERNS:
        try:
            if re.search(pat, text):
                print(f'  EN: {pat[:75]!r} -> {mtype.value} conf={conf}')
        except Exception:
            pass
    for ending, mtype, conf, prio in getattr(tm, '_KO_ENDINGS', []):
        if re.search(ending, text):
            print(f'  KO: {ending[:50]!r} -> {mtype.value} conf={conf}')
    m = classify_memory(s)
    print('  =>', m.memory_type.value)