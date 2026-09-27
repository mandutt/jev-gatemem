"""
⑤-B안 v2 시뮬레이션: B안 v1 회귀(가정문/해결문 과분류) 수정 검증
v1 회귀 2건:
  1. "오류 발생 시 참고" → '발생 시' 가정문 — '시' 조사 차단 필요
  2. "키리스 해결 ..." → '해결' 단독 매치 — 해결/수정/확인 단어 제거 (성공 기록이므로)
v1 개선 1건:
  "실행 실패 원인: 배치 파일이..." — '실패' + 부정 맥락(원인) 기록형 → 유지해야 함

설계 원칙:
- 2단어 결합만 (단어 1개 매치 제외 — ①번 과분류 재현 방지)
- 가정문 '시' 차단: (?!\s*시\b)
- '해결/수정/확인' 제거: 성공/요청 명제와 혼동
- '실패'는 부정 맥락 단어(원인|문제|때문에|발생)와 결합 또는 문장 종결만
"""
import sys, io, sqlite3, re, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

VENV_SP = r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages"
sys.path.insert(0, VENV_SP)
import mnemosyne.core.typed_memory as tm
from mnemosyne.core.typed_memory import MemoryType

DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"

# ---------- B안 v2 패턴 ----------
B2_PATTERNS = [
    # 1. 오류/에러/버그 + 발생/발견 — 단, '시'(가정) 차단
    (r'(오류|에러|버그)(가|를|는|은|도)?\s*(발생|발견)(?!\s*시\b)', 0.68, '명사형: 오류+발생 (가정 시 차단)'),
    # 2. 빌드/테스트/배포/연결/설치/실행 + 실패 — 부정 맥락(원인/문제/때문에) 또는 문장 끝
    (r'(빌드|테스트|배포|연결|설치|실행)(가|를|는|은|도)?\s*실패(?=\s*(원인|문제|때문에|발생)|[\s.,!?~]*$)', 0.68, '명사형: 빌드+실패 (부정맥락/종결)'),
    # 3. 기술용어+오류 접미 — 문장 끝 또는 콜론 뒤
    (r'(파싱|구문|문법|타입|인코딩|런타임)\s*오류\b', 0.70, '기술용어+오류'),
]

SMOKE = [
    # 명사형 (error 기대)
    ("오류 발생", "error"), ("빌드 실패", "error"), ("오류 해결", "context"),  # 해결은 빠짐
    ("버그 수정", "context"), ("파싱 오류", "error"), ("파일 저장 오류", "error"),
    ("오류 발생: Connection refused (port 8080)", "error"),
    ("빌드가 실패했어", "error"), ("오류가 발생했어", "error"),
    ("camelai-serial-proxy 실행 실패 원인: 배치 파일이", "error"),
    ("오류 발견", "error"),
    # 지시문/가정문 (error 아니어야 함)
    ("버그를 수정하세요. test_calc.py는 수정하지 마세요", "context"),
    ("오류 발생 시 재시도해줘", "context"),
    ("오류 발생 시 참고할 수 있지 않을까?", "context"),
    ("오류 확인 부탁해", "context"),
    ("파일을 저장해줘", "context"),
    ("테스트를 실행해줘", "context"),
    ("빌드를 실행해줘", "context"),
    ("키리스 해결 (2026-08-21): web_extract", "context"),  # 해결 기록 — error 아님
    ("web_extract 키리스 해결", "context"),
    # 혼용 (영어 로그+한국 요청)
    ("Error: File not found. 파일 경로를 다시 확인해줘", "error"),
    ("오류 발생: Connection refused. 재시도해줘", "error"),
    ("경로 C:/Users/x/abc.py를 찾을 수 없습니다. 다시 확인해줘", "context"),
    # 기존 ⑤ 유지
    ("버그리포트를 작성할 것이다", "fact"),
    ("이 버그는 middleware 버그야", "context"),
]

def simulate():
    orig = list(tm.TYPE_PATTERNS)
    results = {"smoke": [], "b_changes": []}

    tm.TYPE_PATTERNS = orig + [(p, MemoryType.ERROR, c, 'high') for p, c, _ in B2_PATTERNS]

    # 스모크
    smoke_ok = 0
    for text, expect in SMOKE:
        m = tm.classify_memory(text)
        actual = m.memory_type.name.lower()
        ok = (actual == expect) or (expect == 'context' and actual in ('context', 'fact', 'instruction', 'preference'))
        if ok: smoke_ok += 1
        results["smoke"].append({"text": text, "expect": expect, "actual": actual, "conf": m.confidence, "pat": (m.matched_pattern or "")[:70]})
    print(f"[스모크] {smoke_ok}/{len(SMOKE)}")

    # base vs base+B2 순수 비교
    tm.TYPE_PATTERNS = orig
    base = {}
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT id, content FROM working_memory WHERE memory_type IS NOT NULL")
    rows = cur.fetchall()
    con.close()
    for rid, content in rows:
        if not content or not content.strip(): continue
        base[rid] = tm.classify_memory(content).memory_type.name.lower()

    tm.TYPE_PATTERNS = orig + [(p, MemoryType.ERROR, c, 'high') for p, c, _ in B2_PATTERNS]
    for rid, content in rows:
        if not content or not content.strip(): continue
        m = tm.classify_memory(content)
        new = m.memory_type.name.lower()
        if new != base.get(rid):
            results["b_changes"].append({"id": rid, "content": content[:200], "from": base.get(rid), "to": new, "conf": m.confidence, "pat": (m.matched_pattern or "")[:70]})

    tm.TYPE_PATTERNS = orig  # 복원
    return results

if __name__ == "__main__":
    res = simulate()
    out = os.path.join(os.path.dirname(__file__), "..", "experiments", "results", "f5b_v2_simulation_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"저장: {out}")
    print("\n--- 스모크 실패 ---")
    for s in res["smoke"]:
        if s["actual"] != s["expect"]:
            print(f"  ❌ {s['text'][:45]} expect={s['expect']} actual={s['actual']}")
    print("\n--- B2 순수 변경 ---")
    for c in res["b_changes"]:
        print(f"  [{c['from']}→{c['to']}] conf={c['conf']:.2f} {c['content'][:100]}")