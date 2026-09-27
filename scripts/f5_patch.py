# -*- coding: utf-8 -*-
"""⑤번(한글 ERROR 구문 패턴) 패치 로직 — reapply_korean_classifier.py에서 import.

목적: en_patterns에 대응하는 한글 ERROR 어휘 부재로 "오류가 발생했어"가
context로 분류되는 문제를 구문 패턴으로 해결.

설계 원칙 (①번 단어 리스트 실패에서 학습):
  - 단어만 매치하면 지시문/가정("버그리포트를 작성할 것이다", "오류 발생 시 참고")
    도 error로 오분류됨 → 동사+어미 구문("발생했/났어/수정됐/실패했")만 매치
  - "오류는 [수식어] 계속 발생해"처럼 조사-동사 사이 수식어 삽입 허용 (.{0,20}?)
  - "~가 있어"는 지시문에도 흔함 → (있어|있는데) 제외 (v3 실험에서 과분류 확인)
  - 중지/중단은 "오류로/때문에 중지" 맥락만 (작업 지시 "중단되었어"는 context 유지)
  - 기존 KO CONTEXT 어미(0.55~0.80)와 경쟁해야 하므로 conf 0.70~0.75

실측 (2026-09-28, 라이브 828건):
  v1 (?![가-힣]) lookahead → 어미 차단으로 전면 실패
  v2 어미 포함 → 22건 변경(20 개선), 지시문 과분류 7건
  v3 (있어/있는데) 제거 + 중지/중단 맥락 제한 → 3건 변경(2 개선)
  v4 조사 확장(가/를/는/은/도) + 수식어 .{0,20}? → 3건 변경(2 개선), 스모크 15/15, 회귀 0
"""

_JOSA = r"(가|를|는|은|도)?"

# (패턴, MemoryType.ERROR, conf, priority) — TYPE_PATTERNS에 추가될 튜플
F5_PATTERNS = [
    # 1) 오류 발생 서술 (과거/현재) — "오류가 발생했어 / 에러가 났어 / 버그가 떴어"
    (rf"(오류|에러|버그){_JOSA}\s*(발생했|발생해|났어|났다|났는데|떴어|떴다|생겼어|생겼다|생겼는데)", 0.75, "high"),
    # 2) 버그/결함 상태 서술 — "버그가 있었어 / 발견됐어 / 수정됐어"
    (rf"(버그|결함|오류){_JOSA}\s*(있었|있어서|발견됐|수정됐|고쳐졌|해결됐)", 0.72, "high"),
    # 3) 실패 서술 — "빌드가 실패했어 / 실패했다 / 실패했었"
    (r"(실패)(했|되었|됐|했다|했었)", 0.72, "high"),
    # 3b) 오류/API로 인한 중지 — "api 때문에 중지됐어 / 오류로 중단됐"
    (r"(오류|에러|api|API)(로|때문에)\s*(중지|정지|중단)(되|했)", 0.72, "high"),
    # 4) 반복/지속 오류 — "오류는 [수식어~20자] 계속 발생해" (수식어 삽입 허용)
    (r"(?:오류|에러|버그).{0,20}?(?:계속|또|다시|여전히)\s*(?:발생해?|발생했|나|떠|생기)", 0.75, "high"),
    # 5) 오류 보고 명시 — "문제가 생겼어 / 오류가 나서 / 에러가 발생했"
    (rf"(오류|에러|문제){_JOSA}\s*(생겼|났는데|나서|발생했|발생해)", 0.70, "high"),
]

# 멱등성 마커 (파일에 이미 적용됐는지 판별)
_MARKER = "F5_PATTERNS"


def apply_f5_to_text(text: str):
    """파일 텍스트에 ⑤번 패턴 블록을 추가. (text, added_count) 반환.

    멱등: _MARKER가 이미 있으면 아무것도 하지 않는다.
    """
    if _MARKER in text:
        return text, 0

    # _KO_PATTERNS 정의 직후가 아니라, 최종 TYPE_PATTERNS 정의(닫는 괄호) 뒤에 삽입
    # (F5 블록이 튜플 중간에 들어가지 않도록; _KO_PATTERNS는 아직 닫히지 않은
    #  튜플이므로 그 안에 삽입하면 SyntaxError)
    anchor = "    _EN_PATTERNS + list(_KO_PATTERNS)\n)"
    idx = text.find(anchor)
    if idx == -1:
        raise RuntimeError("F5: 앵커(TYPE_PATTERNS 닫는 괄호)를 찾지 못함")

    # 삽입할 블록 (닫는 괄호 바로 뒤에 추가)
    block = "\n\n" + "\n".join([
        "# --- ⑤번: 한글 ERROR 구문 패턴 (F5) ---",
        "# en_patterns의 한글 대응 부재로 '오류가 발생했어'가 context로 분류되는 문제 해결.",
        "# 단어 리스트가 아닌 동사+어미 구문만 매치 (지시문/가정 오분류 방지).",
        "# 실측: v4, 828건 회귀 0, 스모크 15/15.",
        "F5_PATTERNS: List[Tuple[str, MemoryType, float, str]] = [",
    ])
    for pat, conf, pri in F5_PATTERNS:
        block += f"\n    ({pat!r}, MemoryType.ERROR, {conf}, {pri!r}),"
    block += "\n]\nTYPE_PATTERNS = TYPE_PATTERNS + F5_PATTERNS\n"

    text = text.replace(anchor, anchor + block, 1)
    return text, len(F5_PATTERNS)


def apply_f5_to_file(path: str):
    """파일에 직접 적용. (적용 여부, 추가된 패턴 수) 반환."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    new_text, count = apply_f5_to_text(text)
    if count:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
    return count > 0, count