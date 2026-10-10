# -*- coding: utf-8 -*-
"""stage110_lmev_smoke.py — LongMemEval-S 스모크: 3문항 ingest + JEV choice + reader (2026-10-10)

설계 문서: docs/longmemeval/2026-10-10_longmemeval-design.md (사용자 승인 2026-10-10)

목적 (스모크 단계):
  1. ingest 시간 실측 (문항당 491턴 평균 → 500문항 전체 소요 산정)
     - mnemosyne Memory(임시 DB)에 remember() 1콜/턴 (임베딩 포함, 0 JEV 콜)
  2. JEV choice 1콜/문항 latency 분포 (직렬 vs 병렬 워커 결정)
  3. reader(deepcombo) 응답 sanity + judge(deepcombo) yes/no 판정 sanity
  4. 키 상태 확인: EXPLABS 2키 (xpl_)만 사용, TYPESAFE/과금 경로 금지

데이터 격리 (라이브 데몬 무영향):
  - 라이브 DB(%LOCALAPPDATA%/jev-mem/mnemosyne.db) 접근 없음 — 임시 DB만 사용
  - 데몬 프로세스 kill/재시작 없음, core.json/config.yaml/HKCU 수정 없음

실행: python stage110_lmev_smoke.py [--limit N] [--no_reader]
"""
import os, sys, json, time, argparse, tempfile, sqlite3, threading
from collections import Counter

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client
import stage48_live60_cross as m48

# ---------- 데이터 격리: JEV_REG_DISABLE로 sitecustomize 강제 우회 금지 ----------
# (다만 스모크는 라이브 venv가 아닌 Hermes venv 파이썬으로 실행 — daemon venv 그대로 두고
#  mnemosyne 라이브러리를 로드하되, 임베딩은 daemon venv의 캐시를 재사용)

DATA_DIR = os.path.join(REPO, "experiments", "operational-golden", "data")
LMEV_DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"
OUT = os.path.join(DATA_DIR, "stage110_smoke_results.json")

# ---------- JEV 키: EXPLABS 2키만 (사용자 지시 2026-10-10) ----------
def _load_jev_keys():
    """HKCU\\Environment에서 EXPLABS 키만 로드 (레지스트리가 source)"""
    import winreg
    for name in ("EXPLABS_API_KEY", "EXPLABS_API_KEY2"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
                v, _ = winreg.QueryValueEx(k, name)
                if v and not os.environ.get(name):
                    os.environ[name] = v
        except OSError:
            pass

def check_keys():
    """사용자 지시: TYPESAFE 금지, EXPLABS 2키만. xpl_ 접두 확인."""
    _load_jev_keys()
    keys = []
    for name in ("EXPLABS_API_KEY", "EXPLABS_API_KEY2"):
        v = os.environ.get(name, "")
        if v:
            keys.append((name, v))
    assert keys, "EXPLABS 키 없음 — HKCU\\Environment 확인 필요"
    for name, v in keys:
        assert v.startswith("xpl_"), f"{name}가 xpl_ 접두 아님 — 사용 금지: {v[:8]}..."
    return keys

# ---------- ingest: 문항 haystack → 임시 mnemosyne DB ----------
def ingest_question(x, tag):
    """문항 1건의 haystack 세션 전부를 임시 DB에 remember() (0 JEV 콜)."""
    tmp = tempfile.mkdtemp(prefix="lmev_")
    db_path = os.path.join(tmp, "lmev.db")
    from mnemosyne import Mnemosyne
    mem = Mnemosyne(session_id=tag, db_path=db_path)
    t0 = time.time()
    n = 0
    for sess in x["haystack_sessions"]:
        for turn in sess:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if not content:
                continue
            mem.remember(f"{role}: {content}", source="conversation",
                         importance=0.5, extract=False)
            n += 1
    dt = time.time() - t0
    return {"db_path": db_path, "mem": mem, "turns": n, "ingest_s": dt}

# ---------- JEV choice (가이드라인: pool 60, abstain 포함) ----------
def run_choice(mem, q, client, api, pool_top=60):
    """라이브 파이프라인과 동일: 4-lane pool(60) → excerpt → choice 1콜"""
    conn = mem.beam.conn

    def recall_raw_factory(qry):
        def recall_raw(kind, arg, kk):
            from mnemosyne.core import beam as beam_mod
            from mnemosyne.core import embeddings as emb_mod
            if kind == "fts":
                return beam_mod._fts_search_working(conn, arg, k=kk)
            if kind == "vec":
                qemb = emb_mod.embed([arg])
                if qemb is None or not len(qemb):
                    return []
                return beam_mod._wm_vec_search(conn, qemb[0], k=kk)
            if kind == "imp":
                return j1p._imp_search(conn, k=kk)
            if kind == "graph":
                return j1p._graph_lane_search(conn, arg, kk)
            if kind == "get":
                r = conn.execute(
                    "SELECT id, content, importance FROM working_memory WHERE id=?",
                    (arg,)).fetchone()
                if not r:
                    r = conn.execute(
                        "SELECT id, content, importance FROM episodic_memory WHERE id=?",
                        (arg,)).fetchone()
                return dict(r) if r else None
            return []
        return recall_raw

    try:
        pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    except Exception as e:
        return {"q": q, "err": f"pool: {e}"}
    pool = j1p._filter_and_rank(pool, q)[:pool_top]
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a"
              for c in pool]
    jl = labels + [m48.ABSTAIN_CURRENT]
    st = j1p.build_state(q, pool)
    qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    t0 = time.time()
    resp = client.post(api, json={"state": st, "questions": qs, "model": "jev-latest"},
                       timeout=25)
    lat = time.time() - t0
    if resp.status_code != 200:
        return {"q": q, "err": f"http{resp.status_code}", "latency_s": lat, "pool": len(pool)}
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    try:
        idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception:
        idx = None
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    abstain = (idx == len(jl) - 1)
    rows = [{"rank": r, "content": labels[r]} for r in range(min(5, len(pool)))]
    return {"q": q, "idx": idx, "abstain_p": ap, "abstain": abstain,
            "pool_n": len(pool), "latency_s": round(lat, 2), "rows": rows}

# ---------- reader (deepcombo, 로컬 무료) ----------
DEEPCOMBO_URL = "http://localhost:20128/v1/chat/completions"

def chat(prompt, max_tokens=200, temperature=0.0):
    body = {"model": "deepcombo",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": temperature}
    req = urllib.request.Request(DEEPCOMBO_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode()
    if raw.lstrip().startswith("{"):
        d = json.loads(raw.split("data:")[0])
    else:
        d = None
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:") and "[DONE]" not in line:
                d = json.loads(line[5:].strip())
                break
        if d is None:
            return f"[ERR 파싱] {raw[:100]}"
    return d["choices"][0]["message"]["content"]

import urllib.request

def reader_answer(q, rows, retries=5):
    """deepcombo reader — 9router 동시 요청 503 대비 지수 백오프 재시도 (실측: 6동시 중 4 503)"""
    ctx = "\n".join(f"- {r['content']}" for r in rows) if rows else "(메모리 없음)"
    prompt = (f"<retrieved_context>\n{ctx}\n</retrieved_context>\n\n"
              f"질문: {q}\n위 메모리를 참고하여 답변하세요.")
    for attempt in range(retries):
        try:
            return chat(prompt)
        except Exception as e:
            if attempt == retries - 1:
                return f"[ERR reader: {e}]"
            time.sleep(1.0 * (2 ** attempt))

# judge prompt (LongMemEval 공식, get_anscheck_prompt 재현)
def judge_prompt(qtype, q, ans, hyp, abstention=False):
    if not abstention:
        t = ("I will give you a question, a correct answer, and a response from a model. "
             "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
             "If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. "
             "If the response only contains a subset of the information required by the answer, answer no.\n\n"
             f"Question: {q}\n\nCorrect Answer: {ans}\n\nModel Response: {hyp}\n\n"
             "Is the model response correct? Answer yes or no only.")
    else:
        t = ("I will give you an unanswerable question, an explanation, and a response from a model. "
             "Please answer yes if the model correctly identifies the question as unanswerable. "
             "The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\n"
             f"Question: {q}\n\nExplanation: {ans}\n\nModel Response: {hyp}\n\n"
             "Does the model correctly identify the question as unanswerable? Answer yes or no only.")
    return t

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--no_reader", action="store_true")
    args = ap.parse_args()

    # 1) 키 확인 (사용자 지시: EXPLABS 2키만)
    keys = check_keys()
    print(f"[keys] EXPLABS {len(keys)}키: " + ", ".join(f"{n}={v[:6]}..." for n, v in keys), flush=True)

    # 2) JEV 클라이언트
    client = _jev_client()
    assert client, "JEV 클라이언트 생성 실패"
    api = getattr(client, "_jev_api", None)
    print(f"[jev] API: {api}", flush=True)

    # 3) 데이터 로드 + 3문항 선택 (타입 대표)
    data = json.load(open(LMEV_DATA, encoding="utf-8"))
    # abstention 포함 + 타입 다양성
    picked = []
    seen = set()
    for x in data:
        is_abs = x["question_id"].endswith("_abs")
        t = x["question_type"] + ("_abs" if is_abs else "")
        if t not in seen or (is_abs and len(picked) < args.limit):
            if t not in seen:
                seen.add(t)
            picked.append(x)
        if len(picked) >= args.limit:
            break
    picked = picked[:args.limit]
    print(f"[data] {len(picked)}문항: " + ", ".join(x["question_id"] for x in picked), flush=True)

    # 4) ingest + JEV + reader 스모크
    results = []
    for i, x in enumerate(picked):
        qid = x["question_id"]
        print(f"\n=== {i+1}/{len(picked)} {qid} ({x['question_type']}) ===", flush=True)
        ing = ingest_question(x, qid)
        print(f"  ingest: {ing['turns']}턴 {ing['ingest_s']:.1f}s ({ing['ingest_s']/max(ing['turns'],1)*1000:.0f}ms/턴)", flush=True)

        jr = run_choice(ing["mem"], x["question"], client, api)
        print(f"  JEV: pool={jr.get('pool_n')} idx={jr.get('idx')} abstain={jr.get('abstain')} "
              f"abstain_p={jr.get('abstain_p', 0):.3f} latency={jr.get('latency_s')}s err={jr.get('err')}", flush=True)

        hyp = None
        if not args.no_reader and not jr.get("err"):
            hyp = reader_answer(x["question"], jr.get("rows") or [])
            print(f"  reader: {hyp[:120]!r}", flush=True)

        res = {"question_id": qid, "question_type": x["question_type"],
               "ingest_turns": ing["turns"], "ingest_s": round(ing["ingest_s"], 2),
               "jev": jr, "hypothesis": hyp}
        results.append(res)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n[smoke] 완료 → {OUT}")

    # 5) 전체 실행 예측
    tot_turns = sum(ing["turns"] for ing in [ingest_question(x, x["question_id"]) for x in picked])
    total = sum(r["ingest_turns"] for r in results)
    ingest_rate = sum(r["ingest_s"] for r in results) / max(total, 1)
    print(f"\n[예측] 500문항 ingest: {total/len(results)*500/1000:.0f}K턴 × {ingest_rate*1000:.0f}ms/턴 ≈ "
          f"{total/len(results)*500*ingest_rate/60:.0f}분 (직렬)")
    jev_lats = [r["jev"].get("latency_s", 0) for r in results if not r["jev"].get("err")]
    if jev_lats:
        print(f"[예측] JEV 500콜: 평균 {sum(jev_lats)/len(jev_lats):.1f}s × 500 = "
              f"{sum(jev_lats)/len(jev_lats)*500/60:.0f}분 (직렬) → 병렬 8워커 ≈ "
              f"{sum(jev_lats)/len(jev_lats)*500/8/60:.0f}분")

if __name__ == "__main__":
    main()