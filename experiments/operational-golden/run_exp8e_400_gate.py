"""400자 A + full-text 게이트 결합 검증 (2026-10-04)

목적: exp8d(400자 excerpt)의 winner에 full-text 게이트를 적용해
      리콜(88.9%)과 정밀도(noans/lgo 방어)를 동시에 얻는지 실측.

대상: exp8d_excerpt400_raw.json의 non-abstain winner 전부
  - op 85건 + lgo 55건 + noans 14건 = 154건
  각 winner 원문(≤800자, head+tail window) → "직접 답인가?" YES/NO 1콜

분석:
  - 게이트 NO 비율 (전체/그룹별)
  - R2 (winner_score < θ → abstain) 결합 시 op hit@3 / noans / lgo 변화
    - winner_score는 exp8d에 없으므로 exp8a의 winner_score를 qid로 매칭 (같은 코퍼스)
  - 100자 A vs 400자 A vs 400자 A+게이트 최종 비교

비용: 154콜 FREE (SmartRotator)
출력: experiments/operational-golden/data/exp8e_400_gate_raw.json
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
sys.path.insert(0, os.path.join(ROOT, "experiments/operational-golden"))
DATA = os.path.join(ROOT, "experiments/operational-golden/data")
DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
WORKERS = 3
GATE_LIMIT = 800

PROMPT = (
    "Does this memory directly state or entail the answer to the question? "
    "Answer YES if it contains the specific fact/value/rule the question asks for. "
    "Answer NO if it only shares the topic, related keywords, or background."
)

from keyring import SmartRotator
rot = SmartRotator()
print("키 상태:", rot.stats(), flush=True)


def cap_window(text, limit=GATE_LIMIT):
    """head 600 + tail 200 = 800자 window (⑥ 교훈 반영)"""
    if len(text) <= limit:
        return text
    head = text[:600]
    tail = text[-200:]
    return head + "\n...[중략]...\n" + tail


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


def gate_call(key, query, cand_text, cand_id):
    body = {
        "model": MODEL,
        "state": {"question": query, "candidate": cand_text, "candidate_id": cand_id},
        "questions": {
            "entails": {
                "type": "choice",
                "instructions": PROMPT,
                "criteria": {"c0": "YES", "c1": "NO"},
            }
        },
    }
    t0 = time.perf_counter()
    status, resp = post(URL, body, key)
    lat = (time.perf_counter() - t0) * 1000
    if status != 200:
        return None, None, f"http-{status}", lat
    cost = (resp.get("usage") or {}).get("cost", None)
    rot.set_cost(cost)
    ans = (resp.get("answers") or {}).get("entails") or {}
    ch = ans.get("choice")
    if ch is None:
        return None, cost, "no-choice", lat
    i = int(str(ch).lstrip("c"))
    if i == 0:
        return "YES", cost, None, lat
    if i == 1:
        return "NO", cost, None, lat
    return None, cost, f"bad-idx-{i}", lat


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
    # exp8d 400자 결과
    d = json.load(open(os.path.join(DATA, "exp8d_excerpt400_raw.json"), encoding="utf-8"))
    recs = d["records"]

    # query 복원 (exp8d는 query 미저장 — 소스 데이터에서)
    qmap = {}
    op_all = json.load(open(os.path.join(DATA, "golden_eval_v2.json"), encoding="utf-8"))
    for x in op_all:
        if x.get("gold_id"):
            qmap[x["gold_id"]] = x["query"]
    noans_all = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
    for x in noans_all:
        qmap[x.get("qid")] = x["query"]
    for r in recs:
        r["query"] = qmap.get(r["qid"], "")
    missing = sum(1 for r in recs if not r.get("query"))
    print(f"query 복원: {len(recs)}건, 미복원 {missing}건", flush=True)
    # exp8a winner_score 매칭용 (같은 코퍼스)
    a = json.load(open(os.path.join(DATA, "exp8a_rerun_choice_winner.json"), encoding="utf-8"))
    a_recs = a["records"]

    # qid+grp → winner_score 매핑 (exp8a에서)
    score_map = {}
    for r in a_recs:
        if r.get("winner_score") is not None:
            score_map[(r["grp"], r["qid"])] = r["winner_score"]

    # 400자 non-abstain winner
    targets = []
    for r in recs:
        if r.get("choice_abstain") or not r.get("winner_id"):
            continue
        targets.append(r)
    print(f"400자 non-abstain: {len(targets)}건 (op {sum(1 for t in targets if t['grp']=='op')} + lgo {sum(1 for t in targets if t['grp']=='lgo')} + noans {sum(1 for t in targets if t['grp']=='noans')})")

    # DB 원문 — 메인 스레드에서 미리 로드 (스레드 안전)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    full_map = {}
    for r in targets:
        if r.get("winner_id") and r["winner_id"] not in full_map:
            cur = conn.execute("SELECT content FROM working_memory WHERE id=?", (r["winner_id"],))
            row = cur.fetchone()
            if row:
                full_map[r["winner_id"]] = row["content"]
            else:
                cur = conn.execute("SELECT content FROM episodic_memory WHERE id=?", (r["winner_id"],))
                row = cur.fetchone()
                if row:
                    full_map[r["winner_id"]] = row["content"]
    conn.close()

    results = []
    def work(r):
        q = r["query"]
        full = full_map.get(r["winner_id"]) or ""
        cand_text = cap_window(full)  # head 600 + tail 200
        key = rot.next()
        v, cost, err, lat = gate_call(key, q, cand_text, r["winner_id"])
        ws = score_map.get((r["grp"], r["qid"]))
        res = dict(r, verdict=v, gate_err=err, lat_ms=round(lat, 1),
                   full_len=len(full), capped=len(full) > 800, winner_score=ws)
        print(f"  [{r['grp']}] {r['qid']} → {v} (err={err}, {len(full)}자, score={ws})", flush=True)
        return res

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(work, targets):
            results.append(r)

    # 저장
    out = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": MODEL,
        "mode": "excerpt400 + fulltext-gate",
        "gate_limit": GATE_LIMIT,
        "cap_mode": "head600+tail200",
        "n": len(results),
        "records": results,
    }
    with open(os.path.join(DATA, "exp8e_400_gate_raw.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {DATA}/exp8e_400_gate_raw.json")

    # 요약
    for grp in ["op", "lgo", "noans"]:
        sub = [r for r in results if r["grp"] == grp]
        if not sub:
            continue
        yes = sum(1 for r in sub if r.get("verdict") == "YES")
        no = sum(1 for r in sub if r.get("verdict") == "NO")
        err = sum(1 for r in sub if r.get("gate_err"))
        print(f"{grp}: {len(sub)}건 | YES {yes} | NO {no} | err {err}")

    # R2 결합: gate NO & winner_score < θ → abstain
    print("\n=== R2 결합 시뮬레이션 (gate NO & score < θ → abstain) ===")
    for th in [0.3, 0.4, 0.5, 0.6]:
        # op
        op_sub = [r for r in results if r["grp"] == "op"]
        h3 = sum(1 for r in op_sub
                 if not (r.get("verdict") == "NO" and (r.get("winner_score") or 0) < th)
                 and r.get("gold_rank") is not None and r["gold_rank"] <= 3)
        # noans
        n_sub = [r for r in results if r["grp"] == "noans"]
        n_inject = sum(1 for r in n_sub
                       if not (r.get("verdict") == "NO" and (r.get("winner_score") or 0) < th))
        # lgo
        l_sub = [r for r in results if r["grp"] == "lgo"]
        l_inject = sum(1 for r in l_sub
                       if not (r.get("verdict") == "NO" and (r.get("winner_score") or 0) < th))
        print(f"θ={th}: op hit@3 {h3}/90 ({h3/90*100:.1f}%) | noans 주입 {n_inject}/50 ({n_inject/50*100:.1f}%) | lgo 주입 {l_inject}/90 ({l_inject/90*100:.1f}%)")


if __name__ == "__main__":
    main()