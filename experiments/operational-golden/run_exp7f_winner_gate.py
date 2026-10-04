"""Winner Entailment Gate 파일럿 — "A(choice) 1위 후보가 질문의 직접 답인가" 1콜 검증 (2026-10-04)

배경: 0콜 파레토 분석(τ 게이트 기각) + a/c AI 공동 제안.
  A choice가 선택한 1위 후보에 대해, 질문-후보 쌍(pair)만으로
  "직접 답(direct answer)인가?"를 YES/NO로 판정하는 별도 Jev 콜.
  NO면 abstain(빈 컨텍스트) 처리 → hard-negative acceptance 감소 목표.

대상 43건 (기존 raw에서 추출, API 0콜로 선별):
- LGO (exp7b2) A choice non-abstain 37건: gold 제거 상태에서 그럴듯한 후보를 고른 것들
- fresh noans (exp7d) A choice FP 6건: 정답 없는데 후보를 고른 것들

판정 프롬프트 (문구 단순, gold 라벨 상태와 무관):
  "Does this memory directly state or entail the answer to the question?
   Answer YES if it contains the specific fact/value/rule the question asks for.
   Answer NO if it only shares the topic, related keywords, or background."
  criteria: c0=YES, c1=NO  (질문용 choice가 아닌 판정용 typed question)

측정:
- NO 비율 (거부율) — 높을수록 게이트가 잘 작동
- LGO: 37건 중 NO 개수 → acceptance 37 - NO (게이트 적용 후)
- noans: 6건 중 NO 개수 → FP 6 - NO (게이트 적용 후)
- 통과 기준 (a AI 제안): 43건 중 30건 이상(>70%) NO로 걸러내면 정식 채택 후보

비용: 43콜 FREE 레인 (0원)
출력: experiments/operational-golden/data/exp7f_winner_gate_raw.json
"""
import json
import os
import sys
import time
import sqlite3
import urllib.request
import urllib.error
import winreg
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "experiments/operational-golden/data")
LIVE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
WORKERS = 3
SLEEP = 0.0

PROMPT = (
    "Does this memory directly state or entail the answer to the question? "
    "Answer YES if it contains the specific fact/value/rule the question asks for. "
    "Answer NO if it only shares the topic, related keywords, or background."
)
LABELS = ["YES", "NO"]


def resolve_key():
    k = os.environ.get("EXPLABS_API_KEY", "")
    try:
        hk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        try:
            rk, _ = winreg.QueryValueEx(hk, "EXPLABS_API_KEY")
            if rk:
                k = rk
        finally:
            winreg.CloseKey(hk)
    except FileNotFoundError:
        pass
    return k.strip().strip('"')


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
                ra = e.headers.get("Retry-After")
                try:
                    wait = float(ra) if ra else 60.0
                except ValueError:
                    wait = 60.0
                print(f"    429 → {wait:.0f}s 드레인 (attempt {attempt+1}/6)", flush=True)
                time.sleep(wait)
                continue
            return e.code, {"__msg": e.read().decode()[:200]}
        except Exception as e:
            if attempt == 5:
                return -1, {"__msg": f"{type(e).__name__}"}
            time.sleep(1.5)
    return 429, {"__msg": "rate limited"}


def gate_call(key, query, cand_excerpt, cand_id):
    """Winner Entailment Gate: 질문 + 1위 후보 1건 → YES/NO"""
    body = {
        "model": MODEL,
        "state": {
            "question": query,
            "candidate": cand_excerpt,
            "candidate_id": cand_id,
        },
        "questions": {
            "entails": {
                "type": "choice",
                "instructions": PROMPT,
                "criteria": {"c0": LABELS[0], "c1": LABELS[1]},
            }
        },
    }
    status, resp = post(URL, body, key)
    if status != 200:
        return None, None, f"http-{status}"
    cost = (resp.get("usage") or {}).get("cost", None)
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
    if "--dry" in sys.argv:
        # 드라이런: 대상 43건 추출만 (API 0콜)
        targets = collect_targets()
        print(f"대상 {len(targets)}건:")
        for t in targets:
            print(f"  [{t['src']}] {t['qid']} | {(t['query'] or '')[:50]} | {(t['cand'] or '')[:60]}")
        return

    key = resolve_key()
    if not key:
        print("EXPLABS_API_KEY 없음")
        return
    targets = collect_targets()
    print(f"[{len(targets)}건] Winner Entailment Gate 시작 (FREE 레인)")

    results = []
    def work(t):
        verdict, cost, err = gate_call(key, t["query"], t["cand"], t["cand_id"])
        r = dict(t, verdict=verdict, err=err, cost=cost)
        print(f"  {t['qid']} → {verdict} (err={err})", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(work, targets):
            results.append(r)
            if SLEEP:
                time.sleep(SLEEP)

    # 측정
    lgo = [r for r in results if r["src"] == "lgo"]
    noans = [r for r in results if r["src"] == "noans"]
    lgo_no = sum(1 for r in lgo if r.get("verdict") == "NO")
    noans_no = sum(1 for r in noans if r.get("verdict") == "NO")
    lgo_err = sum(1 for r in lgo if r.get("err"))
    noans_err = sum(1 for r in noans if r.get("err"))

    print()
    print("=== 결과 ===")
    print(f"LGO  ({len(lgo)}건): NO {lgo_no} ({lgo_no/len(lgo)*100:.1f}%) | err {lgo_err}")
    print(f"  게이트 적용 후 acceptance: {len(lgo)-lgo_no}/{len(lgo)} ({ (len(lgo)-lgo_no)/len(lgo)*100:.1f}%)")
    print(f"noans({len(noans)}건): NO {noans_no} ({noans_no/len(noans)*100:.1f}%) | err {noans_err}")
    print(f"  게이트 적용 후 FP: {len(noans)-noans_no}/{len(noans)} ({ (len(noans)-noans_no)/len(noans)*100:.1f}%)")
    total_no = lgo_no + noans_no
    total = len(lgo) + len(noans)
    print(f"전체: NO {total_no}/{total} ({total_no/total*100:.1f}%)")
    print(f"통과 기준 (>70% NO): {'✓ 채택 후보' if total_no/total > 0.7 else '✗ 미달'}")

    out = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": MODEL,
        "prompt": PROMPT,
        "targets_total": total,
        "lgo_n": len(lgo), "lgo_no": lgo_no, "lgo_err": lgo_err,
        "noans_n": len(noans), "noans_no": noans_no, "noans_err": noans_err,
        "total_no": total_no,
        "pass_criteria": total_no / total > 0.7 if total else False,
        "records": results,
    }
    with open(os.path.join(DATA, "exp7f_winner_gate_raw.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {DATA}/exp7f_winner_gate_raw.json")


def collect_targets():
    """기존 raw에서 43건 추출: LGO choice non-abstain 37 + noans choice FP 6"""
    def load(f):
        d = json.load(open(os.path.join(DATA, f), encoding="utf-8"))
        return d["records"] if isinstance(d, dict) else d

    lgo_choice = load("exp7b2_lgo_choice_raw.json")
    noans = load("exp7d_fresh_noans_raw.json")

    targets = []
    for r in lgo_choice:
        if not r.get("abstain") and r.get("chosen"):
            targets.append({
                "src": "lgo",
                "qid": r["qid"],
                "query": r["query"],
                "cand": r.get("chosen_excerpt") or "",
                "cand_id": r.get("chosen"),
            })
    for r in noans:
        if not r.get("choice_abstain"):
            targets.append({
                "src": "noans",
                "qid": r["qid"],
                "query": r["query"],
                "cand": r.get("top1_excerpt") or "",
                "cand_id": None,
            })
    return targets


if __name__ == "__main__":
    main()