"""v4 프롬프트 결과를 v3+F5 최종 파일에 합성 — JEV_ALL1975_V4.jsonl 생성.

v4_probe는 fact 오분류 + artifact 전체(107건)만 재분류했으므로,
나머지 1868건은 v3+F5 결과를 유지하고 107건만 v4 결과로 교체한다.
단, v4 probe가 '고친 것'만 적용하고 '오히려 틀린 것'은 유지하는 게 아니라
107건 모두 v4 판단으로 교체 (v4가 31.8% 정확, v3는 해당 세트에서 0%).
"""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8")]


def main():
    v3f5 = load_jsonl(HERE / "JEV_ALL1975_V3_F5.jsonl")
    probe = load_jsonl(HERE / "JEV_V4_PROBE.jsonl")
    gold_rows = load_jsonl(HERE / "ALL1975.jsonl")
    gold = {r["id"]: r["gold_type"] for r in gold_rows}

    probe_by_id = {r["id"]: r for r in probe}
    print(f"v3+F5: {len(v3f5)}, probe: {len(probe_by_id)}")

    out = []
    replaced = 0
    for r in v3f5:
        row = dict(r)
        p = probe_by_id.get(r["id"])
        if p and p.get("type"):
            row["type"] = p["type"]
            row["type_confidence"] = p.get("type_confidence")
            row["store"] = p.get("store")
            row["store_confidence"] = p.get("store_confidence")
            row["v4_applied"] = True
            replaced += 1
        else:
            row["v4_applied"] = False
        out.append(row)

    out.sort(key=lambda x: x["id"])
    out_path = HERE / "JEV_ALL1975_V4.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"v4 적용: {replaced}건 → {out_path.name}")

    def f1(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        return 2 * p * r / (p + r) if p + r else 0

    acc = sum(1 for r in out if r["type"] == gold[r["id"]]) / len(out)
    types = sorted({*gold.values(), *(r["type"] for r in out)})
    print(f"\n=== JEV v4 (n={len(out)}) ===")
    print(f"정확도: {acc:.4f} (v3+F5 0.7696)")
    for t in types:
        tp = sum(1 for r in out if r["type"] == t and gold[r["id"]] == t)
        fp = sum(1 for r in out if r["type"] == t and gold[r["id"]] != t)
        fn = sum(1 for r in out if gold[r["id"]] == t and r["type"] != t)
        n = sum(1 for g in gold.values() if g == t)
        print(f"  {t:12s} n={n:3d} prec={tp/(tp+fp) if tp+fp else 0:.3f} rec={tp/(tp+fn) if tp+fn else 0:.3f} F1={f1(tp,fp,fn):.3f}")

    # store 결합 규칙
    store_tp = store_fp = store_fn = store_tn = 0
    for r in out:
        g = gold[r["id"]]
        g_store = g != "NO_STORE"
        j_store = not (r["type"] == "NO_STORE" and r.get("store") in (False, "NO_STORE"))
        if j_store and g_store: store_tp += 1
        elif j_store and not g_store: store_fp += 1
        elif not j_store and g_store: store_fn += 1
        else: store_tn += 1
    n = len(out)
    store_acc = (store_tp + store_tn) / n
    print(f"\n=== store 결합 규칙 ===")
    print(f"acc={store_acc:.3f} prec={store_tp/(store_tp+store_fp) if store_tp+store_fp else 0:.3f} "
          f"rec={store_tp/(store_tp+store_fn) if store_tp+store_fn else 0:.3f} "
          f"F1={f1(store_tp,store_fp,store_fn):.3f} (TP={store_tp} FP={store_fp} FN={store_fn} TN={store_tn})")


if __name__ == "__main__":
    main()