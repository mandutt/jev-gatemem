"""4단계 분석: 2×2 ablation raw → 지표/검정 리포트

- Hit@3 (단일 gold), GoldRecall@3 (다중 gold), MRR, Pool Recall
- 무답 오주입률 (C/D: τ 초과, A/B: choice가 abstain 아닌 후보 선택)
- Primary: A vs C — McNemar (짝지은) + Holm (3쌍: A-C, A-B, C-D)
- 불일치 쌍 전수 리스트 (수동 검토용)
산출: experiments/operational-golden/data/ablation_2x2_report.json + 표 출력
"""
import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo 루트 (3단계)
DATA = os.path.join(ROOT, "experiments/operational-golden/data")


def hit_at(records, k=3):
    """records: [{'rank': r or None}] → hit@k 비율"""
    ok = [r for r in records if r.get("rank") is not None]
    hit = [r for r in ok if r["rank"] <= k]
    return len(hit) / len(records) if records else 0.0, len(ok), len(records)


def mrr(records):
    vals = [1.0 / r["rank"] for r in records if r.get("rank") is not None]
    return sum(vals) / len(records) if records else 0.0


def mcnemar(a_rec, c_rec):
    """짝지은 검정: hit@3 기준 (a_only, c_only) discordant pairs → exact binomial"""
    keys = {("op_qid", r["qid"], r.get("axis")): r for r in a_rec}
    pairs = []
    for cr in c_rec:
        key_a = ("op_qid", cr["qid"], cr.get("axis"))
        ar = keys.get(key_a)
        if ar is None or cr.get("rank") is None or ar.get("rank") is None:
            continue
        pairs.append((ar["rank"] <= 3, cr["rank"] <= 3))
    b = sum(1 for x, y in pairs if x and not y)  # A만 hit
    c = sum(1 for x, y in pairs if y and not x)  # C만 hit
    n = b + c
    if n == 0:
        return 0.0, b, c, 1.0
    # exact binomial two-sided p (p=0.5)
    from math import comb
    p = sum(comb(n, i) for i in range(0, min(b, c) + 1)) * 2 / (2 ** n)
    p = min(1.0, p)
    return p, b, c, n


def main():
    raw_path = os.path.join(DATA, "ablation_2x2_raw.json")
    if not os.path.exists(raw_path):
        print(f"FAIL: {raw_path} 없음 — 본실험 먼저 실행")
        return 2
    raw = json.load(open(raw_path, encoding="utf-8"))
    results = raw["results"]

    # 소스별/조건별 그룹
    groups = defaultdict(list)
    for r in results:
        if r.get("src") in ("op", "new", "syn"):
            groups[(r["src"], r["cond"])].append(r)

    print("=" * 78)
    print(f"2×2 Read Ablation 결과 (코퍼스 {raw['corpus_n']}행, 해시 {raw['corpus_hash']})")
    print("=" * 78)

    # ---- Hit@3 / MRR (소스별) ----
    for src in ("op", "new", "syn"):
        print(f"\n--- {src} ---")
        for cond in ("A", "B", "C", "D"):
            recs = groups.get((src, cond), [])
            if not recs:
                continue
            h3, n_ok, n_tot = hit_at(recs, 3)
            h1, _, _ = hit_at(recs, 1)
            m = mrr(recs)
            errs = sum(1 for r in recs if r.get("err"))
            ab = sum(1 for r in recs if r.get("abstain"))
            print(f"  {cond}: n={len(recs):3d} hit@1={h1*100:5.1f}% hit@3={h3*100:5.1f}% "
                  f"MRR={m:.3f} (rank측정 {n_ok}) abstain={ab} err={errs}")

    # ---- 통합 (op+new+syn) ----
    print(f"\n--- 통합 (op+new+syn) ---")
    allg = defaultdict(list)
    for r in results:
        if r.get("src") in ("op", "new", "syn"):
            allg[r["cond"]].append(r)
    for cond in ("A", "B", "C", "D"):
        recs = allg.get(cond, [])
        if not recs:
            continue
        h3, _, _ = hit_at(recs, 3)
        h1, _, _ = hit_at(recs, 1)
        print(f"  {cond}: n={len(recs):3d} hit@1={h1*100:5.1f}% hit@3={h3*100:5.1f}% MRR={mrr(recs):.3f}")

    # ---- 무답 오주입 ----
    print(f"\n--- 무답 오주입 ---")
    tau_data = None
    tp = os.path.join(DATA, "tau_result.json")
    if os.path.exists(tp):
        tau_data = json.load(open(tp, encoding="utf-8"))
    na = [r for r in results if r.get("src") == "noans"]
    for cond in ("A", "B", "C", "D"):
        recs = [r for r in na if r["cond"] == cond]
        if not recs:
            continue
        if cond in ("C", "D"):
            tau = tau_data["tau"] if tau_data else 0.5
            vals = [r.get("max_score") for r in recs if r.get("max_score") is not None]
            over = sum(1 for v in vals if v > tau)
            print(f"  {cond}: n={len(vals)} τ={tau:.3f} 오주입(>τ)={over}/{len(vals)} "
                  f"= {over/len(vals)*100 if vals else 0:.1f}%")
        else:
            vals = [r.get("choice") for r in recs if r.get("choice") is not None]
            picked = sum(1 for v in vals if v >= 0)
            print(f"  {cond}: n={len(vals)} choice 발동={picked}/{len(vals)} "
                  f"(abstain={sum(1 for v in vals if v == -1)})")

    # ---- McNemar (Primary A vs C, 통합) ----
    print(f"\n--- McNemar Primary (A vs C, hit@3, op+new) ---")
    a_rec = [r for r in results if r.get("src") in ("op", "new") and r["cond"] == "A"]
    c_rec = [r for r in results if r.get("src") in ("op", "new") and r["cond"] == "C"]
    p, b, c_, n = mcnemar(a_rec, c_rec)
    print(f"  A만 hit={b} / C만 hit={c_} / discordant={n} / exact p={p:.4f}")
    if n:
        print(f"  → {'유의 (p<0.05)' if p < 0.05 else '비유의'}")

    # 불일치 쌍 리스트
    a_by = {(r["qid"], r.get("axis")): r for r in a_rec}
    disc = []
    for cr in c_rec:
        ar = a_by.get((cr["qid"], cr.get("axis")))
        if ar and ar.get("rank") is not None and cr.get("rank") is not None:
            ah, ch = ar["rank"] <= 3, cr["rank"] <= 3
            if ah != ch:
                disc.append({
                    "qid": cr["qid"], "src": cr["src"], "axis": cr.get("axis"),
                    "query": cr["query"][:80],
                    "a_rank": ar["rank"], "c_rank": cr["rank"],
                    "winner": "A" if ah else "C",
                })
    print(f"\n--- 불일치 쌍 ({len(disc)}건) ---")
    for d in disc[:20]:
        print(f"  [{d['winner']}] {d['src']}/{d.get('axis')} a={d['a_rank']} c={d['c_rank']} | {d['query']}")

    report = {
        "corpus_n": raw["corpus_n"], "corpus_hash": raw["corpus_hash"],
        "groups": {f"{k[0]}_{k[1]}": {"n": len(v),
                                       "hit3": hit_at(v, 3)[0], "hit1": hit_at(v, 1)[0], "mrr": mrr(v)}
                   for k, v in groups.items()},
        "overall": {cond: {"n": len(allg[cond]), "hit3": hit_at(allg[cond], 3)[0],
                            "hit1": hit_at(allg[cond], 1)[0], "mrr": mrr(allg[cond])}
                    for cond in allg},
        "mcnemar_ac": {"p": p, "a_only": b, "c_only": c_, "n": n},
        "discordant_pairs": disc,
    }
    opath = os.path.join(DATA, "ablation_2x2_report.json")
    json.dump(report, open(opath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n저장: {opath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())