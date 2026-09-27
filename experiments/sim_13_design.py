# -*- coding: utf-8 -*-
"""①③ 동시 설계 시뮬레이션 (2026-09-27)

목표: 한글 어휘 패턴(①번)을 추가했을 때,
  (A) 현재 공식 score = conf × (1 + 0.1×index)
  (B) B안 score = conf
각각에서 "한글 어휘"와 "한국어 어미"가 어떻게 경쟁하는지 실측.

시나리오 패턴:
  - KO_LEX_ERROR   = r'오류|에러|버그|실패'      conf 0.75 (어휘, ERROR)
  - KO_LEX_ARTIFACT = r'파일|폴더|디렉토리'      conf 0.70 (어휘, ARTIFACT)
  - 기존 한글 어미: 대표 3개만 (conf는 라이브 값)
      [ㅆ]다 FACT 0.74, [ㅂ]니다 FACT 0.80, (어|아|지|죠|네요|군요|야|이야)$ CONTEXT 0.55
"""
import sys

# 라이브 모듈에서 MemoryType/패턴 구조 재사용
sys.path.insert(0, r'C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages')
import mnemosyne.core.typed_memory as tm
from mnemosyne.core.typed_memory import MemoryType

def score_a(conf, idx):
    return conf * (1.0 + 0.1 * idx)

def score_b(conf, idx):
    return conf

# 가상 패턴 테이블 (라이브 KO 블록의 대표 + 신규 한글 어휘)
# (label, pattern, type, conf)
TABLE = [
    # 기존 한글 어미 (라이브 값)
    ("어미:ㅆ다/FACT",    r"[ㅆ]다",                MemoryType.FACT,    0.74),
    ("어미:ㅂ니다/FACT",  r"[ㅂ]니다",              MemoryType.FACT,    0.80),
    ("어미:(어아지죠...)$/CONTEXT", r"(?:어|아|지|죠|네요|군요|야|이야)$", MemoryType.CONTEXT, 0.55),
    # 신규 한글 어휘 (①번 후보)
    ("어휘:오류|에러|버그|실패/ERROR",   r"오류|에러|버그|실패", MemoryType.ERROR,   0.75),
    ("어휘:파일|폴더|디렉토리/ARTIFACT", r"파일|폴더|디렉토리",   MemoryType.ARTIFACT, 0.70),
    # 영어 기존 (참고)
    ("EN:error/ERROR",   r"(?<![A-Za-z0-9_])(error|bug|issue|problem|failure|crash)(?![A-Za-z0-9_])", MemoryType.ERROR, 0.70),
    ("EN:file.../ARTIFACT", r"(?<![A-Za-z0-9_])(file|folder|directory|path|url)\s+(name|called|named|is|at)(?![A-Za-z0-9_])", MemoryType.ARTIFACT, 0.70),
]

def matches_all(text):
    return [(lab, t, conf) for lab, pat, t, conf in TABLE if __import__('re').search(pat, text)]

cases = [
    "파일 오류가 났어",           # 어휘 ERROR + 어휘 ARTIFACT
    "파일을 저장했어",            # 어휘 ARTIFACT + 어미 CONTEXT
    "오류가 발생했어",            # 어휘 ERROR + 어미 CONTEXT
    "버그를 수정했어",            # 어휘 ERROR + 어미 CONTEXT
    "파일이야",                  # 어휘 ARTIFACT + 어미 CONTEXT(야)
    "폴더를 만들었어",            # 어휘 ARTIFACT + 어미 CONTEXT
    "there was an error",        # EN error만
    "the file name is config.yaml",  # EN artifact만
]

print(f"{'케이스':<28s} {'매치':<70s} {'A공식 승자':<14s} {'B공식 승자':<14s}")
print("-" * 130)
for c in cases:
    hits = matches_all(c)
    if not hits:
        print(f"{c:<28s} 매치 없음")
        continue
    # A 공식
    best_a = max(hits, key=lambda h: score_a(h[2], list(MemoryType).index(h[1])))
    # B 공식 (conf 동률 시 index tie-break — 파이썬 max는 첫 번째)
    best_b = max(hits, key=lambda h: (score_b(h[2], list(MemoryType).index(h[1])), -list(MemoryType).index(h[1])))
    names = ", ".join(f"{lab}(conf={conf})" for lab, t, conf in hits)
    print(f"{c:<28s} {names[:68]:<70s} {best_a[0]:<14s} {best_b[0]:<14s}")