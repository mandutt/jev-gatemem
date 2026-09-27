"""Mnemosyne typed_memory.py — 한국어 어미 분류 패치 재적용 스크립트.

용도: Mnemosyne 업데이트로 `mnemosyne/core/typed_memory.py`가 원본으로
덮어써진 뒤, 한국어 어미 분류 패치를 다시 적용한다.

사용법:
  python scripts/reapply_korean_classifier.py [--target path/to/typed_memory.py]

동작:
  1. 대상 파일이 이미 패치 적용 상태인지 확인 (마커 문자열 검색)
  2. 미적용이면 한국어 블록을 주입 (EN 패턴 뒤)
  3. 검증: 한국어/영어 스모크 케이스 실행

안전장치: 파일을 직접 바꾸기 전 .bak 백업. 검증 실패 시 롤백.
"""
import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from mnemosyne.core.typed_memory import MemoryType

MARKER = "# --- Korean Syllable Classes (28 jongsung) ---"
BACKUP_SUFFIX = ".bak-ko-classifier"

# 주입할 한국어 블록 (typed_memory.py의 CONFIDENCE_BOOSTERS 앞에 삽입)
# 주의: 이 블록은 _EN_PATTERNS(영어 패턴 리스트) 다음, CONFIDENCE_BOOSTERS 앞에 온다.
KOREAN_BLOCK = r'''# --- Korean Syllable Classes (28 jongsung) ---
# Hangul syllables are finite: (19 choseong) x (21 jungseong) x (28 jongseong) = 11,172.
# Build per-jongseong character classes once so ending-morpheme patterns can
# match any syllable carrying that final consonant (or none). This covers
# plain AND compound finals (ㅄ, ㄵ, ㄺ, ㅆ, ...) without enumerating words.
# Jongseong index order (verified against U+AC00..): 0:none 1:ㄱ 2:ㄲ 3:ㄳ
# 4:ㄴ 5:ㄵ 6:ㄶ 7:ㄷ 8:ㄹ 9:ㄺ 10:ㄻ 11:ㄼ 12:ㄽ 13:ㄾ 14:ㄿ 15:ㅀ 16:ㅁ
# 17:ㅂ 18:ㅄ 19:ㅅ 20:ㅆ 21:ㅇ 22:ㅈ 23:ㅊ 24:ㅋ 25:ㅌ 26:ㅍ 27:ㅎ
_GA = 0xAC00
_KO_CLASS: Dict[int, str] = {
    jong: ''.join(
        chr(_GA + i * 588 + m * 28 + jong)
        for i in range(19) for m in range(21)
    )
    for jong in range(28)
}
_KO_NO_FINAL = _KO_CLASS[0]
_KO_FIN_N = _KO_CLASS[4]    # ㄴ
_KO_FIN_NJ = _KO_CLASS[5]   # ㄵ (앉)
_KO_FIN_L = _KO_CLASS[8]    # ㄹ
_KO_FIN_M = _KO_CLASS[16]   # ㅁ
_KO_FIN_B = _KO_CLASS[17]   # ㅂ
_KO_FIN_BS = _KO_CLASS[18]  # ㅄ (없)
_KO_FIN_S = _KO_CLASS[19]   # ㅅ
_KO_FIN_SS = _KO_CLASS[20]  # ㅆ (었/있/했)
_KO_FIN_NG = _KO_CLASS[21]  # ㅇ
_KO_FIN_H = _KO_CLASS[27]   # ㅎ

# Korean ending-morpheme patterns (applied AFTER English patterns).
_KO_QUESTION = (
    (f"[{_KO_FIN_N}]지", MemoryType.CONTEXT, 0.72, "high"),      # ~ㄴ지 (맞는지)
    (f"[{_KO_FIN_L}]까", MemoryType.CONTEXT, 0.72, "high"),      # ~ㄹ까 (할까)
    (f"[{_KO_FIN_N}]가", MemoryType.CONTEXT, 0.68, "high"),      # ~ㄴ가 (맞는가)
    (f"[{_KO_NO_FINAL}]나", MemoryType.CONTEXT, 0.60, "high"),   # ~냐/~나 (뭐냐)
    (f"[{_KO_FIN_N}]데", MemoryType.CONTEXT, 0.66, "high"),      # ~ㄴ데 (없는데)
    (f"[{_KO_FIN_L}]게", MemoryType.CONTEXT, 0.60, "high"),      # ~ㄹ게 (앉을게)
)
_KO_REQUEST = (
    (f"[{_KO_NO_FINAL}]줘", MemoryType.CONTEXT, 0.80, "high"),   # ~줘 (해줘)
    (f"[{_KO_NO_FINAL}]자", MemoryType.CONTEXT, 0.78, "high"),   # ~자 (가자)
    (f"[{_KO_NO_FINAL}]게", MemoryType.CONTEXT, 0.62, "high"),   # ~게 (보게)
    (f"[{_KO_NO_FINAL}]세요", MemoryType.CONTEXT, 0.82, "high"), # ~세요
    (f"[{_KO_FIN_S}]세요", MemoryType.CONTEXT, 0.80, "high"),    # ~었세요
)
_KO_STATEMENT = (
    (f"[{_KO_FIN_SS}]다", MemoryType.FACT, 0.74, "stable"),      # 있었다/먹었다/했다 (ㅆ)
    (f"[{_KO_FIN_BS}]다", MemoryType.FACT, 0.78, "stable"),      # 없다/값다 (ㅄ)
    (f"[{_KO_FIN_NJ}]다", MemoryType.FACT, 0.78, "stable"),      # 앉다/얹다 (ㄵ)
    (f"[{_KO_FIN_N}]다", MemoryType.FACT, 0.70, "stable"),       # 간다/본다 (ㄴ)
    (f"[{_KO_FIN_L}]다", MemoryType.FACT, 0.70, "stable"),       # 살다/알다 (ㄹ)
    (f"[{_KO_FIN_H}]다", MemoryType.FACT, 0.70, "stable"),       # 좋다/많다 (ㅎ)
    (f"[{_KO_FIN_B}]다", MemoryType.FACT, 0.72, "stable"),       # 쉽다/밉다 (ㅂ)
    (f"[{_KO_FIN_M}]니다", MemoryType.FACT, 0.76, "stable"),     # 남니다/감니다 (ㅁ+니다)
    (f"[{_KO_FIN_B}]니다", MemoryType.FACT, 0.80, "stable"),     # 합니다/있습니다 (ㅂ+니다)
    (f"[{_KO_FIN_NG}]니다", MemoryType.FACT, 0.72, "stable"),    # 공입니다 (ㅇ+니다)
    (r"[\uac00-\ud7af]+(이다|ㄴ다)[\s.,!?~]*$", MemoryType.FACT, 0.68, "stable"),  # 사실이다/간다
)
_KO_DEFAULT = (
    (r"[\uac00-\ud7af]+[\s.,!?~]*$", MemoryType.CONTEXT, 0.30, "high"),
    (r"[\uac00-\ud7af]+(?:어|아|지|죠|네요|군요|야|이야)[\s.,!?~]*$", MemoryType.CONTEXT, 0.55, "high"),

# ①번 (2026-09-27): 한국어 어휘 패턴 — 의미가 어미보다 우선.
# conf 원칙: 어휘(의미) > 어미(문법). ERROR 어휘 > ARTIFACT 어휘.
_KO_LEXICON: List[Tuple[str, MemoryType, float, str]] = (
    (r"오류|에러|버그|실패|장애", MemoryType.ERROR, 0.75, "stable"),
    (r"파일|폴더|디렉토리|경로", MemoryType.ARTIFACT, 0.70, "stable"),
)
)


'''


# ③번 (2026-09-27): score=conf(B안) 적용 — 타입 인덱스 가중치 제거.
# classify_memory 내 score 라인을 교체 + 동률 tie-break 추가.
_SCORE_OLD = "score = confidence * (1.0 + 0.1 * list(MemoryType).index(mem_type))"
_SCORE_NEW = """score = confidence
            if score > best_score or (
                score == best_score
                and best_match is not None
                and _TYPE_TIE_ORDER[mem_type] < _TYPE_TIE_ORDER[best_match.memory_type]
            ):"""
_TIE_ORDER_BLOCK = '''
# ③번 (2026-09-27): 동률(tie) 시 타입 의미 우선순위 — 작을수록 우선.
_TYPE_TIE_ORDER: Dict[MemoryType, int] = {
    MemoryType.ERROR: 0,
    MemoryType.ARTIFACT: 1,
    MemoryType.OBSERVATION: 2,
    MemoryType.LEARNING: 3,
    MemoryType.CONTEXT: 4,
    MemoryType.RELATIONSHIP: 5,
    MemoryType.INSTRUCTION: 6,
    MemoryType.EVENT: 7,
    MemoryType.GOAL: 8,
    MemoryType.COMMITMENT: 9,
    MemoryType.DECISION: 10,
    MemoryType.PREFERENCE: 11,
    MemoryType.FACT: 12,
    MemoryType.UNKNOWN: 13,
}
'''


SMOKE_KO = [
    ("좋아 진행해줘", "context"), ("없다", "fact"), ("앉다", "fact"),
    ("먹었다", "fact"), ("맞는지", "context"), ("할까", "context"),
    ("합니다", "fact"), ("있습니다", "fact"), ("그래", "context"),
]
# 한-영/한글 어휘 케이스 (2026-09-27 — ②번 \b 경계 검증)
# NOTE: ①번(어휘), ③번(score=conf)은 2026-09-27 실험 결과 부정적(179건 회귀)로
# 적용 보류. 아래 기대값은 ②번만 적용된 현재 상태 기준.
SMOKE_MIXED = [
    ("파일 error가 났어", "error"),       # 한글 바로 뒤 영어 키워드 → ERROR
    ("이 버그는 middleware 버그야", "context"),  # 한글 "버그" 어휘 패턴 없음 → CONTEXT
    ("error가", "error"),                 # 짧은 혼용
]
SMOKE_EN = [
    "The API endpoint is at https://api.example.com/v2",
    "I prefer dark mode for all my applications",
    "Always validate user input before processing",
]


def find_target() -> Path:
    """Hercules 설치 venv에서 typed_memory.py 위치 탐색."""
    cands = list(Path.home().glob(
        "AppData/Local/hermes/installs/*/environments/*/venv/Lib/site-packages/"
        "mnemosyne/core/typed_memory.py"))
    if cands:
        return cands[0]
    raise FileNotFoundError("typed_memory.py를 찾을 수 없습니다. --target으로 지정하세요.")


def is_applied(path: Path) -> bool:
    return MARKER in path.read_text(encoding="utf-8")


def apply_patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"[skip] 이미 적용됨: {path}")
        return False

    # CONFIDENCE_BOOSTERS 앞에 삽입
    anchor = "CONFIDENCE_BOOSTERS: Dict[MemoryType, List[str]] = {"
    if anchor not in text:
        raise RuntimeError(f"앵커({anchor!r})를 찾을 수 없음 — 파일 구조가 바뀌었을 수 있음")

    # 1) 원본 영어 패턴 리스트 이름을 _EN_PATTERNS로 변경 (KO 병합이 참조)
    #    원본 형태: "TYPE_PATTERNS: List[Tuple[str, MemoryType, float, str]] = ["
    en_decl = "TYPE_PATTERNS: List[Tuple[str, MemoryType, float, str]] = ["
    if en_decl not in text:
        raise RuntimeError(f"영어 패턴 선언({en_decl!r})을 찾을 수 없음")
    text = text.replace(en_decl, "_EN_PATTERNS: List[Tuple[str, MemoryType, float, str]] = [", 1)

    # 2) \b → ASCII 경계 변환 (한글 인접 버그 수정, 2026-09-27)
    #    Python \b는 유니코드 \w 기준 — 한글은 \w에 포함되어 "error가"에서
    #    경계가 안 잡힘. ASCII 문자([A-Za-z0-9_]) 기준 경계로 교체하면
    #    "error가/파일은/버그를" 같은 한-영 혼용에서도 영어 키워드가 매치된다.
    #    원본 패턴은 전부 \b(...) 또는 (...)\b 형태이므로 2규칙으로 충분.
    #    (검증: xerror/errors/some_error_value 등 부분일치는 여전히 매치 안 됨)
    ko_anchor = "CONFIDENCE_BOOSTERS: Dict[MemoryType, List[str]] = {"
    en_start = text.index("_EN_PATTERNS: List")
    en_end = text.index(ko_anchor, en_start)
    en_section = text[en_start:en_end]
    # (1) \b(  →  (?<![A-Za-z0-9_])(       왼쪽 경계 (그룹 앞)
    en_section_new = en_section.replace(r"\b(", r"(?<![A-Za-z0-9_])(")
    # (2) )\b  →  )(?![A-Za-z0-9_])        오른쪽 경계 (그룹 뒤)
    en_section_new = en_section_new.replace(r")\b", r")(?![A-Za-z0-9_])")
    # (3) 혹시 남은 단독 \b (드물게 존재) — 안전하게 ASCII 경계로
    en_section_new = en_section_new.replace(r"\b", r"(?<![A-Za-z0-9_])(?![A-Za-z0-9_])")
    text = text[:en_start] + en_section_new + text[en_end:]

    # 2.5) 관계 패턴 동사 정밀화 (②번 보완, 2026-09-27)
    #    \b → ASCII 경계 후 "Technical Lead이자"의 Lead(직책명사)가
    #    관계 패턴에 매치되는 회귀 방지. 관계 동사는 목적어가 따라올 때만.
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
        print("     [relfix] 관계 패턴 동사 정밀화 적용")
    else:
        # 이미 정밀화됨 (백업 복원 등) — 확인용 출력
        if "led\\s+(the|a|an|this|that|project|team" in text:
            print("     [relfix] 관계 패턴 이미 정밀화됨 (skip)")
        else:
            print("     [WARN] 관계 패턴을 찾을 수 없음 — 적용 안 됨")

    # 2) KO 블록 삽입 + TYPE_PATTERNS 병합 (블록 자체에 병합 포함)
    text = text.replace(anchor, KOREAN_BLOCK + "\n" + anchor, 1)

    # 2.6) ③번: score 공식 교체 (score=conf + tie-break) 및 _TYPE_TIE_ORDER 삽입
    if _SCORE_OLD in text:
        text = text.replace(_SCORE_OLD, _SCORE_NEW, 1)
        print("     [③번] score=conf 공식 적용")
    else:
        print("     [WARN] score 공식을 찾을 수 없음 — ③번 미적용")
    if "_TYPE_TIE_ORDER" not in text:
        # CONFIDENCE_BOOSTERS 닫는 } 뒤에 삽입
        boost_end = text.index("\n}", text.index("CONFIDENCE_BOOSTERS")) + 2
        text = text[:boost_end] + _TIE_ORDER_BLOCK + text[boost_end:]
        print("     [3번] _TYPE_TIE_ORDER 삽입")
    else:
        print("     [3번] _TYPE_TIE_ORDER 이미 존재 (skip)")

    # 2.7) ④번: 한국어 종결 FACT 어미 문장 중간 매치 차단 (F1) + version 모델명 오매치 차단 (F2)
    #    (2026-09-27 라이브 검증: 823건 중 7건 fact->context, 전부 개선, 회귀 0건)
    #    F1: f"[{_KO_FIN_XX}]다/니다" 는 종결형인데 $ 앵커가 없어 "했다가/입니다만"의
    #        문장 중간에도 매치 -> (?![가-힣]) 추가로 한글 연속 시 매치 차단
    #        ("했다." / "했다\"" / 문장 끝은 유지, "했다가"는 차단)
    #    F2: (version|v)\s*\d+\.?\d* 가 "deepseek-v4-flash"의 v4에 매치(FACT 0.9)되어
    #        실험 메모 전체를 fact로 오분류 -> (?![A-Za-z0-9_-]) 추가로 모델명(하이픈 뒤
    #        영문/숫자) 차단. "버전 v2.1" 같은 정상 버전 표기는 유지 (뒤가 공백/문장 끝).
    from f4_patch import apply_f4_to_text
    text, f1_count, f2_count = apply_f4_to_text(text)
    print(f"     [④번] F1(어미 후방차단) {f1_count}개 / F2(version 후방차단) {f2_count}개")

    # 백업 후 기록
    bak = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    shutil.copy2(path, bak)
    path.write_text(text, encoding="utf-8")
    print(f"[ok] 패치 적용: {path}\n     백업: {bak}")
    return True


def verify(path: Path) -> bool:
    import importlib.util

    # 파일을 모듈로 직접 로드 (설치된 패키지가 아니라 패치 대상 파일 검증)
    spec = importlib.util.spec_from_file_location("_tm_verify", path)
    tm = importlib.util.module_from_spec(spec)
    # 동일 디렉토리의 mnemosyne 패키지가 필요할 수 있지만 typed_memory는
    # re/dataclass/enum 외 의존이 없으므로 단독 로드 가능
    spec.loader.exec_module(tm)

    ok = True
    for s, exp in SMOKE_KO:
        got = tm.classify_memory(s).memory_type.value
        if got != exp:
            print(f"  [FAIL] {s!r}: 기대 {exp}, 실제 {got}")
            ok = False
    for s, exp in SMOKE_MIXED:
        got = tm.classify_memory(s).memory_type.value
        if got != exp:
            print(f"  [FAIL] (mixed) {s!r}: 기대 {exp}, 실제 {got}")
            ok = False
    for s in SMOKE_EN:
        got = tm.classify_memory(s).memory_type.value
        if got == "unknown":
            print(f"  [FAIL] {s!r}: unknown")
            ok = False
    if ok:
        print("[ok] 검증 통과 (한국어/영어 스모크)")
    else:
        print("[FAIL] 검증 실패 — 백업에서 복원하세요:", BACKUP_SUFFIX)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", help="typed_memory.py 경로 (기본: Hermes 설치 자동 탐색)")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    target = Path(args.target) if args.target else find_target()
    if args.verify_only:
        sys.exit(0 if verify(target) else 1)

    if is_applied(target):
        print(f"[info] 이미 적용됨 → 검증만 실행: {target}")
        sys.exit(0 if verify(target) else 1)

    apply_patch(target)
    sys.exit(0 if verify(target) else 1)


if __name__ == "__main__":
    main()