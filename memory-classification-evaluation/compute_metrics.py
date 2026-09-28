"""Compute metrics from gold + baseline results; emit METRICS.md + CONFUSION_MATRIX.csv.

Usage: python compute_metrics.py <gold.jsonl> <baseline.jsonl>
"""
import json
import sys
import io
from pathlib import Path
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TYPES = ["fact", "preference", "decision", "commitment", "goal", "event",
         "instruction", "relationship", "context", "learning", "observation",
         "error", "artifact", "unknown", "NO_STORE"]
STORE_TYPES = [t for t in TYPES if t != "NO_STORE"]


def main():
    gold_path = Path(sys.argv[1])
    base_path = Path(sys.argv[2])
    outdir = gold_path.parent

    gold = {}
    for l in open(gold_path, encoding="utf-8"):
        r = json.loads(l)
        if "error" not in r and "gold_type" in r:
            gold[r["id"]] = r
    baseline = {}
    for l in open(base_path, encoding="utf-8"):
        r = json.loads(l)
        baseline[r["id"]] = r

    ids = [i for i in gold if i in baseline]
    print(f"gold={len(gold)} baseline={len(baseline)} matched={len(ids)}")

    # ---- per-type confusion ----
    conf = Counter()
    g_store_true = 0
    g_store_pred_true = 0
    tp_store = 0
    type_correct = 0
    for i in ids:
        gt = gold[i]["gold_type"]
        pt = baseline[i]["predicted_type"]
        gs = gt != "NO_STORE"
        ps = pt != "NO_STORE" and pt != "unknown"  # classifier never emits NO_STORE; context is a real type
        # For should_store: gold says store; classifier stores (any of 13 types)
        conf[(gt, pt)] += 1
        if gs:
            g_store_true += 1
            if ps:
                tp_store += 1
        if ps:
            g_store_pred_true += 1
        if gt == pt:
            type_correct += 1

    n = len(ids)
    acc = type_correct / n if n else 0

    # should_store precision/recall/F1
    p_store = tp_store / g_store_pred_true if g_store_pred_true else 0
    r_store = tp_store / g_store_true if g_store_true else 0
    f1_store = 2 * p_store * r_store / (p_store + r_store) if (p_store + r_store) else 0

    # per-type P/R/F1 (among store types)
    lines = []
    lines.append("# METRICS.md")
    lines.append("")
    lines.append(f"## Summary (n={n})")
    lines.append("")
    lines.append(f"- MemoryType exact-match accuracy: **{acc:.3f}**")
    lines.append(f"- should_store precision: {p_store:.3f} ({tp_store}/{g_store_pred_true})")
    lines.append(f"- should_store recall: {r_store:.3f} ({tp_store}/{g_store_true})")
    lines.append(f"- should_store F1: {f1_store:.3f}")
    lines.append(f"- unknown rate: {sum(1 for i in ids if baseline[i]['predicted_type']=='unknown')/n:.3f}")
    lines.append("")
    lines.append("## Per-type metrics")
    lines.append("")
    lines.append("| type | n_gold | precision | recall | F1 |")
    lines.append("|---|---|---|---|---|")
    for t in TYPES:
        ng = sum(1 for i in ids if gold[i]["gold_type"] == t)
        if ng == 0:
            continue
        np = sum(1 for i in ids if baseline[i]["predicted_type"] == t)
        tp = conf[(t, t)]
        prec = tp / np if np else 0
        rec = tp / ng if ng else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
        lines.append(f"| {t} | {ng} | {prec:.3f} | {rec:.3f} | {f1:.3f} |")
    lines.append("")
    lines.append("## Confusion pairs (지시문 §13)")
    lines.append("")
    pairs = [("preference", "instruction"), ("preference", "decision"),
             ("decision", "instruction"), ("error", "event"),
             ("error", "observation"), ("error", "learning"),
             ("fact", "context"), ("event", "context"),
             ("goal", "commitment"), ("context", "NO_STORE"),
             ("instruction", "NO_STORE"), ("fact", "NO_STORE")]
    lines.append("| gold → pred | count |")
    lines.append("|---|---|")
    for g, p in pairs:
        c = conf[(g, p)]
        if c:
            lines.append(f"| {g} → {p} | {c} |")
    lines.append("")
    lines.append("## Top confusions (전체)")
    lines.append("")
    lines.append("| gold → pred | count |")
    lines.append("|---|---|")
    for (g, p), c in conf.most_common(15):
        if g != p:
            lines.append(f"| {g} → {p} | {c} |")

    (outdir / "METRICS.md").write_text("\n".join(lines), encoding="utf-8")

    # confusion matrix CSV
    with open(outdir / "CONFUSION_MATRIX.csv", "w", encoding="utf-8") as f:
        f.write("gold\\pred," + ",".join(TYPES) + "\n")
        for g in TYPES:
            row = [g]
            for p in TYPES:
                row.append(str(conf[(g, p)]))
            f.write(",".join(row) + "\n")

    print(f"wrote METRICS.md + CONFUSION_MATRIX.csv to {outdir}")


if __name__ == "__main__":
    main()