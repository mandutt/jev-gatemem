# -*- coding: utf-8 -*-
"""stage112_lmev_serial.py — LongMemEval-S 500문항 단독 프로세스 실행 (2026-10-10)

설계: docs/longmemeval/2026-10-10_longmemeval-design.md
선행 실측 (stage110/111 프로브):
  - 단독 ingest 33.6s/문항 (insert 9s + 배치 embed 24.5s) — 병렬(4프로세스)은 6배 손해
    → 단독 실행이 최적 (이 머신에서 다중 프로세스 경합 확정)
  - 배치 ingest + JEV 결과 = 기존 remember 경로와 동일 (stage110_batch_probe: pool=41 idx=1)
  - JEV: EXPLABS 2키, 평균 1.6s/콜 (500콜 = 13분 직렬)

파이프라인 (문항 순차):
  1. ingest: remember(임베딩 off) bulk + 배치 임베딩 → memory_embeddings+vec_working
  2. JEV choice 1콜 (EXPLABS 2키, abstain 포함, 503 1회 재시도)
  3. reader: deepcombo (로컬, 503 지수 백오프 재시도)
  4. 결과 JSONL append + 체크포인트 (완료 qid skip, 중단 후 재개 가능)

격리: 임시 DB만 사용, 라이브 DB(%LOCALAPPDATA%\\jev-mem) 접근 없음, 데몬 무영향.

실행: %LOCALAPPDATA%/jev-mem/venv/Scripts/python.exe stage112_lmev_serial.py [--limit M]
예상: 500문항 × 33.6s ≈ 4.7시간 (백그라운드/밤새 실행)
"""
import os, sys, json, time, argparse, shutil, tempfile

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"
BENCH_DIR = os.path.join(REPO, "experiments", "operational-golden", "data", "tmp_bench")
RESULTS = os.path.join(REPO, "experiments", "operational-golden", "data", "stage112_lmev_results.jsonl")
os.makedirs(BENCH_DIR, exist_ok=True)


def ingest_batch(x, tag):
    """remember(임베딩 off) bulk + 배치 임베딩. stage110_batch_probe 검증 경로."""
    from mnemosyne import Mnemosyne
    import mnemosyne.core.embeddings as emb_mod
    from mnemosyne.core import beam as beam_mod

    tmp = tempfile.mkdtemp(prefix="lmev_s_", dir=BENCH_DIR)
    db_path = os.path.join(tmp, "x.db")
    mem = Mnemosyne(session_id=tag, db_path=db_path)
    conn = mem.beam.conn
    t0 = time.time()

    # 1) 임베딩 off remember bulk
    _orig = emb_mod.available
    emb_mod.available = lambda: False
    rows = [f"{t.get('role','user')}: {t['content']}"
            for sess in x["haystack_sessions"] for t in sess
            if t.get("content")]
    for i, content in enumerate(rows):
        mem.remember(content, source="conversation", importance=0.5, extract=False)
        if (i + 1) % 100 == 0:
            conn.commit()
    conn.commit()
    emb_mod.available = _orig

    # 2) 배치 임베딩 (64개/배치 → _store_working_embedding)
    pool_rows = conn.execute(
        "SELECT id, content FROM working_memory WHERE id IS NOT NULL").fetchall()
    contents = [r["content"] for r in pool_rows]
    BATCH = 64
    for start in range(0, len(contents), BATCH):
        chunk = contents[start:start + BATCH]
        vecs = emb_mod.embed(chunk)
        if vecs is None:
            break
        for r, vec in zip(pool_rows[start:start + BATCH], vecs):
            try:
                beam_mod._store_working_embedding(
                    conn, r["id"],
                    vec.tolist() if hasattr(vec, "tolist") else list(vec),
                    commit_vec=False)
            except Exception:
                pass
    conn.commit()
    return {"db_path": db_path, "mem": mem, "turns": len(rows),
            "ingest_s": time.time() - t0}


def run_choice(mem, q, client, api):
    """JEV choice 1콜 — stage110_lmev_smoke.run_choice와 동일."""
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
                    r = json.loads(line)
                    if r.get("question_id"):
                        done.add(r["question_id"])
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
    ok = 0
    err = 0
    for i, x in enumerate(todo):
        qid = x["question_id"]
        t0 = time.time()
        tmp_dir = None
        try:
            ing = ingest_batch(x, qid)
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
                "question_id": qid,
                "question_type": x["question_type"],
                "question": x["question"],
                "answer": x.get("answer", ""),
                "question_date": x.get("question_date", ""),
                "answer_session_ids": x.get("answer_session_ids", []),
                "ingest_turns": ing["turns"],
                "ingest_s": round(ing["ingest_s"], 2),
                "jev": jr,
                "hypothesis": hyp,
                "elapsed_s": round(time.time() - t0, 1),
            }
            ok += 1
            print(f"[{i+1}/{len(todo)}] {qid} type={x['question_type']} "
                  f"ingest={ing['ingest_s']:.1f}s jev={jr.get('idx')}/abstain={jr.get('abstain')}/"
                  f"ap={jr.get('abstain_p', 0):.2f} lat={jr.get('latency_s')}s err={jr.get('err')} "
                  f"elapsed={res['elapsed_s']}s", flush=True)
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

        if (i + 1) % 10 == 0:
            el = time.time() - t_start
            rate = (i + 1) / el * 60
            remain = (len(todo) - i - 1) / max(rate, 1e-9)
            print(f"  --- 진행 {i+1}/{len(todo)} | {rate:.1f}문항/분 | 잔여 ≈ {remain:.0f}분 "
                  f"(경과 {el/60:.1f}분) ---", flush=True)

    el = time.time() - t_start
    print(f"\n[완료] 성공 {ok} / 오류 {err} | 총 {el/60:.1f}분 → {RESULTS}", flush=True)
    print(f"[완료 마커] LMEV_SERIAL_DONE ok={ok} err={err} total_s={el:.0f}", flush=True)


if __name__ == "__main__":
    main()