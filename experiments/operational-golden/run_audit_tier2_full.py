"""실측: audit Tier 2 전체 코퍼스 파일럿 — 의미적 모순 스윕 전수 (free 레인)

대상: working_memory 전체 (probe에서 평가한 40건 제외)
프로토콜: probe와 동일 (utterance 120자 + 후보 3건 어휘 유사)
  - 후보: 같은 어휘 공유하는 다른 행, 상위 3건 (유사도>0.1)
  - 질문: stale choice (c0 라이브 / c1 stale)
  - 판정: prob_stale >= 0.5 → STALE (probe와 동일 기준)

운영:
  - 병렬 3 (free 레인 240/분, 안전 ~150콜/분)
  - 체크포인트 재개: 완료 레코드를 raw json에 원자 저장 (중단 시 이어가기)
  - 게이트: 429 드레인 60s 대기 / 5xx 재시도 1회 / 연속 에러 10회 → 중단
  - 스모크: 배치 시작 전 1콜 (200 확인)
raw 저장: experiments/operational-golden/audit_tier2_full_raw.json
"""
import json
import os
import re
import sqlite3
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT = os.path.join(ROOT, "experiments", "operational-golden", "audit_tier2_full_raw.json")

try:
    import httpx
except ImportError:
    print("httpx 없음 — jev-mem venv python으로 실행")
    sys.exit(2)

API_URL = os.environ.get("JEV_API_URL", "https://api.experientiallabs.ai/v1/systemone")
API_KEY = os.environ.get("EXPLABS_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
PARALLEL = 2  # free 레인 240/분 — 병렬 3이면 429 폭주 (실측: 200건 후 429 루프)
STALE_THRESHOLD = 0.5
MAX_CONSEC_ERRORS = 10
SMOKE = "--smoke" in sys.argv
FORCE = "--force" in sys.argv
LIMIT = None
for a in sys.argv:
    if a.startswith("--limit="):
        LIMIT = int(a.split("=")[1])

_client = None


def get_client():
    global _client
    if _client is None:
        # hang 방지: connect/read 타임아웃 분리 + 429 드레인 60s 금지 (20s로)
        _client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
    return _client


def post_systemone(utterance: str, candidates: list, timeout: float = 20.0):
    cands = [{"id": f"t{i}", "label": (c or "")[:800]} for i, c in enumerate(candidates)]
    body = {
        "model": "jev-latest",
        "state": {"utterance": utterance[:120], "candidates": cands},
        "questions": {
            "stale": {
                "type": "choice",
                "instructions": (
                    "The memory is the current query. A newer memory may replace or contradict it. "
                    "Decide whether any candidate is a newer memory that supersedes this one."
                ),
                "criteria": {
                    "c0": "Live — no candidate replaces or contradicts this memory",
                    "c1": "Stale — a candidate replaces or contradicts this memory",
                },
            }
        },
    }
    r = get_client().post(API_URL, json=body, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=timeout)
    return r


def sim(a, b):
    sa, sb = set(re.findall(r"\w+", (a or "").lower())), set(re.findall(r"\w+", (b or "").lower()))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def load_rows():
    db = os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT id, content, session_id, timestamp, memory_type FROM working_memory"
    ).fetchall()
    con.close()
    return rows


def pick_candidates(rows, rid, content, n=3):
    others = [r for r in rows if r[0] != rid]
    scored = sorted(others, key=lambda r: sim(content, r[1]), reverse=True)
    cands = []
    for r in scored:
        if sim(content, r[1]) > 0.1 and len(cands) < n:
            cands.append((r[0], (r[1] or "")[:120]))
        if len(cands) >= n:
            break
    return [c[1] for c in cands], [c[0] for c in cands]


def evaluate_one(rid, content, rows):
    utt_cands, cand_ids = pick_candidates(rows, rid, content)
    if not utt_cands:
        return {"id": rid, "verdict": "SKIP_NO_CANDIDATES", "reason": "유사 후보 없음",
                "latency_ms": 0, "status": 200}
    try:
        r = post_systemone(content, utt_cands)
    except Exception as e:
        return {"id": rid, "verdict": "ERROR", "error": str(e)[:200], "status": 0}
    lat = r.elapsed.total_seconds() * 1000
    if r.status_code != 200:
        return {"id": rid, "verdict": "ERROR", "status": r.status_code,
                "error": r.text[:200], "latency_ms": lat}
    body = r.json()
    ans = (body.get("answers") or {}).get("stale") or {}
    choice = ans.get("choice")
    probs = ans.get("probabilities") or {}
    p_stale = probs.get("c1") or 0.0
    verdict = "STALE" if p_stale >= STALE_THRESHOLD else "LIVE"
    return {"id": rid, "verdict": verdict, "choice": choice, "prob_stale": p_stale,
            "candidate_ids": cand_ids, "latency_ms": lat, "status": 200}


def _save(path, records, threshold):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"),
                   "threshold": threshold, "api": API_URL, "records": records},
                  f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def main():
    if not API_KEY:
        print("API key 없음 — 중단")
        return 1

    rows = load_rows()
    print(f"전체 {len(rows)} 행")

    # 기존 진행 복구 (체크포인트)
    done_ids = set()
    if os.path.exists(OUT) and not FORCE:
        try:
            old = json.load(open(OUT, encoding="utf-8"))
            done_ids = {r["id"] for r in old["records"] if r.get("status") == 200}
            print(f"체크포인트: {len(done_ids)}건 완료 — 이어가기")
        except Exception:
            done_ids = set()

    queue = [r for r in rows if r[0] not in done_ids]
    if LIMIT:
        queue = queue[:LIMIT]
    print(f"대상 {len(queue)}건")

    # 스모크
    if SMOKE:
        sample = rows[0]
        r = post_systemone(sample[1], ["smoke"], timeout=20.0)
        print(f"[스모크] status={r.status_code}")
        if r.status_code == 200:
            print("  answers:", (r.json().get("answers") or {}))
            return 0
        print("  body:", r.text[:300])
        return 1

    # 전체 행 캐시 (후보 선택용)
    all_rows = rows

    records = list(done_ids and (json.load(open(OUT, encoding="utf-8"))["records"]) or [])
    consec_errors = 0
    t0 = time.time()
    n_ok = n_stale = n_skip = n_err = 0

    # 병렬 처리 — hang 방지: daemon 스레드 + wait=False 종료.
    # API가 특정 요청에 응답을 안 주면(연결 유지+데이터 무응답) httpx 20s도 안 터지고
    # 스레드가 영구 점유 → shutdown(wait=True)가 hang. daemon 스레드로 격리.
    stales = 0
    ex = ThreadPoolExecutor(max_workers=PARALLEL, thread_name_prefix="jev-batch")
    try:
        futs = {ex.submit(evaluate_one, rid, content, all_rows): rid
                for rid, content, _, _, _ in queue}
        batch_budget = 300
        processed = 0
        while futs and processed < batch_budget:
            try:
                for fut in as_completed(futs, timeout=90):
                    rid = futs.pop(fut)
                    processed += 1
                    try:
                        rec = fut.result()
                    except Exception as e:
                        rec = {"id": rid, "verdict": "ERROR", "error": f"future: {e}", "status": 0}
                    records.append(rec)
                    if rec["verdict"] == "ERROR":
                        n_err += 1
                        consec_errors += 1
                        if rec.get("status") == 429:
                            print(f"  429 — 60s 드레인 (진행 {processed}/{len(queue)}) 429누적={n_err}")
                            time.sleep(60)
                            consec_errors = 0
                            # rate limit은 분 단위 — 60s 후에도 계속 429면 (연속 20회) 배치 종료
                            if n_err >= 20:
                                print("  429 연속 20회 — rate limit 지속, 배치 종료 (다음 재개에서 이어가기)")
                                futs.clear()
                                break
                        if consec_errors >= MAX_CONSEC_ERRORS:
                            print(f"  연속 에러 {consec_errors} — 중단")
                            futs.clear()
                            break
                    else:
                        consec_errors = 0
                        if rec["verdict"] == "STALE":
                            n_stale += 1
                        elif rec["verdict"] == "SKIP_NO_CANDIDATES":
                            n_skip += 1
                        else:
                            n_ok += 1
                    if processed % 100 == 0:
                        _save(OUT, records, STALE_THRESHOLD)
                        dt = time.time() - t0
                        print(f"  [{processed}/{len(queue)}] ok={n_ok} stale={n_stale} skip={n_skip} err={n_err} "
                              f"{dt:.0f}s ({(processed/dt):.1f}/s)")
                    if processed >= batch_budget:
                        break
            except TimeoutError:
                print(f"  [timeout] 90s 내 미완료 {len(futs)}건 — 남은 건 재개에서 처리")
                futs.clear()  # while 탈출: 남은 future는 다음 재개가 처리
                break
    finally:
        # 중요: wait=False — 미완료(데드) future를 기다리지 않음.
        ex.shutdown(wait=False, cancel_futures=True)

    # 최종 저장
    _save(OUT, records, STALE_THRESHOLD)
    print(f"\n완료 — {OUT}")
    print(f"ok={n_ok} stale={n_stale} skip={n_skip} err={n_err} 총 {len(records)}")
    import os as _os
    # non-daemon 워커(API 무응답으로 데드)가 살아있으면 프로세스가 종료되지 않음
    # → 체크포인트 저장 후 강제 종료. 남은 작업은 다음 재개가 처리.
    _os._exit(0)


if __name__ == "__main__":
    sys.exit(main())