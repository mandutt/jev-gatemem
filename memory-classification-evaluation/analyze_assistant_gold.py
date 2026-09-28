"""assistant gold50 판정 vs JEV 게이트 후보 정밀도/재현율 분석."""
import json
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

rows = [json.loads(l) for l in open(DATA / "ab_assistant_gold50.jsonl", encoding="utf-8")]
verdicts = json.load(open(DATA / "ab_assistant_gold50.json", encoding="utf-8"))["verdicts"]

# gold 결합
for i, r in enumerate(rows):
    r["gold"] = "STORE" if verdicts.get(str(i)) == "store" else "NO_STORE"

n = len(rows)
gold_store = sum(1 for r in rows if r["gold"] == "STORE")
gold_nostore = n - gold_store
print(f"gold: STORE={gold_store} NO_STORE={gold_nostore} (n={n})")

def sc(r): return r["jev_store_conf"] or 0.0

def gate(rows, name, fn):
    kept = [r for r in rows if fn(r)]
    tp = sum(1 for r in kept if r["gold"] == "STORE")
    fp = len(kept) - tp
    # 금 STORE 중 누락
    missed = [r for r in rows if r["gold"] == "STORE" and not fn(r)]
    recall = tp / gold_store if gold_store else 0
    precision = tp / len(kept) if kept else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    print(f"\n[{name}]")
    print(f"  keep={len(kept)} ({len(kept)/n*100:.1f}%) | TP={tp} FP={fp}")
    print(f"  precision={precision:.3f} recall={recall:.3f} F1={f1:.3f}")
    if missed:
        print(f"  MISSED {len(missed)}건:")
        for r in missed:
            print(f"    [{r['jev_store']}/{r['jev_type']} conf={sc(r):.2f}] {r['utterance'][:70]}")
    return kept

# 게이트 후보
g1 = gate(rows, "G1: store==STORE", lambda r: r["jev_store"] == "STORE")
ga = gate(rows, "G-a: store==STORE && type!=NO_STORE", lambda r: r["jev_store"] == "STORE" and r["jev_type"] not in (None, "NO_STORE"))
for t in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8):
    gate(rows, f"G-t{t}: store==STORE && conf>={t}", lambda r, t=t: r["jev_store"] == "STORE" and sc(r) >= t)
gate(rows, "G-60+type: store&&conf>=0.6&&type!=NO_STORE",
     lambda r: r["jev_store"] == "STORE" and sc(r) >= 0.6 and r["jev_type"] not in (None, "NO_STORE"))

# JEV-NO_STORE인데 gold STORE (오분류 패턴)
print("\n=== JEV가 NO_STORE로 스킵했지만 gold=STORE (누락 위험) ===")
for r in rows:
    if r["jev_store"] == "NO_STORE" and r["gold"] == "STORE":
        print(f"  [{r['jev_type']} conf={sc(r):.2f}] {r['utterance'][:80]}")

print("\n=== JEV가 STORE지만 gold=NO_STORE (과다저장) ===")
for r in rows:
    if r["jev_store"] == "STORE" and r["gold"] == "NO_STORE":
        print(f"  [{r['jev_type']} conf={sc(r):.2f}] {r['utterance'][:80]}")