"""Run O gold wrong->none 17건 실사 — abstain이 정화인지 정답 상실인지 판별.

각 건: gold_id, gold_in_pool, gold_pool_rank, base가 고른 wrong 후보(id/excerpt),
abs가 고른 none. gold_in_pool=True & rank 낮음 = abstain이 정답 놓침(부정).
gold_in_pool=False = 정화(정답이 애초에 없음).
"""
import json, os

ROOT = "C:/Users/mandu/hermes-made/jev-memory-middleware"
raw = json.load(open(os.path.join(ROOT, "experiments", "operational-golden", "abstain_run_O_raw.json"), encoding="utf-8"))

rows = [r for r in raw if r.get("gold") and r.get("base_cls") == "wrong" and r.get("abs_cls") == "none"]
print(f"대상: gold wrong->none {len(rows)}건\n")

def excerpt_of(pool, pick_id, n=90):
    # pool entries are 12-char id strings in this raw dump
    if pick_id in pool:
        return f"<id {pick_id}>"
    return "?"

for r in sorted(rows, key=lambda x: x["gold_pool_rank"] if x.get("gold_pool_rank") else 99):
    gold = r["gold"]
    gip = r.get("gold_in_pool")
    grank = r.get("gold_pool_rank")
    base_idx = r["base"]["idx"]
    base_pick = r["pool"][base_idx] if base_idx is not None and 0 <= base_idx < len(r["pool"]) else "?"
    base_ex = excerpt_of(r["pool"], base_pick)
    verdict = ""
    if not gip:
        verdict = "정화(정답 풀 부재): abstain 정당"
    elif grank and grank <= 10:
        verdict = f"⚠ 정답 상실 의심: gold 풀 내 {grank}위인데 none 선택"
    else:
        verdict = f"정화(정답 풀 내 {grank}위 — 순위 깊음/오답이 1위였음): abstain 정당"
    print(f"[{r['cat']}|{r['axis']}] {r['query'][:45]}")
    print(f"  gold={gold[:12]} in_pool={gip} rank={grank} | base pick={str(base_pick)[:12]} abs=none")
    print(f"  base가 고른 오답: {base_ex}")
    print(f"  판정: {verdict}\n")

from collections import Counter
print("판정 집계:", dict(Counter(
    "정화" if (not r.get("gold_in_pool") or (r.get("gold_pool_rank") or 99) > 10)
    else "정답상실의심" for r in rows)))
print(f"\n총 {len(rows)}건 중 정화(정답 부재/깊은 순위) = "
      f"{sum(1 for r in rows if not r.get('gold_in_pool') or (r.get('gold_pool_rank') or 99) > 10)}")
print(f"정답상실 의심(gold 풀 내 ≤10위였는데 none) = "
      f"{sum(1 for r in rows if r.get('gold_in_pool') and (r.get('gold_pool_rank') or 99) <= 10)}")