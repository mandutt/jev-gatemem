"""Error analysis + representative cases from gold/baseline.

Emits ERROR_ANALYSIS.md and REPRESENTATIVE_CASES.md.
Usage: python analyze_errors.py <gold.jsonl> <baseline.jsonl>
"""
import json
import sys
import io
from pathlib import Path
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ERROR_TAXONOMY = [
    "RULE_ERROR", "KOREAN_ENDING_ERROR", "KEYWORD_ERROR", "PRIORITY_ERROR",
    "AMBIGUOUS_UTTERANCE", "CONTEXT_REQUIRED", "ONTOLOGY_GAP", "GOLD_AMBIGUITY",
    "DATASET_ARTIFACT", "NO_STORE_BOUNDARY", "JEV_RECALL_COMPENSATION", "OTHER",
]


def classify_error(g, p, amb, note=""):
    """Heuristic error taxonomy per contention §20."""
    if amb:
        return "AMBIGUOUS_UTTERANCE"
    if g in ("preference", "decision", "instruction", "commitment", "goal",
             "relationship", "artifact") and p == "context":
        return "KOREAN_ENDING_ERROR"  # no Korean pattern for these types at all
    if g == "error" and p == "context":
        return "RULE_ERROR"  # F5 didn't cover the phrasing
    if g == "NO_STORE" and p == "context":
        return "NO_STORE_BOUNDARY"
    if g == "context" and p == "fact":
        return "PRIORITY_ERROR"
    if g != p:
        return "RULE_ERROR"
    return "OK"


def main():
    gold_path = Path(sys.argv[1])
    base_path = Path(sys.argv[2])
    outdir = gold_path.parent

    gold = {}
    for l in open(gold_path, encoding="utf-8"):
        r = json.loads(l)
        if "error" not in r and "gold_type" in r and r.get("gold_type"):
            gold[r["id"]] = r
    baseline = {}
    for l in open(base_path, encoding="utf-8"):
        baseline[json.loads(l)["id"]] = json.loads(l)

    ids = [i for i in gold if i in baseline]
    mismatches = []
    for i in ids:
        g = gold[i]
        p = baseline[i]
        if g["gold_type"] != p["predicted_type"]:
            cat = classify_error(g["gold_type"], p["predicted_type"],
                                 g.get("ambiguity", False), g.get("note", ""))
            mismatches.append({
                "id": i, "utterance": g["utterance"], "gold": g["gold_type"],
                "pred": p["predicted_type"], "conf": p["predicted_confidence"],
                "pattern": (p.get("matched_pattern") or "")[:50],
                "category": cat, "ambiguity": g.get("ambiguity", False),
                "reason": g.get("reason", "")[:100],
            })

    cat_counts = Counter(m["category"] for m in mismatches)
    lines = []
    lines.append("# ERROR_ANALYSIS.md")
    lines.append("")
    lines.append(f"- 분석 대상: {len(ids)} samples, 오분류 {len(mismatches)} ({len(mismatches)/len(ids):.1%})")
    lines.append("")
    lines.append("## Error taxonomy (지시문 §20)")
    lines.append("")
    lines.append("| category | count |")
    lines.append("|---|---|")
    for c in ERROR_TAXONOMY:
        if cat_counts[c]:
            lines.append(f"| {c} | {cat_counts[c]} |")
    lines.append("")
    lines.append("## Category별 대표 사례")
    lines.append("")
    for c in ERROR_TAXONOMY:
        examples = [m for m in mismatches if m["category"] == c][:8]
        if not examples:
            continue
        lines.append(f"### {c}")
        lines.append("")
        for m in examples:
            lines.append(f"- `{m['utterance'][:55]}` — gold={m['gold']} pred={m['pred']} (conf={m['conf']})")
        lines.append("")

    # Korean ending dependency analysis
    lines.append("## 종결어미 의존성 (지시문 §11)")
    lines.append("")
    ending_stats = defaultdict(lambda: {"n": 0, "wrong": 0})
    for i in ids:
        e = gold[i].get("ending_class") or "?"
        ending_stats[e]["n"] += 1
        if gold[i]["gold_type"] != baseline[i]["predicted_type"]:
            ending_stats[e]["wrong"] += 1
    lines.append("| ending | n | 오분류 | 오분류율 |")
    lines.append("|---|---|---|---|")
    for e, s in sorted(ending_stats.items(), key=lambda x: -x[1]["n"])[:20]:
        lines.append(f"| ~{e} | {s['n']} | {s['wrong']} | {s['wrong']/s['n']:.0%} |")
    lines.append("")

    # Context-dependent / ambiguous
    amb = [m for m in mismatches if m["ambiguity"]]
    lines.append(f"## Ambiguous utterances (gold에서 ambiguity=true, 오분류 중 {len(amb)}건)")
    lines.append("")
    for m in amb[:10]:
        lines.append(f"- `{m['utterance'][:55]}` — gold={m['gold']} pred={m['pred']}")
    lines.append("")

    (outdir / "ERROR_ANALYSIS.md").write_text("\n".join(lines), encoding="utf-8")

    # representative cases
    lines2 = ["# REPRESENTATIVE_CASES.md", ""]
    lines2.append("## False Store (저장할 필요 없는데 저장된 경우)")
    lines2.append("")
    fs = [m for m in mismatches if m["gold"] == "NO_STORE"][:20]
    lines2.append("| utterance | pred | conf |")
    lines2.append("|---|---|---|")
    for m in fs:
        lines2.append(f"| {m['utterance'][:50]} | {m['pred']} | {m['conf']} |")
    lines2.append("")
    lines2.append("## False Discard (저장할 가치 있는데 저가치 type으로) - gold는 저장 유형, pred=context")
    lines2.append("")
    fd = [m for m in mismatches if m["gold"] not in ("NO_STORE", "context") and m["pred"] == "context"][:25]
    lines2.append("| utterance | gold | conf |")
    lines2.append("|---|---|---|")
    for m in fd:
        lines2.append(f"| {m['utterance'][:50]} | {m['gold']} | {m['conf']} |")
    lines2.append("")
    (outdir / "REPRESENTATIVE_CASES.md").write_text("\n".join(lines2), encoding="utf-8")

    print(f"wrote ERROR_ANALYSIS.md + REPRESENTATIVE_CASES.md (mismatches={len(mismatches)})")


if __name__ == "__main__":
    main()