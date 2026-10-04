"""주입 건 수동 3분류 판정 파일 생성 (b AI Q6 프로토콜) (2026-10-04)

A(choice)가 LGO/fresh noans에서 주입(선택)한 43건을 3분류:
- VALID   : 대체 증거로 유효 (gold 제거 후에도 실제로 답을 담고 있는 다른 메모리)
- PLAUS   : 그럴듯하지만 틀림 (해로운 오주입 — 사용자 오해 유발)
- IRREL   : 무관 (주제도 다른 엉뚱한 메모리)

해로운 오주입률 = PLAUS / 전체 쿼리 (b AI 정의)
- LGO / noans 각각 산출 + Wilson 95% 구간
출력: data/gold44_like_3class_review.md (사람이 판정할 수동 파일)
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
DATA = "experiments/operational-golden/data"

d = json.load(open(os.path.join(DATA, "exp7f_winner_gate_raw.json"), encoding="utf-8"))
recs = d["records"]

lines = []
lines.append("# A choice 주입 건 3분류 수동 판정 (43건)")
lines.append("")
lines.append("> 생성: 2026-10-04 · 대상: LGO 37건 + fresh noans 6건 (exp7b2/exp7d에서 A choice가 선택한 건)")
lines.append("> b AI 프로토콜: 조건(exp7b2/exp7d)을 가린 채 판정. 3분류:")
lines.append("> - **VALID** = 대체 증거로 유효 (gold 행 제거 후에도 실제 답을 담는 다른 메모리)")
lines.append("> - **PLAUS** = 그럴듯하지만 틀림 (해로운 오주입)")
lines.append("> - **IRREL** = 무관 (주제도 다른 엉뚱한 메모리)")
lines.append(">")
lines.append("> **판정 방법**: 아래 각 항목의 [질문]과 [선택된 메모리]만 보고, 옆에 `VALID` / `PLAUS` / `IRREL` 중 하나를 기록")
lines.append("> **해로운 오주입률** = PLAUS / 전체. LGO와 noans를 따로 산출.")
lines.append("")
lines.append("---")
lines.append("")

cnt = 0
for r in recs:
    cnt += 1
    src = "LGO" if r["src"] == "lgo" else "NOANS"
    q = (r["query"] or "").replace("\n", " ").strip()
    c = (r["cand"] or "").replace("\n", " ").strip()
    verdict = r.get("verdict", "?")
    lines.append(f"### {cnt}. [{src}] {r['qid']}")
    lines.append(f"- **질문**: {q}")
    lines.append(f"- **선택된 메모리**: {c}")
    lines.append(f"- **Winner Gate 판정**: {verdict} (참고용 — 판정에 영향 주지 마세요)")
    lines.append(f"- **수동 판정**: ___ (VALID / PLAUS / IRREL)")
    lines.append("")

with open(os.path.join(DATA, "winner_gate_3class_review.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"생성: {DATA}/winner_gate_3class_review.md ({cnt}건)")