"""
⑤-B안 시뮬레이션: 한글 명사형 오류 패턴 (오류 발생/빌드 실패 등) 추가 검증
- 목표: 명사+행위동사 원형 2단어 결합으로 가중치 부여 (단어 1개 매치는 제외)
- 실측: 라이브 DB 전체 재분류 → 변경/회귀 건수 + 스모크
- ①번 실패 원인(어휘 과매치 17건)을 재현하지 않는지 확인
"""
import sys, io, sqlite3, re, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

VENV_SP = r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages"
sys.path.insert(0, VENV_SP)

from mnemosyne.core import typed_memory
from mnemosyne.core.typed_memory import MemoryType, TypeMatch
import mnemosyne.core.typed_memory as tm

DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"

# ---------- B안 후보 패턴 (명사+행위동사 원형) ----------
# 설계: 지시문 어미(하세요/해줘/하자)와 가정문(~시)은 원형과 다름
# "버그를 수정하세요" → '수정하세' — 매치 안 됨 ✅
# "오류 발생 시 참고" → '발생 시' — 매치 안 됨 (시 다음 위치) ✅
# "오류 발생" → 매치 ✅ / "빌드 실패" → 매치 ✅
B_PATTERNS = [
    # (패턴, conf, 설명)
    (r'(오류|에러|버그)(가|를|는|은|도)?\s*(발생|발견|확인|해결|수정)\b', 0.68, '명사형: 오류+발생/해결/수정 등'),
    (r'(빌드|테스트|배포|연결|설치|실행)(가|를|는|은|도)?\s*(실패|오류|에러)\b', 0.68, '명사형: 빌드+실패 등'),
    (r'(파싱|구문|문법|타입|인코딩)\s*(오류|에러)\b', 0.70, '기술용어+오류 접미'),
]

# ---------- 스모크 케이스 ----------
SMOKE = [
    # 명사형 (error 기대)
    ("오류 발생", "error"), ("빌드 실패", "error"), ("오류 해결", "error"),
    ("버그 수정", "error"), ("파싱 오류", "error"), ("파일 저장 오류", "error"),
    ("오류 발생: Connection refused (port 8080)", "error"),
    ("빌드가 실패했어", "error"), ("오류가 발생했어", "error"), ("오류가 해결됐어", "error"),
    # 지시문/가정문 (error 아니어야 함 — 과분류 방지)
    ("버그를 수정하세요. test_calc.py는 수정하지 마세요", "context"),
    ("오류 발생 시 재시도해줘", "context"),
    ("오류 확인 부탁해", "context"),
    ("파일을 저장해줘", "context"),
    ("테스트를 실행해줘", "context"),
    ("빌드를 실행해줘", "context"),
    # 혼용 (영어 로그+한국 요청)
    ("Error: File not found. 파일 경로를 다시 확인해줘", "error"),  # 영어 로그가 이미 error — 유지
    ("오류 발생: Connection refused. 재시도해줘", "error"),  # B안으로 개선될지?
    ("경로 C:/Users/x/abc.py를 찾을 수 없습니다. 다시 확인해줘", "context"),
    # 기존 ⑤ 유지
    ("버그리포트를 작성할 것이다", "fact"),
    ("이 버그는 middleware 버그야", "context"),
]

def simulate():
    # 원본 TYPE_PATTERNS 백업
    orig = list(typed_memory.TYPE_PATTERNS)
    results = {"smoke": [], "db_changes": [], "db_total": 0}

    # ---------- 스모크 (B안만 적용) ----------
    typed_memory.TYPE_PATTERNS = orig + [(p, MemoryType.ERROR, c, 'high') for p, c, _ in B_PATTERNS]
    smoke_ok = 0
    for text, expect in SMOKE:
        m = typed_memory.classify_memory(text)
        actual = m.memory_type.name.lower()
        ok = (actual == expect) or (expect == 'context' and actual in ('context', 'fact', 'instruction', 'preference'))
        if ok: smoke_ok += 1
        results["smoke"].append({"text": text, "expect": expect, "actual": actual, "conf": m.confidence, "pat": (m.matched_pattern or "")[:60]})
    print(f"[스모크] {smoke_ok}/{len(SMOKE)}")

    # ---------- 라이브 DB 전체 재분류 ----------
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT id, content, memory_type FROM working_memory WHERE memory_type IS NOT NULL")
    rows = cur.fetchall()
    con.close()

    changed = []
    for rid, content, db_mt in rows:
        if not content or not content.strip():
            continue
        m = typed_memory.classify_memory(content)
        new_mt = m.memory_type.name.lower()
        if new_mt != db_mt:
            changed.append({"id": rid, "content": content[:200], "from": db_mt, "to": new_mt, "conf": m.confidence, "pat": (m.matched_pattern or "")[:60]})
    results["db_total"] = len(rows)
    results["db_changes"] = changed
    print(f"[DB] {len(rows)}건 중 {len(changed)}건 변경")

    # 복원
    typed_memory.TYPE_PATTERNS = orig
    return results

if __name__ == "__main__":
    res = simulate()
    out = os.path.join(os.path.dirname(__file__), "..", "experiments", "results", "f5b_simulation_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"저장: {out}")
    # 상세 출력
    print("\n--- 스모크 실패 ---")
    for s in res["smoke"]:
        if s["actual"] != s["expect"]:
            print(f"  ❌ {s['text'][:40]} expect={s['expect']} actual={s['actual']}")
    print("\n--- DB 변경 전체 ---")
    for c in res["db_changes"]:
        print(f"  [{c['from']}→{c['to']}] conf={c['conf']:.2f} {c['content'][:90]}")