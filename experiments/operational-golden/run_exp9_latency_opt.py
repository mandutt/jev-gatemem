"""실측: 게이트 지연 최적화 — 병렬 발사 vs 동일 요청 2질문 (0원, exp8e 데이터 재사용)

목적 (8차 남은 과제 3): A(choice) + full-text 게이트를
  B. 동시 발사 (choice+gate 병렬) / C. 동일 요청 2질문 (1콜) 으로 묶었을 때
  판정 결과가 직렬(exp8e, A)과 일치하는지 + 지연이 얼마나 줄어드는지 실측.

방식:
  B: choice_call + gate_call을 ThreadPoolExecutor 2개로 동시 실행 (winner 무관 gate는 예비 후보)
     → 판정: choice winner + gate verdict (기존과 동일 조합)
  C: 한 body에 choice(winner) + entails(gate) 2개 questions → 1콜
     → 판정: 같은 2개 answers
  비교: A(exp8e의 verdict) vs B vs C — verdict 일치율 (gate YES/NO), winner 일치율

데이터: exp8e_400_gate_raw.json의 154건 (op 85 + lgo 55 + noans 14), winner_id/winner_score 재사용.
채택 조건 (사전 고정): verdict 일치율 >= 95% AND p50 지연이 직렬 대비 30%+ 감소.

주의: 데몬 무경유 직접 API (query_log/shadow 오염 없음). free 레인 병렬 2 + 60s 드레인.
"""
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "experiments", "operational-golden"))
from keyring import SmartRotator  # noqa: E402

DATA = os.path.join(ROOT, "experiments", "operational-golden", "data")
DB = os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db")
URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
GATE_LIMIT = 800
WORKERS = 2  # free 레인 안전값 (병렬 2)
CHOICE_PROMPT = (
    "Which memory is the best evidence for answering the question? "
    "Select the single most relevant candidate."
)
GATE_PROMPT = (
    "Does the candidate directly answer the question, or state the exact fact/rule/preference "
    "requested? Answer YES only if it does; NO if it is related but does not answer."
)

rot = SmartRotator()


def cap_window(text, limit=GATE_LIMIT):
    if not text:
        return ""
    if len(text) <= limit:
        return text
    head, tail = text[:600], text[-200:]
    return head + "\n...[truncated]...\n" + tail


def post(url, body, key, timeout=180.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    for attempt in range(6):
        try:
            t0 = time.perf_counter()
            resp = urllib.request.urlopen(req, timeout=timeout)
            lat = (time.perf_counter() - t0) * 1000
            return resp.status, json.loads(resp.read().decode()), lat
        except urllib.error.HTTPError as e:
            if e.code == 429:
                nk = rot.on_429()
                if nk:
                    key = nk
                    continue
                print(f"    429 → 60s (attempt {attempt+1}/6)", flush=True)
                time.sleep(60)
                continue
            return e.code, {"__msg": e.read().decode()[:200]}, 0.0
        except Exception as e:
            if attempt == 5:
                return -1, {"__msg": f"{type(e).__name__}"}, 0.0
            time.sleep(1.5)
    return 429, {"__msg": "rate limited"}, 0.0


def _parse_choice(ans, key):
    a = (ans or {}).get(key) or {}
    ch = a.get("choice")
    if ch is None:
        return None, None
    i = int(str(ch).lstrip("c"))
    probs = a.get("probabilities") or {}
    return i, probs


def choice_body(query, cands):
    # exp8d/8e와 동일한 choice body (400자 excerpt 후보)
    cand_list = [{"id": f"t{i}", "label": (c or "")[:400]} for i, c in enumerate(cands)]
    return {
        "model": MODEL,
        "state": {"query": query, "candidates": cand_list},
        "questions": {
            "choice": {
                "type": "choice", "instructions": CHOICE_PROMPT,
                "criteria": {f"c{i}": f"candidate {i}" for i in range(len(cands))},
            }
        },
    }


def gate_body(query, cand_text, cand_id):
    return {
        "model": MODEL,
        "state": {"question": query, "candidate": cand_text, "candidate_id": cand_id},
        "questions": {
            "entails": {
                "type": "choice", "instructions": GATE_PROMPT,
                "criteria": {"c0": "YES", "c1": "NO"},
            }
        },
    }


def combined_body(query, cands, cand_text, cand_id):
    """C: 한 요청에 choice + entails 2질문."""
    cand_list = [{"id": f"t{i}", "label": (c or "")[:400]} for i, c in enumerate(cands)]
    return {
        "model": MODEL,
        "state": {"query": query, "candidates": cand_list, "question": query,
                  "candidate": cand_text, "candidate_id": cand_id},
        "questions": {
            "choice": {
                "type": "choice", "instructions": CHOICE_PROMPT,
                "criteria": {f"c{i}": f"candidate {i}" for i in range(len(cands))},
            },
            "entails": {
                "type": "choice", "instructions": GATE_PROMPT,
                "criteria": {"c0": "YES", "c1": "NO"},
            },
        },
    }


def main():
    d = json.load(open(os.path.join(DATA, "exp8e_400_gate_raw.json"), encoding="utf-8"))
    recs = d["records"]
    print(f"exp8e records: {len(recs)}", flush=True)

    # DB 원문 로드 (winner_id → content)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    full_map = {}
    for r in recs:
        wid = r.get("winner_id")
        if not wid or wid in full_map:
            continue
        row = conn.execute("SELECT content FROM working_memory WHERE id=?", (wid,)).fetchone()
        if row:
            full_map[wid] = row["content"]
        else:
            row = conn.execute("SELECT content FROM episodic_memory WHERE id=?", (wid,)).fetchone()
            if row:
                full_map[wid] = row["content"]
    conn.close()
    print(f"full-text 로드: {len(full_map)}건", flush=True)

    # 후보 재구성 (exp8d 400자 pool) — exp8e raw에 pool이 없으므로 다시 만들 필요는 없음.
    # winner 검증용: gate는 winner_id의 원문에 대해 판정 → exp8e와 동일 대상.
    # (B/C 공통: gate 대상은 동일 winner_id)

    results = []

    def work_b(r):
        q = r["query"]
        wid = r["winner_id"]
        full = full_map.get(wid) or ""
        cand_text = cap_window(full)
        key = rot.next()
        # B: gate 단독 호출 (choice는 exp8d가 이미 수행 — 여기선 gate 지연만 측정.
        #  동시 발사 효과 = max(choice_p50 536ms, gate_p50) 로 오프라인 결합)
        v, cost, err, lat = gate_call(key, q, cand_text, wid)
        return {"grp": r["grp"], "qid": r["qid"], "mode": "B", "verdict": v,
                "err": err, "lat_ms": round(lat, 1), "baseline": r.get("verdict"),
                "winner_score": r.get("winner_score")}

    # B: 154건 (총 154콜, free 병렬 2)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(work_b, r) for r in recs if r.get("winner_id")]
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"err": f"future: {e}"})
            if i % 50 == 0:
                print(f"  진행 {i}/{len(futs)}", flush=True)

    # 저장
    out = os.path.join(DATA, "exp9_latency_opt_raw.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "mode": "B(parallel gate, choice already done)",
                   "note": "C(동일요청 2질문)는 systemone 1요청 1질문 제약으로 400 — 기각",
                   "n": len(results), "records": results}, f, ensure_ascii=False, indent=1)
    print(f"저장: {out}", flush=True)

    # 분석
    print("\n=== 분석 (B: gate 단독) ===")
    ms = [r for r in results if r.get("mode") == "B"]
    ok = [r for r in ms if r.get("verdict")]
    match = [r for r in ok if r["verdict"] == r.get("baseline")]
    lats = sorted(r["lat_ms"] for r in ms if r.get("lat_ms"))
    if lats:
        p50, p95 = lats[len(lats)//2], lats[int(len(lats)*0.95)]
    else:
        p50 = p95 = 0
    print(f"n={len(ms)} err={len(ms)-len(ok)} 일치 {len(match)}/{len(ok)} "
          f"({len(match)/max(len(ok),1):.1%}) p50={p50:.0f}ms p95={p95:.0f}ms")
    print("→ 동시 발사 예상 p50 = max(choice 536ms, gate {:.0f}ms) ≈ {:.0f}ms (직렬 1,271ms 대비)".format(
        p50, max(536, p50)))


def gate_call(key, query, cand_text, cand_id):
    body = gate_body(query, cand_text, cand_id)
    t0 = time.perf_counter()
    status, resp, lat = post(URL, body, key, timeout=30.0)
    if status != 200:
        return None, None, f"http-{status}", (time.perf_counter() - t0) * 1000
    ans = (resp.get("answers") or {}).get("entails") or {}
    ch = ans.get("choice")
    cost = (resp.get("usage") or {}).get("cost", None)
    rot.set_cost(cost)
    if ch is None:
        return None, cost, "no-choice", (time.perf_counter() - t0) * 1000
    i = int(str(ch).lstrip("c"))
    return ("YES" if i == 0 else "NO"), cost, None, (time.perf_counter() - t0) * 1000


if __name__ == "__main__":
    main()