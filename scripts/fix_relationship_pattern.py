"""라이브 typed_memory.py의 관계 패턴 정밀화 (②번 보완, 2026-09-27).

\b → ASCII 경계 변환 후 생긴 회귀 수정:
"Technical Lead이자"의 "Lead"(직책명사)가 관계 패턴 (manages?|leads?)에
매치되어 relationship으로 오분류되는 문제.

해결: 관계 패턴의 manages/supervises/leads를 동사형(뒤에 목적어/전치사구)만
매치하도록 엄격화. 단독 "lead/manager"는 직책명사로 취급해 관계로 안 잡힘.

변경:
  (manages?|reports?\s+to|supervises?|leads?)
→ (manages?\s+(the|a|an|this|that|project|team|group|repo|department|company|org)
   |reports?\s+to
   |supervises?\s+(the|a|an|this|that|project|team|group|department)
   |leads?\s+(the|a|an|this|that|project|team|group|repo|department|company|org)
   |led\s+(the|a|an|this|that|project|team|group|repo|department|company|org))

백업: typed_memory.py.bak-relfix
"""
import shutil
import sys
from pathlib import Path

TARGET = Path(
    r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages\mnemosyne\core\typed_memory.py"
)
BACKUP = TARGET.with_suffix(TARGET.suffix + ".bak-relfix")

OLD = r"(?<![A-Za-z0-9_])(manages?|reports?\s+to|supervises?|leads?)(?![A-Za-z0-9_])"
NEW = (
    r"(?<![A-Za-z0-9_])("
    r"manages?\s+(the|a|an|this|that|project|team|group|repo|department|company|org)"
    r"|reports?\s+to"
    r"|supervises?\s+(the|a|an|this|that|project|team|group|department)"
    r"|leads?\s+(the|a|an|this|that|project|team|group|repo|department|company|org)"
    r"|led\s+(the|a|an|this|that|project|team|group|repo|department|company|org)"
    r")(?![A-Za-z0-9_])"
)

text = TARGET.read_text(encoding="utf-8")
if OLD not in text:
    print("기존 관계 패턴을 찾을 수 없음 — 이미 정밀화됐거나 구조 변경. 중단.")
    sys.exit(1)
if "relfix" in text or "관계 패턴 정밀화" in text:
    print("이미 정밀화 적용됨. 중단.")
    sys.exit(2)

n = text.count(OLD)
text = text.replace(OLD, NEW)
shutil.copy2(TARGET, BACKUP)
TARGET.write_text(text, encoding="utf-8")
print(f"[ok] 관계 패턴 정밀화: {n}곳 교체 (백업: {BACKUP.name})")