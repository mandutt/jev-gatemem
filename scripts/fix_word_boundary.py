"""라이브 typed_memory.py의 _EN_PATTERNS \b → ASCII 경계 변환 (②번 버그 수정).

- 대상: Hermes 설치 venv의 mnemosyne/core/typed_memory.py (현재 한국어 패치 적용본)
- 변경: _EN_PATTERNS 리스트 구간 내부의 모든 \b를 ASCII 경계로 교체
  - \b(  →  (?<![A-Za-z0-9_])(
  - )\b  →  )(?![A-Za-z0-9_])
  - 기타  →  (?<![A-Za-z0-9_])(?![A-Za-z0-9_])
- 한국어 블록(_KO_*)은 건드리지 않음. 백업: typed_memory.py.bak-wordboundary
- 검증: 기존 SMOKE_KO + SMOKE_EN + SMOKE_MIXED 전부 통과해야 함
"""
import shutil
import sys
from pathlib import Path

TARGET = Path(
    r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages\mnemosyne\core\typed_memory.py"
)
BACKUP = TARGET.with_suffix(TARGET.suffix + ".bak-wordboundary")

text = TARGET.read_text(encoding="utf-8")

ko_anchor = "CONFIDENCE_BOOSTERS: Dict[MemoryType, List[str]] = {"
if "_EN_PATTERNS: List" not in text or ko_anchor not in text:
    print("앵커 없음 — 한국어 패치 미적용본이거나 구조 변경. 중단.")
    sys.exit(1)

en_start = text.index("_EN_PATTERNS: List")
en_end = text.index(ko_anchor, en_start)
en_section = text[en_start:en_end]

if r"\b" not in en_section:
    print("변환할 \\b가 없음 — 이미 적용된 상태? 중단.")
    sys.exit(2)

before = en_section.count(r"\b")
en_new = en_section.replace(r"\b(", r"(?<![A-Za-z0-9_])(")
en_new = en_new.replace(r")\b", r")(?![A-Za-z0-9_])")
en_new = en_new.replace(r"\b", r"(?<![A-Za-z0-9_])(?![A-Za-z0-9_])")
after = en_new.count(r"\b")

text = text[:en_start] + en_new + text[en_end:]

shutil.copy2(TARGET, BACKUP)
TARGET.write_text(text, encoding="utf-8")
print(f"[ok] \\b 변환: {before} → {after} (백업: {BACKUP.name})")