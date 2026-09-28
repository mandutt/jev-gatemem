"""assistant 200건을 JEV(P8 프롬프트)로 분류 — 엄격 게이트 실측.

- jev_classify.py의 jev_classify() (P8) 재사용
- 게이트 규칙 후보 비교:
  G1: store==STORE (기존 store 단독)
  G-qual-a: store==STORE && (type not in NO_STORE) — assistant용 엄격 (type rescue 없음: 최종물은 정제돼 있어 NO_STORE면 진짜 no)
  G-qual-b: store==STORE && type != NO_STORE && store_conf >= 0.6
- 결과: 유지 비율, type 분포, 샘플 10건
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from jev_classify import jev_classify, TYPES  # noqa: E402

IN = HERE / "data" / "ab_live_assistant.jsonl"
OUT = HERE / "data" / "ab_assistant_classified.jsonl"


def main():
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("!! TYPESAFE_API_KEY 미설정")
        return 1
    rows = [json.loads(l) for l in open(IN, encoding="utf-8")]
    print(f"분류 대상: {len(rows)}건")

    results = []
    for i, r in enumerate(rows):
        try:
            res = jev_classify(r["utterance"])
        except Exception as e:
            print(f"[{i}] FAIL {type(e).__name__}: {e}")
            res = {"store": None, "type": None, "store_prob": 0.0, "type_prob": 0.0}
        r["jev"] = res
        results.append(r)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(rows)} done")

    out_lines = [json.dumps(r, ensure_ascii=False) for r in results]
    OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    # 집계
    n = len(results)
    store_yes = sum(1 for r in results if r["jev"].get("store") == "STORE")
    store_no = sum(1 for r in results if r["jev"].get("store") == "NO_STORE")
    type_dist = {}
    for r in results:
        t = r["jev"].get("type") or "?"
        type_dist[t] = type_dist.get(t, 0) + 1

    print(f"\n=== 결과 ({n}건) ===")
    print(f"store=STORE: {store_yes} ({store_yes/n*100:.1f}%)")
    print(f"store=NO_STORE: {store_no} ({store_no/n*100:.1f}%)")
    print("type 분포:", dict(sorted(type_dist.items(), key=lambda x: -x[1])))

    # 게이트 비교
    g1 = sum(1 for r in results if r["jev"].get("store") == "STORE")
    ga = sum(1 for r in results if r["jev"].get("store") == "STORE" and r["jev"].get("type") != "NO_STORE")
    gb = sum(1 for r in results
             if r["jev"].get("store") == "STORE"
             and r["jev"].get("type") != "NO_STORE"
             and (r["jev"].get("store_prob") or 0) >= 0.6)
    print(f"\n게이트 유지 비율:")
    print(f"  G1 (store==STORE):          {g1} ({g1/n*100:.1f}%)")
    print(f"  G-qual-a (store+type!=NO):  {ga} ({ga/n*100:.1f}%)")
    print(f"  G-qual-b (+conf≥0.6):       {gb} ({gb/n*100:.1f}%)")

    print("\n=== 유지 샘플 (G-qual-a, 5건) ===")
    kept = [r for r in results if r["jev"].get("store") == "STORE" and r["jev"].get("type") != "NO_STORE"][:5]
    for r in kept:
        print(f"  [{r['jev'].get('type')}] {r['utterance'][:100]}")

    print("\n=== 스킵 샘플 (G-qual-a, 5건) ===")
    skip = [r for r in results if not (r["jev"].get("store") == "STORE" and r["jev"].get("type") != "NO_STORE")][:5]
    for r in skip:
        print(f"  [{r['jev'].get('store')}/{r['jev'].get('type')}] {r['utterance'][:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())