#!/usr/bin/env python3
"""실험 2-15: 외부 데이터셋(KoSGD/KoAlpaca) v4 오탐 스캔 + A/B/C 조정안 기존 메모리 시뮬레이션.

결론 (2026-09-28):
  1. KoSGD 84,594 대화 발화에서 v4 SKIP 1.2% (1022건) — 대부분 '할게' TP (의사 결정)
  2. KoAlpaca 2,000 서술형 output에서 SKIP 0.5% (10건) — '구축하/정리하/할게' 오탐 (지식 서술)
  3. A/B/C 조정안을 gold50+ctx17 (실게이트 전체 로직, JEV 분류 포함)에 시뮬레이션:
     - A+B (구축하 제외, 정리하겠): gold50 성능 변화 0 (prec 0.684 유지)
     - A+B+C (할게 맥락제한): gold50 prec 0.684 -> 0.632 (악화, TP 82901 손실)
     - ctx17: 모든 안에서 prec=rec=1.000 유지
  4. 결론: 외부 데이터셋 오탐은 "문서 서술 도메인" 한정 — 실제 assistant 대화 발화와 분포 다름.
     A/B는 기존 메모리 영향 0, C는 악화. → 규칙 변경 없음 (현재 v4 유지).

결정: 규칙 변경 없음. 본 리포트 = 근거 기록용.
"""
import json
import re
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "memory-classification-evaluation" / "data"
INPUT_JSON = Path(__file__).resolve().parent / "exp2_14_dataset_scan_input.json"

# ---- v4 규칙 (write_gate.py와 동일) ----
KNOWLEDGE = re.compile(r"(검증|확인|조사|분석|테스트|정밀|확정|검토|추정|판단|파악|실측|분해|라이브|확보)")
OPERATION = re.compile(r"(백업|설치|스왑|설정|복구|적용|구축|등록|이관|모니터링|cron)")
TRANSITION = re.compile(r"(정상|감지|동작|완료|완성|등록|파악).{0,40}(이제|다음|그럼)")
INTENT_V4 = re.compile(r"(진행하겠|만들겠|구축하|정리하|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠|시작하겠|세겠습니다)")
# 조정안
INTENT_AB = re.compile(r"(진행하겠|만들겠|정리하겠|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠|시작하겠|세겠습니다)")
INTENT_ABC = re.compile(
    r"(진행하겠|만들겠|정리하겠|작성하겠|등록하겠|돌릴게|해볼게|적용하겠|시작하겠|세겠습니다"
    r"|(?:그걸로|이걸로|그것으로|그것|이것|바로|다시)\s*할게(?:요)?)"
)


def load_set(jsonl_f: str, json_f: str) -> list:
    items = [json.loads(line) for line in open(DATA / jsonl_f, encoding="utf-8")]
    golds = list(json.load(open(DATA / json_f, encoding="utf-8"))["verdicts"].values())
    assert len(golds) == len(items), f"{jsonl_f} mismatch"
    for it, g in zip(items, golds):
        it["gold"] = g
    return items


def gate_keep(items: list, intent_re) -> tuple:
    """실게이트 전체 재현: JEV 분류(jsonl의 jev_store/jev_type) + v4 필터."""
    tp = fp = tn = fn = 0
    for it in items:
        gold_store = it.get("gold") == "store"
        js, jt = it.get("jev_store", ""), it.get("jev_type", "")
        if js == "STORE" and jt != "context":
            sk = jt == "commitment" and bool(intent_re.search(it["utterance"]))
        elif js in ("STORE", "NO_STORE"):
            sk = True
        else:
            sk = False
        if sk and not gold_store:
            tp += 1
        elif sk and gold_store:
            fn += 1
        elif not sk and gold_store:
            tn += 1
        else:
            fp += 1
    return tp, fp, tn, fn


def summarize(name: str, items: list, intent_re) -> None:
    tp, fp, tn, fn = gate_keep(items, intent_re)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    print(f"{name}: prec={prec:.3f} rec={rec:.3f} F1={f1:.3f} (TP={tp} FP={fp} TN={tn} FN={fn})")


def main() -> None:
    print("========== 외부 데이터셋 스캔 (exp2_14 입력 재사용) ==========")
    data = json.load(open(INPUT_JSON, encoding="utf-8")) if INPUT_JSON.exists() else {}
    for ds, key in (("KoSGD(대화)", "kosgd"), ("KoAlpaca(서술)", "koalpaca")):
        utts = data.get(key, [])
        c = Counter()
        for u in utts:
            if KNOWLEDGE.search(u[:200]):
                c["KEEP-knowledge"] += 1
            elif TRANSITION.search(u) and OPERATION.search(u):
                c["SKIP-transition"] += 1
            elif INTENT_V4.search(u):
                c["SKIP-intent"] += 1
            else:
                c["KEEP-other"] += 1
        print(f"\n[{ds}] n={len(utts)}")
        for k, v in c.most_common():
            print(f"  {k}: {v} ({v / len(utts):.1%})")

    print("\n========== A/B/C 조정안 — 기존 메모리 시뮬레이션 ==========")
    g50 = load_set("ab_assistant_gold50.jsonl", "ab_assistant_gold50.json")
    ctx = load_set("ab_assistant_ctx17.jsonl", "ab_assistant_ctx17.json")
    for label, items in (("gold50", g50), ("ctx17", ctx)):
        print(f"\n[{label}]")
        summarize("현재 v4", items, INTENT_V4)
        summarize("A+B", items, INTENT_AB)
        summarize("A+B+C", items, INTENT_ABC)


if __name__ == "__main__":
    main()