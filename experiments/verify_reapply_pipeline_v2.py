# -*- coding: utf-8 -*-
"""재적용 파이프라인 최종 검증 v2 (2026-09-27)

시나리오: bak-wordboundary(한국어 패치 + \b 원본, 관계 정밀화 전)에
②번 수정(\b 변환 + 관계 정밀화)만 적용 → 라이브(모든 수정 적용본)와 비교.
한국어 블록은 이미 존재하므로 추가하지 않음.
"""
from pathlib import Path

HERMES_VENV = Path(
    r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages\mnemosyne\core"
)
LIVE = (HERMES_VENV / "typed_memory.py").read_text(encoding="utf-8")
SRC = (HERMES_VENV / "typed_memory.py.bak-wordboundary").read_text(encoding="utf-8")

# 1) \b 변환
ko_anchor = "CONFIDENCE_BOOSTERS: Dict[MemoryType, List[str]] = {"
en_start = SRC.index("_EN_PATTERNS: List")
en_end = SRC.index(ko_anchor, en_start)
en_section = SRC[en_start:en_end]
en_new = en_section.replace(r"\b(", r"(?<![A-Za-z0-9_])(")
en_new = en_new.replace(r")\b", r")(?![A-Za-z0-9_])")
en_new = en_new.replace(r"\b", r"(?<![A-Za-z0-9_])(?![A-Za-z0-9_])")
text = SRC[:en_start] + en_new + SRC[en_end:]

# 2) 관계 정밀화
rel_old = r"(manages?|reports?\s+to|supervises?|leads?)"
rel_new = (
    r"(manages?\s+(the|a|an|this|that|project|team|group|repo|department|company|org)"
    r"|reports?\s+to"
    r"|supervises?\s+(the|a|an|this|that|project|team|group|department)"
    r"|leads?\s+(the|a|an|this|that|project|team|group|repo|department|company|org)"
    r"|led\s+(the|a|an|this|that|project|team|group|repo|department|company|org))"
)
if rel_old in text:
    text = text.replace(rel_old, rel_new, 1)
    print("[ok] 관계 정밀화 적용")

# 3) 주석 제거 후 코드 라인 비교
def code_lines(s):
    return [l for l in s.splitlines() if l.strip() and not l.strip().startswith("#")]

ll = code_lines(LIVE)
sl = code_lines(text)
print(f"라이브 코드 라인: {len(ll)}, 시뮬레이션: {len(sl)}")
same = ll == sl
print("코드 라인 일치:", same)
if not same:
    for i, (a, b) in enumerate(zip(ll, sl)):
        if a != b:
            print(f"  첫 차이 @{i}:")
            print(f"    라이브: {a[:110]}")
            print(f"    시뮬:   {b[:110]}")
            break
    only_live = set(ll) - set(sl)
    only_sim = set(sl) - set(ll)
    print("라이브에만:", list(only_live)[:5])
    print("시뮬에만:", list(only_sim)[:5])