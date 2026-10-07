"""Winner Gate 원문 전문 재실험 — excerpt 80자 vs 원문 전문 판정 비교 (2026-10-04)

배경: 사용자 지적 "100자 내외 잘린 상태로는 사람도 판단 어려움 → 게이트도 동일"
- exp7f는 excerpt 평균 79자로 판정. 35/43건이 원문보다 잘림.
- 잘린 꼬리에 답이 있는 사례 실재 (a112c8b5, e941022a, c69c459c 등)

이번 실험: 동일 43건을 **원문 전문**으로 gate 재판정 (같은 프롬프트)
- 비교: excerpt 판정(기존) vs full-text 판정(신규) → 판정 변화율
- 목표: 게이트의 추천 로직이 full-text 기준으로도 유효한지 (사람 판정과의 일치율 변화)

비용: 43콜 FREE 레인 (0원)
출력: experiments/operational-golden/data/exp7g_gate_fulltext_raw.json
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


def gate_call(key, query, full_text, cand_id):
    """게이트: 질문 + 원문 전문 → YES/NO"""
    body = {
        "model": MODEL,
        "state": {
            "question": query,
            "candidate": full_text,
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
        targets = collect_targets()
        print(f"대상 {len(targets)}건 (full-text 재판정)")
        for t in targets:
            print(f"  [{t['src']}] {t['qid']} | full {len(t['full'])}자 | old_gate={t['old_gate']}")
        return

    key = resolve_key()
    if not key:
        print("EXPLABS_API_KEY 없음")
        return
    targets = collect_targets()
    print(f"[{len(targets)}건] full-text gate 재판정 (FREE 레인)")

    results = []
    def work(t):
        verdict, cost, err = gate_call(key, t["query"], t["full"], t["cand_id"])
        changed = "?" if t["old_gate"] == "?" else ("CHANGED" if verdict != t["old_gate"] else "same")
        r = dict(t, new_verdict=verdict, err=err, cost=cost, changed=changed)
        print(f"  {t['qid']} → {verdict} ({changed})", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(work, targets):
            results.append(r)
            time.sleep(0)

    # 집계
    changed = [r for r in results if r.get("changed") == "CHANGED"]
    same = [r for r in results if r.get("changed") == "same"]
    errs = [r for r in results if r.get("err")]
    print()
    print("=== 결과 ===")
    print(f"변화: {len(changed)} CHANGED / {len(same)} same / {len(errs)} err")
    for r in changed:
        print(f"  CHANGED {r['qid']}: {r['old_gate']} → {r['new_verdict']}")
    # 오탐(사람 VALID + old NO)이 full-text에서 YES로 바뀌는지
    vp = os.path.expandvars(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\wgate_3class_verdicts.json")
    v = json.load(open(vp, encoding="utf-8"))
    hm = {v[i]["idx"]: v[i]["v"] for i in range(len(v))}
    for r in results:
        r["human"] = hm.get(r["idx"])  # idx 기준? qid 기준으로
    # qid 기준 매핑이 안전 — 아래에서 idx로 재매핑
    # exp7f와 동일 순서 가정 — collect_targets가 동일 순서 유지

    out = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": MODEL,
        "prompt": PROMPT,
        "mode": "full-text",
        "n": len(results),
        "changed": len(changed),
        "same": len(same),
        "err": len(errs),
        "records": results,
    }
    with open(os.path.join(DATA, "exp7g_gate_fulltext_raw.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"저장: {DATA}/exp7g_gate_fulltext_raw.json")


def collect_targets():
    """exp7f 대상 43건 + DB 원문 전문 → 게이트 재판정"""
    d = json.load(open(os.path.join(DATA, "exp7f_winner_gate_raw.json"), encoding="utf-8"))
    recs = d["records"]

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    def fetch_full(rid):
        if not rid:
            return None
        cur = conn.execute("SELECT content FROM working_memory WHERE id=?", (rid,))
        r = cur.fetchone()
        if r:
            return r["content"]
        cur = conn.execute("SELECT content FROM episodic_memory WHERE id=?", (rid,))
        r = cur.fetchone()
        if r:
            return r["content"]
        return None

    targets = []
    for i, r in enumerate(recs):
        full = fetch_full(r.get("cand_id"))
        if full is None:
            full = r.get("cand") or ""  # noans 등 fallback
        targets.append({
            "idx": i,
            "src": r["src"],
            "qid": r["qid"],
            "query": r["query"],
            "cand_id": r.get("cand_id"),
            "old_gate": r.get("verdict", "?"),
            "full": full,
            "old_excerpt_len": len(r.get("cand") or ""),
        })
    conn.close()
    return targets


if __name__ == "__main__":
    main()