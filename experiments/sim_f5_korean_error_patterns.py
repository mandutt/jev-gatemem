# -*- coding: utf-8 -*-
"""⑤번(한글 ERROR 구문 패턴) 시뮬레이션.

라이브 typed_memory.py를 로드하고, ⑤번 패턴을 메모리상에서만 추가한 뒤
라이브 Mnemosyne DB 823건 전체를 재분류하여 변화를 측정한다.
실제 파일은 건드리지 않는다 (dry-run).

판정 기준:
  A. 변화 건수 / 방향 (context->error 가 개선, error->context 가 회귀)
  B. 변경된 각 건의 문장을 수동 검토: "진짜 오류 보고"인가?
  C. 15개 스모크 케이스 통과 여부
"""
import importlib.util
import json
import re
import sqlite3
import sys

SRC = r'C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages\mnemosyne\core\typed_memory.py'
DB = r'C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db'


def load(path, name='tm'):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    tm = load(SRC)
    print(f'기존 패턴 수: {len(tm.TYPE_PATTERNS)}')

    # --- ⑤번 v4 패턴 (조사 확장) ---
    JOSA = r'(가|를|는|은|도)?'
    F5 = [
        # 1) 오류 발생 서술 (과거/현재)
        (rf'(오류|에러|버그){JOSA}\s*(발생했|발생해|났어|났다|났는데|떴어|떴다|생겼어|생겼다|생겼는데)', tm.MemoryType.ERROR, 0.75, 'high'),
        # 2) 버그/결함 상태 서술
        (rf'(버그|결함|오류){JOSA}\s*(있었|있어서|발견됐|수정됐|고쳐졌|해결됐)', tm.MemoryType.ERROR, 0.72, 'high'),
        # 3) 실패/중지/정지 서술 — "실패했어"는 그대로, 중지/중단은 "오류로/때문에" 맥락만
        (r'(실패)(했|되었|됐|했다|했었)', tm.MemoryType.ERROR, 0.72, 'high'),
        (r'(오류|에러|api|API)(로|때문에)\s*(중지|정지|중단)(되|했)', tm.MemoryType.ERROR, 0.72, 'high'),
        # 4) 반복/지속 오류 — "오류는 [수식어~20자] 계속 발생해" (수식어 삽입 허용)
        (r'(?:오류|에러|버그).{0,20}?(?:계속|또|다시|여전히)\s*(?:발생해?|발생했|나|떠|생기)', tm.MemoryType.ERROR, 0.75, 'high'),
        # 5) 오류 보고 명시 — (있어/있는데) 제거: "~가 있어"는 지시문에도 흔함
        (rf'(오류|에러|문제){JOSA}\s*(생겼|났는데|나서|발생했|발생해)', tm.MemoryType.ERROR, 0.70, 'high'),
    ]
    print(f'⑤번 v4 패턴 수: {len(F5)}')

    # --- 시뮬레이션: 메모리상 TYPE_PATTERNS 교체 ---
    new_pats = list(tm.TYPE_PATTERNS) + F5
    tm.TYPE_PATTERNS = new_pats

    # --- A. 라이브 DB 전체 재분류 ---
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    rows = con.execute('SELECT id, content FROM working_memory').fetchall()
    con.close()
    print(f'라이브 메모리: {len(rows)}건')

    changed = []
    for mid, content in rows:
        if not content:
            continue
        old_t = tm.classify_memory(content).memory_type.value  # 원본은 이미 라이브 상태로 분류됨
        # 기존 패턴만으로 분류 (⑤ 제거)
        tm.TYPE_PATTERNS = list(tm.TYPE_PATTERNS)[: len(new_pats) - len(F5)]
        base_t = tm.classify_memory(content).memory_type.value
        tm.TYPE_PATTERNS = new_pats
        new_t = tm.classify_memory(content).memory_type.value
        if base_t != new_t:
            changed.append((mid, content, base_t, new_t))

    print(f'\n=== 변경 건수: {len(changed)}건 ===')
    improved = [c for c in changed if c[2] in ('context', 'fact') and c[3] == 'error']
    regress = [c for c in changed if c[2] == 'error' and c[3] != 'error']
    print(f'개선 (context/fact -> error): {len(improved)}건')
    print(f'회귀 (error -> 다른 타입):    {len(regress)}건')

    print('\n=== 변경 상세 (중요도순) ===')
    for i, (mid, content, old_t, new_t) in enumerate(improved[:25]):
        print(f'  [{old_t:10s} -> {new_t:10s}] {content[:110]!r}')
    if regress:
        print('\n=== 회귀 상세 ===')
        for mid, content, old_t, new_t in regress[:15]:
            print(f'  [{old_t:10s} -> {new_t:10s}] {content[:110]!r}')

    # --- B. 스모크 테스트 ---
    print('\n=== 스모크 테스트 ===')
    smoke = [
        # (문장, 기대 타입)
        ('좋아 진행해줘', 'context'),          # 기존 핵심 케이스
        ('파일 저장 중 오류가 발생했어', 'error'),  # ⑤ 개선 기대
        ('최신 패치에서 버그가 수정됐어', 'error'),
        ('타임아웃 때문에 빌드가 실패했어', 'error'),
        ('이 오류는 시작할 때마다 계속 발생해', 'error'),
        ('새 폴더로 파일을 옮겼어', 'context'),    # artifact 아님
        ('설정 파일은 이 경로에 있어', 'context'),
        ('나는 버그리포트를 작성할 것이다', 'fact'),  # 기존 KO STATEMENT(~것이다) 동작 유지  # 지시/예정 — error 아님
        ('버그가 있는 calc.py를 테스트해줘', 'context'),  # 지시문 — error 아님
        ('오류가 계속 발생해서 로그를 확인했어', 'error'),
        ('중간에 오류로 중지된 것 같아. 계속 이어서 해줘', 'context'),  # 추측+지시 — error 아님?
        ('어제 빌드가 실패했었어', 'error'),
        ('The build failed due to a timeout', 'error'),  # 영어 회귀 확인
        ('An error occurred while saving the file', 'error'),  # 영어 회귀 확인
        ('I moved the file to the new folder', 'context'),  # 영어 회귀 확인
    ]
    tm.TYPE_PATTERNS = new_pats
    ok = 0
    for s, want in smoke:
        got = tm.classify_memory(s).memory_type.value
        mark = '✅' if got == want else f'❌ (기대 {want})'
        if got == want:
            ok += 1
        print(f'  {mark} {s[:50]:52s} -> {got}')
    print(f'\n스모크: {ok}/{len(smoke)}')

    # --- C. 변경 내역 JSON 저장 (추후 라이브 적용 전 검토용) ---
    out = r'C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\results\f5_simulation_changes.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(
            [{'id': mid[:12], 'content': content[:300], 'from': old_t, 'to': new_t}
             for mid, content, old_t, new_t in changed],
            f, ensure_ascii=False, indent=2,
        )
    print(f'\n변경 내역 저장: {out}')


if __name__ == '__main__':
    main()