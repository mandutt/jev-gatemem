"""실측: fit — gold50 5-fold 헬드아웃 검증 (0 JEV 콜)

목적: 'COMMITMENT 유형 conf 하한 0.65' 규칙(full-data 파레토 지점)이
      같은 50건에서 튜닝한 우연(과적합)인지, 헬드아웃에서도
      '유실 0 유지 + FP 절감'이 재현되는지 검증.

사전 고정 판정 기준:
  채택 후보 유지: Protocol B에서 유실 0 유지 repeat ≥ 9/10 AND 평균 FP 절감 ≥ 2건
  보류          : 그 외 (유실 유지율 80~90% 또는 FP 절감 < 2)
  기각          : 유실 0 유지 repeat < 8/10 (운영 '데이터 유실 금지' 원칙 위반)

프로토콜:
  - 반복 층형 5-fold CV (10 repeat, seed 42+r)
  - 규칙: baseline G-AS (store==STORE && type!=CONTEXT) +
          COMMITMENT 유형은 max(store_conf, type_conf) >= tau 요구
  - Protocol A (고정 규칙 tau=0.65): union of test folds = 전체 50건이므로
    full-data 평가와 동일(분할 무관, 결정론적) — 참조값으로만 사용.
  - Protocol B (fit-per-fold): 각 폴드 train에서 목적함수로 tau 선택
    (train 유실 <= baseline 유실 유지 + FP 최대 절감, 동률 시 낮은 tau,
     개선 0이면 tau=0 즉 baseline) → test 폴드에 적용.
  - 통계: McNemar exact (뒤집힌 판정), Wilson 95% CI (FP rate)

raw: gold50_holdout_cv.json
"""
import json
import math
import os
import random
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
GOLD = os.path.join(ROOT, "memory-classification-evaluation", "data", "ab_assistant_gold50_as.jsonl")
OUT = os.path.join(ROOT, "experiments", "operational-golden", "gold50_holdout_cv.json")

TAU_GRID = [0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
BASE_SEED = 42
N_REPEATS = 10
K = 5
TAU_FIXED = 0.65


def load_gold():
    rows = []
    with open(GOLD, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def gold_keep(r):
    return r["gold"].upper() == "STORE"


def base_keep(r):
    return ((r.get("jev_store") or "").upper() == "STORE"
            and (r.get("jev_type") or "").upper() != "CONTEXT")


def conf(r):
    return max(r.get("jev_store_conf") or 0.0, r.get("jev_type_conf") or 0.0)


def rule_keep(r, tau):
    """baseline G-AS + COMMITMENT conf 하한."""
    if not base_keep(r):
        return False
    if tau > 0 and (r.get("jev_type") or "").upper() == "COMMITMENT":
        return conf(r) >= tau
    return True


def strat_folds(n, y, k, seed):
    rng = random.Random(seed)
    by_class = {}
    for i, v in enumerate(y):
        by_class.setdefault(v, []).append(i)
    folds = [[] for _ in range(k)]
    for cls, idxs in by_class.items():
        rng.shuffle(idxs)
        for j, i in enumerate(idxs):
            folds[j % k].append(i)
    return folds


def wilson(n, k, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - s) / d, (c + s) / d)


def mcnemar_exact(b, c):
    """양측 exact McNemar: b=올바른 변화(correctly cut FP), c=틀린 변화(유실)."""
    n = b + c
    if n == 0:
        return 1.0
    p = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / (2 ** n)
    return 2 * p


def main():
    rows = load_gold()
    y = [gold_keep(r) for r in rows]
    n_gold_keep = sum(y)
    n_gold_nostore = len(rows) - n_gold_keep
    assert len(rows) == 50 and n_gold_keep == 31, (len(rows), n_gold_keep)

    # full-data (Protocol A 참조값)
    base_fp = sum(1 for r in rows if base_keep(r) and not gold_keep(r))
    base_lost = sum(1 for r in rows if not base_keep(r) and gold_keep(r))
    a_fp = sum(1 for r in rows if rule_keep(r, TAU_FIXED) and not gold_keep(r))
    a_lost = sum(1 for r in rows if not rule_keep(r, TAU_FIXED) and gold_keep(r))

    # knife-edge: max_conf 0.60~0.72 구간 행 (threshold 민감도)
    knife = [{"id": r["id"], "gold": r["gold"], "jev_type": r.get("jev_type"),
              "store_conf": r.get("jev_store_conf"), "type_conf": r.get("jev_type_conf"),
              "max_conf": round(conf(r), 3)}
             for r in rows if 0.60 <= conf(r) <= 0.72]

    # Protocol B: 반복 5-fold fit→test
    repeats = []
    total_b_cut = total_b_wrong = 0
    for rep in range(N_REPEATS):
        seed = BASE_SEED + rep
        folds = strat_folds(len(rows), y, K, seed)
        b_fp = b_lost = 0
        tau_choices = []
        fold_records = []
        for fi in range(K):
            test_idx = set(folds[fi])
            test = [rows[i] for i in folds[fi]]
            train = [rows[i] for i in range(len(rows)) if i not in test_idx]

            # fit: train에서 tau 선택
            base_lost_tr = sum(1 for r in train if not base_keep(r) and gold_keep(r))
            base_fp_tr = sum(1 for r in train if base_keep(r) and not gold_keep(r))
            best_tau, best_cut = 0.0, 0
            for tau in TAU_GRID[1:]:
                lost = sum(1 for r in train if not rule_keep(r, tau) and gold_keep(r))
                fp = sum(1 for r in train if rule_keep(r, tau) and not gold_keep(r))
                if lost > base_lost_tr:
                    continue
                cut = base_fp_tr - fp
                if cut > best_cut or (cut == best_cut and cut > 0 and tau < best_tau):
                    best_cut, best_tau = cut, tau

            # test 평가
            t_fp = t_lost = 0
            flipped = []
            for r in test:
                b = base_keep(r)
                v = rule_keep(r, best_tau)
                if v and not gold_keep(r):
                    t_fp += 1
                if not v and gold_keep(r):
                    t_lost += 1
                if b != v:
                    flipped.append({"id": r["id"], "gold": r["gold"],
                                    "direction": "cut" if (b and not v) else "add",
                                    "correct": (b and not v and not gold_keep(r))
                                               or (not b and v and gold_keep(r))})
                    if b and not v and not gold_keep(r):
                        total_b_cut += 1
                    if b and not v and gold_keep(r):
                        total_b_wrong += 1
            b_fp += t_fp
            b_lost += t_lost
            tau_choices.append(best_tau)
            fold_records.append({"fold": fi, "test_ids": [rows[i]["id"] for i in folds[fi]],
                                 "fitted_tau": best_tau, "test_fp": t_fp, "test_lost": t_lost,
                                 "flipped": flipped})
        repeats.append({"rep": rep, "seed": seed, "b_fp": b_fp, "b_lost": b_lost,
                        "tau_choices": tau_choices, "folds": fold_records})

    # 집계
    b_fps = [r["b_fp"] for r in repeats]
    b_losts = [r["b_lost"] for r in repeats]
    lost0 = sum(1 for v in b_losts if v == 0)
    tau_hist = Counter(t for r in repeats for t in r["tau_choices"])
    mean_fp_cut = (base_fp * N_REPEATS - sum(b_fps)) / N_REPEATS

    stats = {
        "full_data": {"base_fp": base_fp, "base_lost": base_lost,
                      "tau65_fp": a_fp, "tau65_lost": a_lost},
        "protocol_b": {
            "repeats": N_REPEATS, "lost0_repeats": lost0,
            "lost0_rate": lost0 / N_REPEATS,
            "b_fp_list": b_fps, "b_lost_list": b_losts,
            "mean_fp_cut_vs_baseline": mean_fp_cut,
            "fp_cut_min": base_fp - max(b_fps), "fp_cut_max": base_fp - min(b_fps),
            "tau_histogram": dict(tau_hist),
            "mcnemar": {"correct_cuts": total_b_cut, "wrong_cuts": total_b_wrong,
                        "p_exact": mcnemar_exact(total_b_cut, total_b_wrong)},
            "wilson_fp_rate": {"baseline": wilson(n_gold_nostore, base_fp),
                               "tau65_fixed": wilson(n_gold_nostore, a_fp)},
            "wilson_lost_rate": {"baseline": wilson(n_gold_keep, base_lost),
                                 "tau65_fixed": wilson(n_gold_keep, a_lost)},
        },
        "knife_edge_rows": knife,
    }

    print("== full-data ==")
    print(f"baseline: FP {base_fp}/{n_gold_nostore}, 유실 {base_lost}/{n_gold_keep}")
    print(f"tau=0.65 고정: FP {a_fp}, 유실 {a_lost}")
    print("\n== Protocol B (fit-per-fold, 10 repeat) ==")
    print(f"유실 0 유지: {lost0}/10 ({lost0/10:.0%})  ← 기준 9/10")
    print(f"b_fp 목록: {b_fps} / b_lost 목록: {b_losts}")
    print(f"평균 FP 절감: {mean_fp_cut:.1f}  ← 기준 2.0")
    print(f"tau 선택 히스토그램: {dict(tau_hist)}")
    print(f"McNemar: correct {total_b_cut} / wrong {total_b_wrong}, p={mcnemar_exact(total_b_cut, total_b_wrong):.4f}")
    print(f"Wilson FP율 baseline {wilson(n_gold_nostore, base_fp)} / tau65 {wilson(n_gold_nostore, a_fp)}")

    verdict = "채택 후보 유지" if (lost0 >= 9 and mean_fp_cut >= 2.0) else (
        "기각" if lost0 < 8 else "보류")
    print(f"\n판정 (사전 고정 기준): {verdict}")

    out = {"generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
           "verdict": verdict, "stats": stats, "repeats": repeats,
           "note": "Protocol A 고정규칙은 결정론적이라 분할 무관 = full-data와 동일(참조값)."}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nraw 저장: {OUT}")


if __name__ == "__main__":
    main()