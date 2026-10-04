"""noans 6건 — choice 실제 선택 id로 full-text 게이트 재실행 (2026-10-04)

exp7f/exp7g의 noans 게이트는 pointwise top1(잘못된 대상)로 수행됨.
exp7d_choice_repro.json으로 choice 실제 선택 id를 복원했으니,
올바른 원문 전문(≤800자)으로 게이트 재판정.

비용: 6콜 FREE (0원)
출력: experiments/operational-golden/data/exp7i_noans_gate_fix_raw.json
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
DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
WORKERS = 3
GATE_LIMIT = 800  # 토큰 캡: 800자

PROMPT = (
    "Does this memory directly state or entail the answer to the question? "
    "Answer YES if it contains the specific fact/value/rule the question asks for. "
    "Answer NO if it only shares the topic, related keywords, or background."
)


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


def gate_call(key, query, full_text, cand_id):
    if len(full_text) > GATE_LIMIT:
        full_text = full_text[:GATE_LIMIT]  # 토큰 캡 800자
    body = {
        "model": MODEL,
        "state": {"question": query, "candidate": full_text, "candidate_id": cand_id},
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
    # choice 재현 결과 로드
    repro = json.load(open(os.path.join(DATA, "exp7d_choice_repro.json"), encoding="utf-8"))
    # exp7d raw에서 query 가져오기
    nd = json.load(open(os.path.join(DATA, "exp7d_fresh_noans_raw.json"), encoding="utf-8"))["records"]
    raw_by_qid = {r["qid"]: r for r in nd}

    # DB에서 원문
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    targets = []
    for r in repro:
        qid = r["qid"]
        full = None
        if r.get("chosen_id"):
            cur = conn.execute("SELECT content FROM working_memory WHERE id=?", (r["chosen_id"],))
            row = cur.fetchone()
            if row:
                full = row["content"]
            if full is None:
                cur = conn.execute("SELECT content FROM episodic_memory WHERE id=?", (r["chosen_id"],))
                row = cur.fetchone()
                if row:
                    full = row["content"]
        targets.append({
            "qid": qid,
            "query": raw_by_qid[qid]["query"],
            "cand_id": r.get("chosen_id"),
            "full": full or "",
        })
    conn.close()
    print(f"대상 {len(targets)}건 (choice 실제 선택, 원문 최대 {GATE_LIMIT}자)")

    key = resolve_key()
    if not key:
        print("EXPLABS_API_KEY 없음")
        return

    results = []
    def work(t):
        v, cost, err = gate_call(key, t["query"], t["full"], t["cand_id"])
        r = dict(t, verdict=v, err=err, cost=cost,
                 full_len=len(t["full"]), capped=len(t["full"]) > GATE_LIMIT)
        print(f"  {t['qid']} → {v} (err={err}, {len(t['full'])}자)", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(work, targets):
            results.append(r)

    out = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": MODEL,
        "prompt": PROMPT,
        "mode": "noans-choice-fix",
        "gate_limit": GATE_LIMIT,
        "n": len(results),
        "records": results,
    }
    with open(os.path.join(DATA, "exp7i_noans_gate_fix_raw.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {DATA}/exp7i_noans_gate_fix_raw.json")

    # noans 오주입: choice non-abstain 6건 중 gate NO가 abstain 처리 → FP 감소
    yes = sum(1 for r in results if r.get("verdict") == "YES")
    no = sum(1 for r in results if r.get("verdict") == "NO")
    print(f"\ngate: YES {yes} / NO {no} / err {sum(1 for r in results if r.get('err'))}")
    print(f"게이트 적용 후 noans FP: Ø(abstain {no}/6건) → 원래 6건 중 NO는 abstain 처리 시 FP {yes}/50")


if __name__ == "__main__":
    main()