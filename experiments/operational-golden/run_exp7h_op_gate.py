"""op 90건 full-text Winner Gate 적용 — hit@3 영향 실측 (2026-10-04)

목적: A choice가 op 90건에서 선택한 후보(gold_rank<=3 기준)에 full-text 게이트를
      적용하면 hit@3가 얼마나 깎이는지(또는 유지되는지) 실측.

절차:
1. exp7a A rerun raw에서 각 레코드의 선택(chosen) 후보 id 추출
   - abstain 10건 제외, non-abstain 80건
   - gold_rank<=3 (hit@3) 72건 + gold_rank>3 (miss) 8건
2. 각 선택 후보에 대해 full-text 게이트 1콜 (YES/NO)
3. 게이트 규칙 적용:
   - gate=YES → 주입 유지 (hit@3 그대로)
   - gate=NO & score>=θ → 주입 유지 (R2)
   - gate=NO & score<θ  → abstain (hit@3 손실)
4. score는 diag6_op_scores의 max_score 사용

비용: 80콜 FREE (non-abstain만)
출력: experiments/operational-golden/data/exp7h_op_gate_raw.json
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


def fetch_full(conn, rid):
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


def main():
    # exp7a A rerun에서 non-abstain 레코드 + 선택 후보
    a = json.load(open(os.path.join(DATA, "exp7a_A_rerun_raw.json"), encoding="utf-8"))
    recs = a["records"]
    op_ps = {r["qid"]: r.get("max_score") for r in json.load(open(os.path.join(DATA, "diag6_op_scores.json"), encoding="utf-8"))["records"]}

    # top1이 선택된 후보 id인지 확인 — exp7a에 chosen id가 있는가?
    print("exp7a keys:", list(recs[0].keys()))
    # top1 = chosen id?
    targets = []
    for r in recs:
        if r.get("abstain"):
            continue
        tid = r.get("top1")
        if not tid:
            continue
        targets.append({
            "qid": r["qid"],
            "query": r["query"],
            "cand_id": tid,
            "gold_rank": r.get("gold_rank"),
            "score": op_ps.get(r["qid"]),
            "hit3": r.get("gold_rank") is not None and r["gold_rank"] <= 3,
            "abstain_orig": False,
        })
    print(f"non-abstain 타깃: {len(targets)}건")
    # abstain 10건도 기록 (게이트 무관)
    abstain_n = sum(1 for r in recs if r.get("abstain"))
    print(f"원래 abstain: {abstain_n}건")

    # DB 연결
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    for t in targets:
        t["full"] = fetch_full(conn, t["cand_id"]) or ""
    conn.close()
    miss = sum(1 for t in targets if not t["full"])
    print(f"원문 미확보: {miss}건")

    key = resolve_key()
    if not key:
        print("EXPLABS_API_KEY 없음")
        return

    results = []
    def work(t):
        v, cost, err = gate_call(key, t["query"], t["full"], t["cand_id"])
        r = dict(t, verdict=v, err=err, cost=cost)
        print(f"  {t['qid']} rank={t['gold_rank']} → {v} (err={err})", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(work, targets):
            results.append(r)

    # 저장용 out
    out = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": MODEL,
        "prompt": PROMPT,
        "mode": "op-fulltext-gate",
        "n": len(results),
        "records": results,
    }
    with open(os.path.join(DATA, "exp7h_op_gate_raw.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {DATA}/exp7h_op_gate_raw.json")

    # 요약: 게이트 NO 비율 + R2(θ)별 hit@3
    no_n = sum(1 for r in results if r.get("verdict") == "NO")
    yes_n = sum(1 for r in results if r.get("verdict") == "YES")
    err_n = sum(1 for r in results if r.get("err"))
    base_hit3 = sum(1 for r in results if r.get("hit3"))
    print(f"\ngate: YES {yes_n} / NO {no_n} / err {err_n}")
    print(f"base hit@3 (게이트 없음): {base_hit3}/90 = {base_hit3/90*100:.1f}% (+abstain {abstain_n})")

    for th in [0.5, 0.6, 0.65, 0.7]:
        keep = 0
        for r in results:
            if r.get("verdict") == "NO" and (r.get("score") or 0) < th:
                continue  # abstain
            if r.get("hit3"):
                keep += 1
        print(f"  R2 θ={th}: hit@3 {keep}/90 ({keep/90*100:.1f}%)")


if __name__ == "__main__":
    main()