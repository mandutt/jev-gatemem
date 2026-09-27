# -*- coding: utf-8 -*-
"""④번(F1/F2) 패치 로직 — reapply_korean_classifier.py에서 import하여 사용.

F1: 한국어 종결형 FACT 어미 f"[{_KO_FIN_XX}]다" / f"[{_KO_FIN_XX}]니다" 패턴에
    (?![가-힣]) 추가 → "했다가/입니다만" 같은 문장 중간 매치 차단
    ("했다." / "했다\"" / 문장 끝은 유지)
F2: (version|v)\\s*\\d+\\.?\\d* 에 (?![A-Za-z0-9_-]) 추가 → "deepseek-v4-flash"의
    v4 오매치 차단 ("버전 v2.1" 같은 정상 버전은 유지)
"""

import re


def apply_f4_to_text(text: str):
    """파일 텍스트에 F1/F2를 적용. (text, f1_count, f2_count) 반환."""
    # F1: 라인 단위로 처리 (문자열 치환 시 오프셋 어긋남 방지)
    f1_count = 0
    out_lines = []
    for line in text.split("\n"):
        m = re.search(
            r'(f"\[\{_KO_FIN_[A-Z_]+\}\])(다|니다)(", MemoryType\.FACT,)', line,
        )
        if m and "(?![가-힣])" not in line:
            line = (
                line[: m.start(2)]
                + m.group(2)
                + "(?![가-힣])"
                + line[m.end(2):]
            )
            f1_count += 1
        out_lines.append(line)
    text = "\n".join(out_lines)

    f2_count = 0
    old_v = r"(?<![A-Za-z0-9_])(version|v)\s*\d+\.?\d*"
    new_v = r"(?<![A-Za-z0-9_])(version|v)\s*\d+\.?\d*(?![A-Za-z0-9_-])"
    if old_v in text and "(?![A-Za-z0-9_-])" not in text:
        text = text.replace(old_v, new_v, 1)
        f2_count = 1

    return text, f1_count, f2_count