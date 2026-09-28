"""Run the LIVE Mnemosyne classifier over evaluation sets; emit BASELINE_RESULTS.

Read-only vs Mnemosyne: only imports the classifier module and calls it.
Usage: python run_baseline.py <input.jsonl> <output.jsonl>
"""
import json
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from harness import load_classifier, classify_text  # noqa: E402

HERE = Path(__file__).parent


def run(inp: Path, outp: Path):
    classify, MT, _ = load_classifier()
    rows = [json.loads(l) for l in open(inp, encoding="utf-8")]

    done_ids = set()
    if outp.exists():
        for l in open(outp, encoding="utf-8"):
            done_ids.add(json.loads(l)["id"])

    with open(outp, "a", encoding="utf-8") as f:
        n = 0
        for r in rows:
            if r["id"] in done_ids:
                continue
            res = classify_text(classify, r["utterance"])
            out = {
                "id": r["id"],
                "dataset": r.get("dataset"),
                "utterance": r["utterance"],
                "ending_class": r.get("ending_class"),
                "predicted_type": res["memory_type"],
                "predicted_confidence": res["confidence"],
                "matched_pattern": res["matched_pattern"],
                "priority": res["priority"],
            }
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
            n += 1
    print(f"ran {n} new rows -> {outp}")


def main():
    inp = Path(sys.argv[1])
    outp = Path(sys.argv[2])
    run(inp, outp)


if __name__ == "__main__":
    main()