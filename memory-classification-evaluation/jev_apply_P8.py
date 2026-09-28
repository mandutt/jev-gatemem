"""P8 프롬프트 결과를 P7 최종 파일에 합성 — JEV_ALL1975_P8.jsonl 생성."""
import json
from pathlib import Path

HERE = Path(__file__).parent


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8")]


def main():
    v7 = load_jsonl(HERE / "JEV_ALL1975_V7.jsonl")
    probe = load_jsonl(HERE / "JEV_V8_PROBE.jsonl")
    gold_rows = load_jsonl(HERE / "ALL1975.jsonl")
    gold = {r["id"]: r["gold_type"] for r in gold_rows}

    probe_by_id = {r["id"]: r for r in probe}
    print(f"v7: {len(v7)}, probe: {len(probe_by_id)}")

    out = []
    replaced = 0
    for r in v7:
        row = dict(r)
        p = probe_by_id.get(r["id"])
        if p and p.get("type"):
            row["type"] = p["type"]
            row["type_confidence"] = p.get("type_confidence")
            row["store"] = p.get("store")
            row["store_confidence"] = p.get("store_confidence")
            row["v8_applied"] = True
            replaced += 1
        else:
            row["v8_applied"] = False
        out.append(row)

    out.sort(key=lambda x: x["id"])
    out_path = HERE / "JEV_ALL1975_V8.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"v8 적용: {replaced}건 → {out_path.name}")

    def f1(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        return 2 * p * r / (p + r) if p + r else 0

    acc = sum(1 for r in out if r["type"] == gold[r["id"]]) / len(out)
    types = sorted({*gold.values(), *(r["type"] for r in out)})
    print(f"\n=== JEV v8 (n={len(out)}) ===")
    print(f"정확도: {acc:.4f} (v7 0.8451)")
    for t in types:
        tp = sum(1 for r in out if r["type"] == t and gold[r["id"]] == t)
        fp = sum(1 for r in out if r["type"] == t and gold[r["id"]] != t)
        fn = sum(1 for r in out if gold[r["id"]] == t and r["type"] != t)
        n = sum(1 for g in gold.values() if g == t)
        print(f"  {t:12s} n={n:3d} prec={tp/(tp+fp) if tp+fp else 0:.3f} rec={tp/(tp+fn) if tp+fn else 0:.3f} F1={f1(tp,fp,fn):.3f}")

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
