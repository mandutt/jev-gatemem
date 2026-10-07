# -*- coding: utf-8 -*-
"""stage96_firing_replay.py — abstain_p 발동 쿼리 production-exact 재현 (2026-10-07)

b-ai F#3: "발동 7건을 production-exact로 재생해 abstain_p가 재현되는지 확인.
재현되면 쿼리·코퍼스 의존, 아니면 변동."

- 대상: trace에서 abstain_p>0.3으로 soft gate 발동한 쿼리 9건 (문서 첨부 #9 제외 — 재현 불가)
- 조건: production-exact (스냅샷 10-06, pool 60, 시간 필터 없음) — stage93과 동일 경로
- 비교: 원 trace abstain_p vs 재실행 abstain_p
- 9콜 (일일 한도 대비 미미)

실행: "$LOCALAPPDATA/jev-mem/venv/Scripts/python.exe" stage96_firing_replay.py
"""
import os, sys, json, time

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import stage93_consumer_2x2 as s93

FIRING = [
    ("그래 보강해줘", 0.31),
    ("지금 확인해줘", 0.34),
    ("아까 rows를 2로 바꾸는 안도 있지 않았나?", 0.81),
    ("일단 '2질문 변형 중 1개 (rule abstain → fact 60 2단)'를 실행해 보자", 0.49),
    ("그래 그렇게 해줘", 0.31),
    ("canary 구축에 대해 설명해줘", 0.37),
    ("cron에 등록해두되 일시정지 상태로 해놓을 순 있나?", 0.42),
    ("그래 수정해줘", 0.48),
    ("지난 v6 검토요청서는 변경하지 말고, v7 검토요청서와 기존 문서들에 반영해줘", 0.38),
]

DATA = os.path.join("experiments", "operational-golden", "data")
OUT = os.path.join(DATA, "stage96_firing_replay.json")

def main():
    results = []
    for i, (q, orig_ap) in enumerate(FIRING):
        r = s93.run_choice_rows(q)
        r["orig_abstain_p"] = orig_ap
        r["reproduced"] = (r.get("abstain_p", 0) > 0.3) == (orig_ap > 0.3)
        results.append(r)
        print(f"[{i+1}/{len(FIRING)}] {q[:45]} | trace ap={orig_ap:.2f} → replay ap={r.get('abstain_p', 0):.2f} idx={r.get('idx')} 재현={r.get('reproduced')}", flush=True)
        json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.5)
    print(f"\n완료: {len(results)}건 → {OUT}")

if __name__ == "__main__":
    main()