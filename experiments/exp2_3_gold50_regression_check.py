"""실험 2-3: gold50 회귀 검증 — 규칙 후보가 STORE 판정 항목을 건드리는지.

gold50: ab_assistant_gold50.json (verdicts: id → {store?, ...})
200건: ab_assistant_classified.jsonl (jev 결과)
규칙 후보: commitment & store==STORE & "순수 진행 선언" → SKIP 추가
목표: gold50에서 인간이 STORE로 판정한 commitment가 규칙에 걸리면 회귀(add_skip_bad)
"""
import json
import re
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

def main():
    gold50 = json.load(open(BASE / "data/ab_assistant_gold50.json", encoding="utf-8"))
    verdicts = gold50.get("verdicts", gold50)
    if isinstance(verdicts, dict):
        items = list(verdicts.items())
    else:
        items = [(v.get("id"), v) for v in verdicts]
    print(f"gold50 verdicts {len(items)}건, 샘플 3:")
    for k, v in items[:3]:
        print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:150]}")

    # verdict 구조 파악: 어떤 키가 STORE/NO_STORE 판정인지
    stores = set()
    for k, v in items:
        if isinstance(v, dict):
            stores.update(str(x) for x in v.keys())
    print(f"\nverdict 키 종류: {stores}")

    # gold50에서 STORE로 판정된 assistant 발화 (id 기반)
    # ab_assistant_gold50_as.jsonl 에 gold가 있을 수도 — 확인
    store_ids = set()
    for k, v in items:
        if isinstance(v, dict):
            sv = v.get("store") or v.get("verdict") or v.get("should_store")
            if sv in (True, "STORE", "store", "yes", 1):
                store_ids.add(k)
            elif isinstance(sv, str) and "STORE" in sv.upper():
                store_ids.add(k)
    print(f"\nSTORE 판정 {len(store_ids)}건: {sorted(store_ids)[:10]}...")

    # gold50 id ↔ 200건 utterance 매핑 (id: msg_id?)
    rows = []
    with open(BASE / "data/ab_assistant_classified.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    by_id = {o["id"]: o for o in rows}
    print(f"\n200건 id 샘플: {list(by_id.keys())[:5]}")

    # gold50 STORE id가 200건 중 몇 개 존재하는지
    overlap = store_ids & set(by_id.keys())
    print(f"gold50 STORE ∩ 200건: {len(overlap)}건")

    # 규칙 후보 매치 (store_ids 기준)
    pat_pure = re.compile(r"(하겠다|확인하겠다|조사하겠다|분석하겠다|살펴보겠다|해보겠다|돌릴게|할게|확인할게|조사할게)$")
    hit = []
    for i in overlap:
        o = by_id[i]
        if pat_pure.search(o["utterance"].strip()) and o["jev"]["type"] == "commitment":
            hit.append((i, o))
    print(f"\n--- gold50 STORE ∩ commitment ∩ 순수진행규칙: {len(hit)}건 ---")
    for i, o in hit:
        print(f"  {i}: {o['utterance'][:80]}")

if __name__ == "__main__":
    main()