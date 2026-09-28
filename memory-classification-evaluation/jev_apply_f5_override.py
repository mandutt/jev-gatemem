"""JEV v3 결과에 rule F5(error) override 적용 — 최종 결과 생성.

배경:
- JEV v3 단독 error F1=0.276 (tp=4 fp=6 fn=15) — 오류 신고를 event/observation/context로 보냄
- rule F5(error 패턴)는 conf>=0.7에서 9/10 정확도로 error를 잡음
- rule error(conf>=0.5)가 v3 판단을 덮어쓰면: F1 0.276→0.556, 새 오답 1건(모호 케이스)뿐

사용: python jev_apply_f5_override.py
입력: JEV_ALL1975_V3.jsonl (v3 결과), BASELINE_ALL1975.jsonl (rule baseline)
출력: JEV_ALL1975_V3_F5.jsonl (override 적용 최종)
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
RULE_ERROR_CONF = 0.5  # rule F5가 error로 판단한 최소 conf (실측: 전부 0.7+)


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8")]


def main():
    v3_rows = load_jsonl(HERE / "JEV_ALL1975_V3.jsonl")
    base_rows = load_jsonl(HERE / "BASELINE_ALL1975.jsonl")
    assert len(v3_rows) == len(base_rows) == 1975

    v3_by_id = {r["id"]: r for r in v3_rows}
    base_by_id = {r["id"]: r for r in base_rows}

    overridden = 0
    out = []
    for rid, r in v3_by_id.items():
        b = base_by_id.get(rid)
        row = dict(r)
        if b and b["predicted_type"] == "error" and b.get("predicted_confidence", 0) >= RULE_ERROR_CONF:
            if row["type"] != "error":
                row["type"] = "error"
                row["overridden_by_rule_f5"] = True
                overridden += 1
            else:
                row["overridden_by_rule_f5"] = False
        else:
            row["overridden_by_rule_f5"] = False
        out.append(row)

    out.sort(key=lambda x: x["id"])
    out_path = HERE / "JEV_ALL1975_V3_F5.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"override 적용: {overridden}건 → {out_path.name}")

    # 지표 재계산
    gold_rows = load_jsonl(HERE / "ALL1975.jsonl")
    gold = {r["id"]: r["gold_type"] for r in gold_rows}

    def f1(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        return 2 * p * r / (p + r) if p + r else 0

    # 14-type 정확도
    acc = sum(1 for row in out if row["type"] == gold[row["id"]]) / len(out)

    # per-type F1
    types = sorted({*gold.values(), *(r["type"] for r in out)})
    print(f"\n=== JEV v3 + rule F5 override (n={len(out)}) ===")
    print(f"정확도: {acc:.4f}")
    for t in types:
        tp = sum(1 for r in out if r["type"] == t and gold[r["id"]] == t)
        fp = sum(1 for r in out if r["type"] == t and gold[r["id"]] != t)
        fn = sum(1 for r in out if gold[r["id"]] == t and r["type"] != t)
        print(f"  {t:12s} n={gold and sum(1 for g in gold.values() if g==t):3d} "
              f"prec={tp/(tp+fp) if tp+fp else 0:.3f} rec={tp/(tp+fn) if tp+fn else 0:.3f} F1={f1(tp,fp,fn):.3f}")

    # store 결합 규칙 (type==NO_STORE && store==NO_STORE → NO_STORE)
    store_tp = store_fp = store_fn = store_tn = 0
    for r in out:
        g = gold[r["id"]]
        g_store = g != "NO_STORE"
        j_store = not (r["type"] == "NO_STORE" and r.get("store") == False)  # noqa: E712
        # 결합: type==NO_STORE && store==NO_STORE → NO_STORE
        j_store = not (r["type"] == "NO_STORE" and r.get("store") in (False, "NO_STORE"))
        if j_store and g_store: store_tp += 1
        elif j_store and not g_store: store_fp += 1
        elif not j_store and g_store: store_fn += 1
        else: store_tn += 1
    n = len(out)
    store_acc = (store_tp + store_tn) / n
    print(f"\n=== store 결합 규칙 (type==NO_STORE && store==NO_STORE → NO_STORE) ===")
    print(f"acc={store_acc:.3f} prec={store_tp/(store_tp+store_fp) if store_tp+store_fp else 0:.3f} "
          f"rec={store_tp/(store_tp+store_fn) if store_tp+store_fn else 0:.3f} "
          f"F1={f1(store_tp,store_fp,store_fn):.3f} (TP={store_tp} FP={store_fp} FN={store_fn} TN={store_tn})")


if __name__ == "__main__":
    main()