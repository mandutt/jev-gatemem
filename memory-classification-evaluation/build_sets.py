"""Stage B/C: build calibration set (target ~400) and main evaluation set (~1500).

Sampling strategy (documented in SAMPLING.md):
- KoDialogBench : dialogue 내 발화를 task 파일별로 균등 추출 (구어체 단발화)
- KoSGD          : USER 턴 80% / SYSTEM 턴 20% (목적 지향 요청 중심)
- KoAlpaca       : instruction 필드만 (한국어 49,620개 중) — 명령형/요청 중심
- dedup          : 대화 ID(KDB) / utterance 해시(KoSGD, KoAlpaca)
- seed           : 고정 20260928 (재현 가능)

Calibration은 표현형(어미) 다양성 + semantic 후보 분포를 목표로 층화 추출:
  - 어미 클래스: ~줘 ~자 ~게 ~세요 ~해 ~해요 ~합니다 ~했어 ~했다 ~했는데 ~하자
                  ~하지마 ~하면좋겠어 ~했으면좋겠어 ~ㄴ지 ~ㄹ까 ~ㄴ가 ~냐 ~ㄴ데 ~다 ~니다 외
  - 출처별 비율: KoDialogBench 45% / KoSGD 35% / KoAlpaca 20%
"""
import json
import re
import hashlib
import random
import sys
import io
from pathlib import Path
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"C:\code\dataset\260928testdata")
OUT = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")
SEED = 20260928
rng = random.Random(SEED)

ENDING_CLASSES = [
    "줘", "자", "게", "세요", "해", "해요", "합니다", "했어", "했다", "했는데",
    "하자", "하지마", "하면좋겠어", "했으면좋겠어", "ㄴ지", "ㄹ까", "ㄴ가", "냐",
    "ㄴ데", "다", "니다", "어", "아", "지", "죠", "네요", "군요", "야", "이야", "거야",
]

def ending_class(u: str) -> str:
    u = u.strip().rstrip(".!?~ ")
    for e in ["했으면좋겠어", "하면좋겠어", "하지마", "했는데", "했습니다", "합니다", "세요", "해요", "좋겠어"]:
        if u.endswith(e):
            return e
    for e in ENDING_CLASSES:
        if u.endswith(e):
            return e
    return u[-2:] if len(u) >= 2 else u

# ---------- KoDialogBench ----------
def load_kdb():
    base = ROOT / "kodialogbench"
    recs = []  # (dialogue_id, speaker?, utterance, task, file)
    for f in sorted(base.rglob("*.jsonl")):
        task = str(f.relative_to(base)).replace("\\", "/")
        with open(f, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                dlg = r.get("dialogue")
                if not isinstance(dlg, list):
                    continue
                for j, turn in enumerate(dlg):
                    if not isinstance(turn, (list, tuple)) or len(turn) < 2:
                        continue
                    u = str(turn[1]).strip()
                    if not u or len(u) < 2:
                        continue
                    recs.append((f"{task}#{i}#{j}", u, "ko_dialog", task))
    return recs

# ---------- KoSGD ----------
def load_kosgd():
    base = ROOT / "kosgd" / "data" / "test"
    recs = []
    for f in sorted(base.glob("dialogues_*.json")):
        dlist = json.load(open(f, encoding="utf-8"))
        for d in dlist:
            did = d.get("dialogue_id", "?")
            for ti, t in enumerate(d.get("turns", [])):
                u = (t.get("utterance") or "").strip()
                if not u or len(u) < 2:
                    continue
                spk = t.get("speaker", "?")
                recs.append((f"{did}#{ti}", u, "ko_sgd", spk))
    return recs

# ---------- KoAlpaca ----------
def load_koalpaca():
    recs = []
    data = json.load(open(ROOT / "koalpaca" / "ko_alpaca_data.json", encoding="utf-8"))
    seen = set()
    for i, r in enumerate(data):
        u = (r.get("instruction") or "").strip()
        if not u or len(u) < 2:
            continue
        h = hashlib.md5(u.encode()).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        recs.append((f"koalpaca#{i}", u, "ko_alpaca", "instruction"))
    return recs


def build():
    kdb = load_kdb()
    kosgd = load_kosgd()
    koalpaca = load_koalpaca()
    print(f"candidates: kdb={len(kdb)} kosgd={len(kosgd)} koalpaca={len(koalpaca)}")

    # --- calibration: stratified by ending class + source ---
    cal_target = 400
    cal = []
    cal_ids = set()
    pools = {
        "ko_dialog": kdb,
        "ko_sgd": kosgd,
        "ko_alpaca": koalpaca,
    }
    source_quota = {"ko_dialog": 0.45, "ko_sgd": 0.35, "ko_alpaca": 0.20}

    # ending-stratified buckets
    buckets = defaultdict(list)  # (source, ending) -> recs
    for src, pool in pools.items():
        for rec in pool:
            buckets[(src, ending_class(rec[1]))].append(rec)
    # normalize keys (strip space)
    for src in pools:
        rng.shuffle(pools[src])

    ending_targets = [k for k in ENDING_CLASSES if k != "다"] + ["다", "니다", "어", "아", "지", "죠", "네요"]
    per_ending = max(2, cal_target // (len(ending_targets) * 3))
    for e in ending_targets:
        for src, frac in source_quota.items():
            bucket = buckets.get((src, e), [])
            src_n = max(1, int(per_ending * frac * 2))
            for rec in bucket[:src_n]:
                if len(cal) >= cal_target:
                    break
                if rec[0] in cal_ids:
                    continue
                cal_ids.add(rec[0])
                cal.append({"id": rec[0], "dataset": rec[2], "source": src,
                            "utterance": rec[1], "context": "", "task": rec[3],
                            "ending_class": e})
    # fill remainder randomly (balanced)
    for src, frac in source_quota.items():
        n = int((cal_target - len(cal)) * frac * 1.5)
        for rec in pools[src]:
            if n <= 0:
                break
            if rec[0] in cal_ids:
                continue
            cal_ids.add(rec[0])
            cal.append({"id": rec[0], "dataset": rec[2], "source": src,
                        "utterance": rec[1], "context": "", "task": rec[3],
                        "ending_class": ending_class(rec[1])})
            n -= 1
    cal = cal[:cal_target]

    # --- calibration: force-fill rare ending classes (줘/자/했어/좋겠어/하자/하지마 etc.) ---
    rare_targets = ["줘", "자", "했어", "했다", "좋겠어", "하자", "하지마", "했는데", "세요", "해요"]
    have_ending = Counter(ending_class(r["utterance"]) for r in cal)
    for e in rare_targets:
        need = 6 - have_ending.get(e, 0)
        if need <= 0:
            continue
        got = 0
        for src in ["ko_sgd", "ko_dialog", "ko_alpaca"]:
            # re-scan pools for this ending (pools already shuffled)
            for rec in pools[src]:
                if got >= need:
                    break
                if rec[0] in cal_ids:
                    continue
                if ending_class(rec[1]) != e:
                    continue
                cal_ids.add(rec[0])
                cal.append({"id": rec[0], "dataset": rec[2], "source": src,
                            "utterance": rec[1], "context": "", "task": rec[3],
                            "ending_class": e})
                got += 1
        # if still short, synthesize minimal generic utterances (agent-like)
        synth = {
            "줘": ["좋아 진행해줘.", "그걸로 해줘.", "확인해줘.", "이것도 해줘.", "계속 진행해줘.", "정리해서 보여줘."],
            "자": ["그걸로 가자.", "다음 단계로 넘어가자.", "이 방식으로 진행하자.", "일단 시작하자.", "계속하자."],
            "했어": ["오류가 발생했어.", "빌드가 실패했어.", "방금 수정했어.", "어제 적용했어.", "결과를 확인했어."],
            "했다": ["Rust로 결정했다.", "패치를 적용했다.", "어제 빌드했다.", "오류가 발생했다.", "문서를 업데이트했다."],
            "좋겠어": ["표로 정리하면 좋겠어.", "간단하게 하면 좋겠어.", "예제를 보여주면 좋겠어.", "테스트를 추가하면 좋겠어."],
            "하자": ["테스트는 pytest로 작성하자.", "모듈을 분리하자.", "로그를 추가하자.", "이 구조를 사용하자."],
            "하지마": ["Mnemosyne 내부를 수정하지마.", "Docker를 사용하지마.", "자동 배포하지마.", "코드를 복사하지마."],
            "했는데": ["수정했는데 여전히 안 돼.", "적용했는데 오류가 나.", "확인했는데 문제가 없어.", "바꿨는데 더 나빠졌어."],
            "세요": ["표로 정리해주세요.", "한국어로 답해주세요.", "간단하게 설명해주세요.", "다시 시도해주세요."],
            "해요": ["저는 표를 선호해요.", "이건 일회성이에요.", "계속 진행해요.", "오류가 반복돼요."],
        }
        for s in synth.get(e, [])[: need - got]:
            cal.append({"id": f"synth#{e}#{got}", "dataset": "synthetic", "source": "synthetic",
                        "utterance": s, "context": "", "task": "forced", "ending_class": e})
            got += 1
    cal = cal[:cal_target]

    # --- main set: stratified random from remaining (exclude cal ids) ---
    main_target = 1500
    main = []
    main_ids = set(cal_ids)
    quotas = {"ko_dialog": 0.45, "ko_sgd": 0.35, "ko_alpaca": 0.20}
    per_source = {src: int(main_target * frac) for src, frac in quotas.items()}
    for src, n in per_source.items():
        cnt = 0
        for rec in pools[src]:
            if cnt >= n:
                break
            if rec[0] in main_ids:
                continue
            main_ids.add(rec[0])
            main.append({"id": rec[0], "dataset": rec[2], "source": src,
                         "utterance": rec[1], "context": "", "task": rec[3],
                         "ending_class": ending_class(rec[1])})
            cnt += 1
    main = main[:main_target]

    # save
    with open(OUT / "CALIBRATION_SET.jsonl", "w", encoding="utf-8") as f:
        for r in cal:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(OUT / "EVALUATION_SET.jsonl", "w", encoding="utf-8") as f:
        for r in main:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"calibration: {len(cal)}")
    print(Counter(r["ending_class"] for r in cal).most_common(25))
    print(f"main: {len(main)}")
    print("main by dataset:", Counter(r["dataset"] for r in main))
    print("main by ending:", Counter(r["ending_class"] for r in main).most_common(15))


if __name__ == "__main__":
    build()