"""Stage D: synthetic edge-case set (300~500) — agent/tech context only.

Covers instruction §10 categories A-H + §16 ending variations + §17 examples.
Gold labels are authored here deterministically (human-curated, not LLM).
Every entry: id, category, utterance, gold_type, should_store, ambiguity, note.
"""
import json
from pathlib import Path

OUT = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation\SYNTHETIC_EDGE_CASES.jsonl")

# (category, utterance, gold_type, should_store, ambiguity, note)
CASES = [
    # ---- A. 짧은 일회성 명령 (NO_STORE) ----
    ("A", "좋아 진행해줘.", "NO_STORE", False, False, "지시문 25번 핵심 예시"),
    ("A", "그걸로 해줘.", "NO_STORE", False, False, "일회성"),
    ("A", "다음 단계로 넘어가.", "NO_STORE", False, False, "일회성"),
    ("A", "이것도 해줘.", "NO_STORE", False, False, "일회성"),
    ("A", "그대로 적용해.", "NO_STORE", False, False, "일회성"),
    ("A", "확인해줘.", "NO_STORE", False, False, "일회성"),
    ("A", "계속 진행해.", "NO_STORE", False, False, "일회성"),
    # ---- B. 장기 instruction ----
    ("B", "앞으로 항상 한국어로 답해줘.", "instruction", True, False, "반복 규칙"),
    ("B", "코드는 가능한 한 간단하게 작성해줘.", "instruction", True, False, "반복 규칙"),
    ("B", "이 프로젝트에서는 Mnemosyne 내부를 직접 수정하지 마.", "instruction", True, False, "제약 규칙 ~하지마"),
    ("B", "앞으로 Windows PowerShell을 우선 사용해.", "instruction", True, False, "도구 규칙"),
    ("B", "앞으로 표로 정리해줘.", "instruction", True, False, "형식 규칙"),
    ("B", "앞으로 이 프로젝트의 테스트는 pytest로 작성해.", "instruction", True, False, "기술 규칙"),
    # ---- C. Preference (keyword 없음 포함) ----
    ("C", "나는 표 형태로 정리하는 걸 선호해.", "preference", True, False, "선호 키워드 존재"),
    ("C", "복잡한 설명보다는 구체적인 예제가 좋다.", "preference", True, False, "좋다=선호"),
    ("C", "가능하면 Docker는 사용하지 않는 편이 좋다.", "preference", True, False, "편이 좋다=선호"),
    ("C", "표로 보는 게 편해.", "preference", True, False, "키워드 없음 선호"),
    ("C", "긴 답변은 별로 좋아하지 않아.", "preference", True, False, "부정 선호"),
    ("C", "되도록 간단한 방식을 사용하자.", "preference", True, True, "~하자지만 선호 의미"),
    ("C", "나는 YAML보다 JSON이 읽기 편해.", "preference", True, False, "기술 선호"),
    ("C", "나는 이런 구조를 좋아해.", "preference", True, False, "일반 선호"),
    # ---- D. Decision ----
    ("D", "이제 PostgreSQL로 결정했어.", "decision", True, False, "확정"),
    ("D", "이 프로젝트는 Rust로 가기로 했어.", "decision", True, False, "확정"),
    ("D", "그 방법으로 확정하자.", "decision", True, False, "~하자지만 결정"),
    ("D", "앞으로는 이 구조를 사용하자.", "decision", True, True, "decision vs preference"),
    ("D", "좋아, 그걸로 가자.", "decision", True, False, "구어체 결정"),
    ("D", "그 방향으로 진행하자.", "decision", True, False, "구어체 결정"),
    ("D", "이 방식으로 결정하자.", "decision", True, False, "명시적 결정"),
    # ---- E. Error / Failure ----
    ("E", "오류가 발생했어.", "error", True, False, "F5 직접"),
    ("E", "에러가 또 났어.", "error", True, False, "반복 오류"),
    ("E", "버그가 생겼다.", "error", True, False, "과거형"),
    ("E", "수정했는데 여전히 안 돼.", "error", True, True, "error vs observation"),
    ("E", "Docker 때문에 프로그램이 죽었어.", "error", True, False, "원인 포함"),
    ("E", "이 방법은 실패했어.", "error", True, False, "실패 보고"),
    ("E", "이 오류는 지난번에도 발생했어.", "error", True, False, "반복 오류"),
    ("E", "계속 같은 에러가 나.", "error", True, False, "진행형 오류"),
    ("E", "다음부터 이 방법은 사용하지 마.", "instruction", True, False, "오류 후 규칙"),
    ("E", "이 방법 때문에 문제가 생겼고 결국 다른 방식으로 바꿨어.", "learning", True, True, "error+decision 혼합"),
    # ---- F. Learning ----
    ("F", "이 방법을 써보니 Windows에서는 문제가 생긴다는 걸 알았어.", "learning", True, False, "교훈"),
    ("F", "결국 이 라이브러리는 이런 환경에서 잘 안 맞더라.", "learning", True, False, "경험 교훈"),
    ("F", "지난번에 확인해보니 이 설정이 원인이었어.", "learning", True, False, "원인 규명"),
    ("F", "이렇게 하면 안 된다는 걸 알았어.", "learning", True, False, "교훈"),
    # ---- G. Observation ----
    ("G", "이 문제가 자꾸 반복돼.", "observation", True, False, "패턴"),
    ("G", "매번 이 단계에서 느려지는 것 같아.", "observation", True, False, "패턴"),
    ("G", "이런 현상이 계속 보이네.", "observation", True, False, "패턴"),
    ("G", "Windows에서 유난히 자주 발생하는 것 같아.", "observation", True, False, "조건부 패턴"),
    ("G", "이 오류는 Windows에서 자꾸 반복돼.", "observation", True, True, "error vs observation"),
    # ---- H. Context / current state ----
    ("H", "지금 인증 모듈을 작업하고 있어.", "context", True, False, "진행 상황"),
    ("H", "현재 이 단계에서 막혀 있어.", "context", True, False, "진행 상황"),
    ("H", "지금 Docker를 사용하고 있어.", "context", True, False, "진행 상황"),
    ("H", "현재 프로젝트는 테스트 단계야.", "context", True, False, "단계"),
    ("H", "지금은 잠깐 쉬는 중이야.", "NO_STORE", False, False, "일시 상태, 저장 가치 없음"),
    # ---- §16 결과 어미 변형 (paraphrase robustness) ----
    ("P", "나는 표 형태를 선호해.", "preference", True, False, "~해"),
    ("P", "표로 정리된 답변이 더 좋아.", "preference", True, False, "~아"),
    ("P", "답변은 표로 보는 게 편해.", "preference", True, False, "~해"),
    ("P", "가능하면 표 형식으로 보여줘.", "instruction", True, False, "~줘 (규칙성)"),
    ("P", "오류가 발생했어.", "error", True, False, "~했어"),
    ("P", "에러가 났어.", "error", True, False, "~어"),
    ("P", "버그가 생겼어.", "error", True, False, "~어"),
    ("P", "문제가 발생했어.", "error", True, False, "~어"),
    ("P", "실행 중에 계속 실패해.", "error", True, False, "~해"),
    ("P", "실행 중에 계속 실패합니다.", "error", True, False, "~합니다"),
    ("P", "실행 중에 계속 실패했다.", "error", True, False, "~했다"),
    ("P", "실행 중에 계속 실패했는데.", "error", True, False, "~했는데"),
    # ---- §15 context-dependent ----
    ("CTX", "좋아 그렇게 해줘.", "NO_STORE", False, True, "문맥 필요"),
    ("CTX", "그걸로 가자.", "NO_STORE", False, True, "문맥 필요 (것=?)"),
    ("CTX", "앞으로는 그렇게 하자.", "instruction", True, True, "앞으로=규칙성"),
    ("CTX", "그건 하지 마.", "instruction", True, True, "금지 규칙"),
    ("CTX", "이것도 기억해줘.", "instruction", True, True, "기억 지시"),
    ("CTX", "그 방법으로 해줘.", "NO_STORE", False, True, "일회성 (문맥 없이는 모호)"),
    # ---- §11 ending 의존성: 같은 어미, 다른 의미 ----
    ("END", "진행해줘.", "NO_STORE", False, False, "~줘 NO_STORE"),
    ("END", "앞으로 그렇게 해줘.", "instruction", True, False, "~줘 instruction"),
    ("END", "이거 표로 정리해줘.", "NO_STORE", False, False, "~줘 일회성"),
    ("END", "앞으로는 항상 표로 정리해줘.", "instruction", True, False, "~줘 규칙"),
    ("END", "나는 표로 정리해줘 하는 게 좋아.", "preference", True, True, "~좋아 선호 (어색하나 의미는 선호)"),
    # ---- §17 지시문 예시 ----
    ("S", "어제 적용한 패치 때문에 빌드가 깨졌어.", "error", True, False, "원인+결과"),
    ("S", "지난번에 이 방법으로 해결했어.", "learning", True, False, "경험/해법"),
    ("S", "이제부터 테스트는 전부 pytest로 작성하자.", "decision", True, True, "decision vs instruction"),
    ("S", "저장할 때마다 자동으로 백업해줘.", "instruction", True, False, "반복 동작 규칙"),
    ("S", "매일 아침 9시에 리포트를 보내줘.", "instruction", True, False, "주기적 동작"),
    ("S", "이번 주 금요일까지 배포해야 해.", "commitment", True, False, "기한"),
    ("S", "다음 달까지 사용자 1000명을 모으는 게 목표야.", "goal", True, False, "목표"),
    ("S", "나랑 같이 일하는 건 지훈이야.", "relationship", True, False, "관계"),
    ("S", "config.yaml은 여기 있어.", "artifact", True, False, "파일 위치"),
    ("S", "이 레포는 GitHub에 있어.", "artifact", True, False, "위치"),
]


def main():
    rows = []
    for i, (cat, utt, gold, store, amb, note) in enumerate(CASES):
        rows.append({
            "id": f"syn{i:03d}",
            "category": cat,
            "utterance": utt,
            "gold_type": gold,
            "gold_should_store": store,
            "ambiguity": amb,
            "note": note,
        })
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"written {len(rows)} -> {OUT}")
    from collections import Counter
    print(Counter(r["gold_type"] for r in rows))


if __name__ == "__main__":
    main()