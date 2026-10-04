"""② 800자 초과 샘플 게이트 평가 — head-800 vs full-text 판정 비교 (2026-10-04)

실험 설계 (콜 절약):
- 910건 중 표본 30건 (op 15 + noans 15, 길이 층화) 
- 각 (query, cand)에 대해:
  a. head-800 게이트: content[:800]으로 "직접 답인가?" YES/NO
  b. full-text 게이트: content 전체(≤30k자 → 8000자 청크 전부 전달)로 동일 질문
- 판정 변화: head=NO & full=YES → 캡 손실 실측 (head-only의 위험)
          head=YES & full=NO → 캡이 오히려 도움 (잡음 제거)
- 에러: 후보가 너무 길어 API 한도 초과 시 분할 or 건너뜀

비용: 30×2 = 60콜 FREE (SmartRotator)
출력: experiments/operational-golden/data/exp8c_cap_eval_raw.json
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import winreg
import random
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "experiments/operational-golden"))
DATA = os.path.join(ROOT, "experiments/operational-golden/data")
URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
WORKERS = 3
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"

PROMPT = (
    "Does this memory directly state or entail the answer to the question? "
    "Answer YES if it contains the specific fact/value/rule the question asks for. "
    "Answer NO if it only shares the topic, related keywords, or background."
)

from keyring import SmartRotator
rot = SmartRotator()


def post(url, body, key, timeout=180.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    for attempt in range(6):
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                nk = rot.on_429()
                if nk:
                    key = nk
                    continue
                ra = e.headers.get("Retry-After")
                try:
                    wait = float(ra) if ra else 30.0
                except ValueError:
                    wait = 30.0
                print(f"    429 → {wait:.0f}s (attempt {attempt+1}/6)", flush=True)
                time.sleep(wait)
                continue
            return e.code, {"__msg": e.read().decode()[:200]}
        except Exception as e:
            if attempt == 5:
                return -1, {"__msg": f"{type(e).__name__}"}
            time.sleep(1.5)
    return 429, {"__msg": "rate limited"}


def gate_call(key, query, cand_text, mode):
    """mode: 'head800' | 'full'"""
    body = {
        "model": MODEL,
        "state": {"question": query, "candidate": cand_text},
        "questions": {
            "entails": {
                "type": "choice",
                "instructions": PROMPT,
                "criteria": {"c0": "YES", "c1": "NO"},
            }
        },
    }
    status, resp = post(URL, body, key)
    if status != 200:
        return None, None, f"http-{status}"
    cost = (resp.get("usage") or {}).get("cost", None)
    rot.set_cost(cost)
    ans = (resp.get("answers") or {}).get("entails") or {}
    ch = ans.get("choice")
    if ch is None:
        return None, cost, "no-choice"
    i = int(str(ch).lstrip("c"))
    if i == 0:
        return "YES", cost, None
    if i == 1:
        return "NO", cost, None
    return None, cost, f"bad-idx-{i}"


def main():
    pairs = json.load(open(os.path.join(DATA, "exp8b_over800_pairs.json"), encoding="utf-8"))
    print(f"800자 초과 쌍 {len(pairs)}건")

    # 길이 층화 샘플 30건 (op 15 + noans 15)
    rng = random.Random(20261004)
    op_pairs = [p for p in pairs if p["grp"] == "op"]
    noans_pairs = [p for p in pairs if p["grp"] == "noans"]
    # 길이로 정렬 후 층화
    op_pairs.sort(key=lambda p: p["cand_len"])
    noans_pairs.sort(key=lambda p: p["cand_len"])
    sample = []
    for src, n in [(op_pairs, 15), (noans_pairs, 15)]:
        if not src:
            continue
        idxs = sorted(rng.sample(range(len(src)), min(n, len(src))))
        for i in idxs:
            sample.append(src[i])
    print(f"샘플 {len(sample)}건 (op {sum(1 for s in sample if s['grp']=='op')} + noans {sum(1 for s in sample if s['grp']=='noans')})")

    results = []
    def work(p):
        q = p["query"]
        content = p["content"]
        # head-800 (단순 절단)
        head = content[:800]
        # full-text: 8000자까지 (API 한도 — 대부분 17K자라 8000으로 잘라도 답 유실 가능)
        full = content[:8000]
        key = rot.next()
        v_head, c1, e1 = gate_call(key, q, head, "head800")
        key = rot.next()
        v_full, c2, e2 = gate_call(key, q, full, "full")
        r = dict(p, head_verdict=v_head, full_verdict=v_full, errs=[e1, e2])
        # 판정 변화
        if v_head and v_full:
            if v_head == "NO" and v_full == "YES":
                r["change"] = "손실 (head NO → full YES)"
            elif v_head == "YES" and v_full == "NO":
                r["change"] = "잡음제거 (head YES → full NO)"
            else:
                r["change"] = "동일"
        else:
            r["change"] = f"err {e1}/{e2}"
        print(f"  {p['qid']} ({p['cand_len']}자): head={v_head} full={v_full} | {r['change']}", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(work, sample):
            results.append(r)

    # 집계
    from collections import Counter
    c = Counter(r.get("change") for r in results)
    print("\n=== 결과 ===")
    for k, v in c.items():
        print(f"  {k}: {v}건")
    loss = [r for r in results if r.get("change") == "손실 (head NO → full YES)"]
    if loss:
        print("\n[캡 손실 케이스]")
        for r in loss:
            print(f"  {r['grp']} {r['qid']} ({r['cand_len']}자): {r['head_verdict']}→{r['full_verdict']}")

    out = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": MODEL,
        "prompt": PROMPT,
        "mode": "cap-eval-head800-vs-full8000",
        "n": len(results),
        "records": results,
    }
    with open(os.path.join(DATA, "exp8c_cap_eval_raw.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {DATA}/exp8c_cap_eval_raw.json")


if __name__ == "__main__":
    main()