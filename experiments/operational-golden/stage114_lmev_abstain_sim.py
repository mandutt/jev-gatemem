# -*- coding: utf-8 -*-
"""stage114_lmev_abstain_sim.py — abstain 임계 재해석 시뮬레이션 (2026-10-10, 0콜)

목적: stage112 결과(저장된 jev.idx / abstain_p / rows)를 재해석해
      'abstain 임계를 낮추면 정확도가 얼마나 오르는가'를 시뮬레이션.

핵심: JEV choice는 이미 실행됨 (500콜). abstain_p 임계를 바꿔도
      choice 결과는 변하지 않음 — 노출(top-k)만 달라진다.
      - abstain_p > τ → 메모리 미노출 (현행: 0.0으로 사실상 항상 abstain 시 abstain)
      - abstain_p ≤ τ → 상위 5개 노출 (이미 rows에 저장됨)

시뮬레이션 대상:
  1. τ 하향: abstain 문항(261건) 중 abstain_p ≤ τ인 문항을 '노출'로 전환
  2. 이때 reader 답변은 어떻게 달라질까? — reader는 rows만 보고 답하므로,
     실제 답변 재생성 없이는 정확한 정답 여부를 모름
     → **근사**: '노출 전환 시 judge가 정답할 확률'은 rows에 답이 있었는지로 추정
     (stage112 rows top-5에 답이 포함됐다면 전환 시 정답 가능성 존재)

한계 명시: 이는 상한 추정 (rows top-5에 답이 있으면 정답할 수 있다는 가정).
실제 정확도는 reader 재생성 후 judge 필요 — 여기선 경향만 본다.
"""
import os, sys, json, collections

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
ROWS = os.path.join(REPO, "experiments", "operational-golden", "data", "stage112_lmev_results.jsonl")

# 통계: abstain 문항의 abstain_p 분포
abs_items = []
nonabs_items = []
for l in open(ROWS, encoding="utf-8"):
    r = json.loads(l)
    if r.get("error"):
        continue
    j = r.get("jev") or {}
    if j.get("abstain"):
        abs_items.append(r)
    else:
        nonabs_items.append(r)

print(f"전체 {len(abs_items)+len(nonabs_items)} / abstain {len(abs_items)} / non-abstain {len(nonabs_items)}")
print(f"\nabstain_p 분포 (abstain 문항):")
aps = sorted(x["jev"]["abstain_p"] for x in abs_items)
for thr in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
    n_under = sum(1 for a in aps if a <= thr)
    print(f"  ≤ {thr}: {n_under}/{len(aps)} ({n_under/len(aps)*100:.0f}%)")

# '노출 전환 시 정답 가능' 상한: abstain 행의 rows top-5에 answer(정답 키워드)가 포함?
def rows_contain_answer(r):
    ans = r.get("answer")
    if isinstance(ans, (dict, list)):
        ans = json.dumps(ans)
    ans = str(ans or "").strip()
    if not ans or len(ans) < 3:
        return False
    # 정답의 첫 단어/구절이 rows 내용에 부분 포함?
    ans_lower = ans.lower()
    tokens = [t for t in ans_lower.replace(",", "").split() if len(t) > 2][:4]
    if not tokens:
        return False
    rows_text = " ".join((row.get("content") or "") for row in (r.get("jev") or {}).get("rows", [])).lower()
    # 정답 토큰의 2개 이상이 rows에 있으면 '답 존재 가능'
    hits = sum(1 for t in tokens if t in rows_text)
    return hits >= 2

print(f"\n[상한 추정] abstain 261건 중 rows top-5에 정답 흔적: {sum(rows_contain_answer(r) for r in abs_items)}건")
print(f"  → 이건 '노출하면 정답할 수도' 상한. 실제는 reader 재생성 필요.")

# 타입별 abstain 비율
by_type = collections.Counter(r["question_type"] for r in abs_items)
by_type_all = collections.Counter(r["question_type"] for r in abs_items + nonabs_items)
print(f"\n타입별 abstain 비율:")
for t in sorted(by_type_all):
    n = by_type.get(t, 0)
    print(f"  {t}: {n}/{by_type_all[t]} = {n/by_type_all[t]*100:.0f}%")