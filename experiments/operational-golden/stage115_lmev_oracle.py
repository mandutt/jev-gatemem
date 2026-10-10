# -*- coding: utf-8 -*-
"""stage115_lmev_oracle.py — LongMemEval-S oracle 상한 측정 (2026-10-10)

목적: evidence 세션만 넣으면 (ideal recall) 정확도가 어디까지 오르는가?
      - JEV abstain 261건 중 실제 답이 pool에 있었는지 대조
      - 검색 레버 문제 vs 판정 레버 문제 분리

방법:
  1. 문항의 answer_session_ids (evidence 세션)만 ingest (median 2세션, ~20턴)
  2. JEV choice 1콜 (same as stage112)
  3. reader (deepcombo) 응답 + judge (deepcombo) 판정

비교: stage112 (full haystack) 24.1% vs 본 실행 oracle 정확도

실행: %LOCALAPPDATA%/jev-mem/venv/Scripts/python.exe stage115_lmev_oracle.py [--limit N]
예상: evidence 세션만이라 ingest 수 초/문항 → 500문항 ≈ 15분 + JEV 500콜 ≈ 30분 내외
"""
import os, sys, json, time, argparse, shutil, tempfile

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"
BENCH_DIR = os.path.join(REPO, "experiments", "operational-golden", "data", "tmp_bench")
RESULTS = os.path.join(REPO, "experiments", "operational-golden", "data", "stage115_lmev_oracle_results.jsonl")
os.makedirs(BENCH_DIR, exist_ok=True)


def ingest_oracle(x, tag):
    """answer_session_ids (evidence) 세션만 ingest."""
    from mnemosyne import Mnemosyne
    import mnemosyne.core.embeddings as emb_mod
    from mnemosyne.core import beam as beam_mod

    tmp = tempfile.mkdtemp(prefix="lmev_o_", dir=BENCH_DIR)
    db_path = os.path.join(tmp, "x.db")
    mem = Mnemosyne(session_id=tag, db_path=db_path)
    conn = mem.beam.conn
    t0 = time.time()

    # evidence 세션만 선택: haystack_session_ids에서 answer_session_ids에 해당하는 인덱스
    sess_ids = x.get("haystack_session_ids", [])
    ans_ids = set(x.get("answer_session_ids", []))
    sel = [s for sid, s in zip(sess_ids, x["haystack_sessions"]) if str(sid) in ans_ids]
    # fallback: answer_session_ids가 없거나 매칭 안 되면 전체 (드문 case)
    if not sel:
        sel = x["haystack_sessions"]

    _orig = emb_mod.available
    emb_mod.available = lambda: False
    rows = [f"{t.get('role','user')}: {t['content']}"
            for sess in sel for t in sess if t.get("content")]
    for i, content in enumerate(rows):
        mem.remember(content, source="conversation", importance=0.5, extract=False)
        if (i + 1) % 100 == 0:
            conn.commit()
    conn.commit()
    emb_mod.available = _orig

    # 배치 임베딩
    pool_rows = conn.execute("SELECT id, content FROM working_memory WHERE id IS NOT NULL").fetchall()
    contents = [r["content"] for r in pool_rows]
    BATCH = 64
    for start in range(0, len(contents), BATCH):
        chunk = contents[start:start + BATCH]
        vecs = emb_mod.embed(chunk)
        if vecs is None:
            break
        for r, vec in zip(pool_rows[start:start + BATCH], vecs):
            try:
                beam_mod._store_working_embedding(conn, r["id"],
                    vec.tolist() if hasattr(vec, "tolist") else list(vec), commit_vec=False)
            except Exception:
                pass
    conn.commit()
    return {"db_path": db_path, "mem": mem, "turns": len(rows), "ingest_s": time.time() - t0}


def run_choice(mem, q, client, api):
    """JEV choice — stage112와 동일."""
    from mnemosyne.core import beam as beam_mod
    from mnemosyne.core import embeddings as emb_mod
    import stage48_live60_cross as m48
    import gateway.j1_pipeline as j1p
    conn = mem.beam.conn

    def recall_raw_factory(qry):
        def recall_raw(kind, arg, kk):
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
                r = conn.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
                if not r:
                    r = conn.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
                return dict(r) if r else None
            return []
        return recall_raw

    try:
        pool = j1p.build_lane_pool(recall_raw_factory(q), q)
        pool = j1p._filter_and_rank(pool, q)[:60]
        labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a"
                  for c in pool]
        jl = labels + [m48.ABSTAIN_CURRENT]
        st = j1p.build_state(q, pool)
        qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                       "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
        t0 = time.time()
        resp = client.post(api, json={"state": st, "questions": qs, "model": "jev-latest"}, timeout=25)
        lat = time.time() - t0
        if resp.status_code != 200:
            return {"err": f"http{resp.status_code}", "pool": len(pool), "latency_s": round(lat, 2)}
        ans = (resp.json().get("answers") or {}).get("best") or {}
        probs = ans.get("probabilities") or {}
        try:
            idx = int(str(ans.get("choice")).lstrip("c"))
        except Exception:
            idx = None
        ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
        return {"idx": idx, "abstain": idx == len(jl) - 1, "abstain_p": round(ap, 3),
                "pool": len(pool), "latency_s": round(lat, 2),
                "rows": [{"rank": r, "content": labels[r]} for r in range(min(5, len(pool)))]}
    except Exception as e:
        return {"err": f"{type(e).__name__}: {e}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0=전체 500")
    args = ap.parse_args()

    from stage110_lmev_smoke import check_keys, reader_answer
    from jev_mem_core.pipeline import _jev_client
    from stage113_lmev_judge import judge_one, judge_prompt  # judge 재사용

    keys = check_keys()
    print(f"[keys] EXPLABS {len(keys)}키 확인", flush=True)
    client = _jev_client()
    assert client
    api = getattr(client, "_jev_api", None)

    data = json.load(open(DATA, encoding="utf-8"))
    done = set()
    if os.path.exists(RESULTS):
        with open(RESULTS, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["question_id"])
                except Exception:
                    pass
    todo = [x for x in data if x["question_id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[data] 전체 {len(data)} / 완료 {len(done)} / 실행 {len(todo)}", flush=True)
    if not todo:
        print("[done] 실행할 문항 없음", flush=True)
        return

    t_start = time.time()
    ok = err = 0
    for i, x in enumerate(todo):
        qid = x["question_id"]
        t0 = time.time()
        tmp_dir = None
        try:
            ing = ingest_oracle(x, qid)
            tmp_dir = os.path.dirname(ing["db_path"])
            jr = run_choice(ing["mem"], x["question"], client, api)
            if jr.get("err") and "503" in str(jr.get("err")):
                time.sleep(1.5)
                jr = run_choice(ing["mem"], x["question"], client, api)
            hyp = None
            if not jr.get("err"):
                rows = [] if jr.get("abstain") else (jr.get("rows") or [])[:5]
                hyp = reader_answer(x["question"], rows)
            res = {
                "question_id": qid, "question_type": x["question_type"],
                "question": x["question"], "answer": x.get("answer", ""),
                "ingest_turns": ing["turns"], "ingest_s": round(ing["ingest_s"], 2),
                "jev": jr, "hypothesis": hyp, "elapsed_s": round(time.time() - t0, 1),
            }
            ok += 1
            print(f"[{i+1}/{len(todo)}] {qid} type={x['question_type']} ingest={ing['ingest_s']:.1f}s "
                  f"jev={jr.get('idx')}/abstain={jr.get('abstain')}/ap={jr.get('abstain_p', 0):.2f} "
                  f"err={jr.get('err')}", flush=True)
        except Exception as e:
            res = {"question_id": qid, "error": f"{type(e).__name__}: {e}",
                   "elapsed_s": round(time.time() - t0, 1)}
            err += 1
            print(f"[{i+1}/{len(todo)}] ERR {qid}: {res['error']}", flush=True)
        finally:
            if tmp_dir:
                try:
                    ing["mem"].beam.conn.close()
                except Exception:
                    pass
                shutil.rmtree(tmp_dir, ignore_errors=True)
        with open(RESULTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
        if (i + 1) % 25 == 0:
            el = time.time() - t_start
            print(f"  --- 진행 {i+1}/{len(todo)} | {el/60:.1f}분 경과 ---", flush=True)

    el = time.time() - t_start
    print(f"\n[완료] 성공 {ok} / 오류 {err} | 총 {el/60:.1f}분 → {RESULTS}", flush=True)
    print(f"[완료 마커] LMEV_ORACLE_DONE ok={ok} err={err} total_s={el:.0f}", flush=True)


if __name__ == "__main__":
    main()