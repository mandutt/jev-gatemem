"""Stage-26 결과 저장: gold 미선택 9건 판정 (2026-10-05, 사람 판정 대역)."""
import json

rows = [
    {"idx": 1, "gold": "d7e42dafa3143a", "query": "S4 임베딩 마이그레이션 이후 검증",
     "verdict": "A", "reason": "picked=S4 검증 최종 요약 행 — 같은 답"},
    {"idx": 2, "gold": "4f8278a3700482", "query": "fit 피드백 루프/라벨 자동 튜닝",
     "verdict": "A", "reason": "picked=fit 라벨 수집 핵심 — 직접 답"},
    {"idx": 3, "gold": "0e2418bbc4d68f", "query": "② 3차 외부 검토 지시문 초안",
     "verdict": "A", "reason": "picked=같은 유저 쿼리 원문 행 — 같은 답"},
    {"idx": 4, "gold": "87483f163c9123", "query": "다른 ai에게 검토 요청",
     "verdict": "B", "reason": "picked=검토요청서 안내 — 관련 있으나 gold의 비교 핵심은 약함"},
    {"idx": 5, "gold": "05ab2f73f273e8", "query": "메커니즘 검증 먼저",
     "verdict": "B", "reason": "picked=검토 요청서 첨부 — 관련이나 직접 답 아님"},
    {"idx": 6, "gold": "01dfeb21681e2a", "query": "모델 하나만으로 다 끝낼 수 있는 경우",
     "verdict": "C", "reason": "picked=abstain(None) — gold가 직접 답인데 기권"},
    {"idx": 7, "gold": "8c43c4f6bd49a0", "query": "② 3차 외부 검토 지시문 초안",
     "verdict": "A", "reason": "picked=같은 유저 쿼리 원문 행"},
    {"idx": 8, "gold": "61ec2684bf12c3", "query": "gold44 자동 생성 기반?",
     "verdict": "A", "reason": "picked=gold44 경위 직접 답"},
    {"idx": 9, "gold": "f76a006d207290", "query": "장문 보고서 입력하면 걸릴 문제?",
     "verdict": "A", "reason": "picked=장문 빈틈 정량 실측 — 직접 답"},
]

A = sum(1 for r in rows if r["verdict"] == "A")
B = sum(1 for r in rows if r["verdict"] == "B")
C = sum(1 for r in rows if r["verdict"] == "C")
print(f"판정: A(VALID) {A}건, B(PLAUS) {B}건, C(IRREL) {C}건")
print(f"→ 갭의 성격: 대부분({A}/9)은 '다른 후보가 같은 답을 담음' = gold exact-ID 지표의 인공물")
print(f"  B {B}건은 관련 후보, C {C}건만 실제 오선택/abstain")

with open(r"C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden/data/stage26_verdicts.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
print("저장: data/stage26_verdicts.json")