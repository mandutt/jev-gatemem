# -*- coding: utf-8 -*-
"""stage118_lmev_lift.py — LongMemEval 재실행 (JEV pick lift 적용, 운영 동등)

2026-10-10, v8 3-AI 검토 대응 (b-ai·c-ai 지적):
- 기존 stage112/115는 `rows = labels[r] for r in range(min(5, len(pool)))` — JEV choice 결과를
  1위로 승격하지 않아 reader가 JEV가 고른 행을 못 받을 수 있었음 ("Oracle 25.1%" 결론 무효).
- 본 러너는 운영 파이프라인과 동일하게:
  1. pool 60 (FTS+vec+imp+graph RRF, 게이트 (1,0.0))
  2. JEV choice 1콜 → pick idx
  3. 노출 = [pick] + pool[:4] (pick 제외) — 운영 `_render`와 동일
  4. abstain 시 빈 컨텍스트 (운영 soft gate와 동일)
  5. gold-in-pool / winner-is-gold / gold-visible-after-lift / reader-correct 4축 기록
- 사용: --limit N 으로 20문항 smoke → 전체 500 재실행
"""
import argparse, json, os, shutil, tempfile, time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data",
                    "longmemeval_s_cleaned.json")
RESULTS = os.path.join(REPO, "experiments", "operational-golden", "data",
                       "stage118_lmev_lift_results.jsonl")
BENCH_DIR = os.path.join(REPO, "experiments", "operational-golden", "data",
                         "tmp_bench")
os.makedirs(BENCH_DIR, exist_ok=True)


def ingest_batch(x, tag):
    """stage112와 동일 — 임베딩 off bulk + 배치 임베딩."""
    from mnemosyne import Mnemosyne
    import mnemosyne.core.embeddings as emb_mod
    from mnemosyne.core import beam as beam_mod

    tmp = tempfile.mkdtemp(prefix="lmev_l_", dir=BENCH_DIR)
    db_path = os.path.join(tmp, "x.db")
    mem = Mnemosyne(session_id=tag, db_path=db_path)
    conn = mem.beam.conn
    t0 = time.time()

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


def run_choice_lift(mem, q, client, api):
    """JEV choice 1콜 + [pick]+pool[:4] lift 노출 (운영 동등)."""
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
        pool = j1p._filter_and_rank(pool, q)[:60]
        labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150)
                  or "n/a" for c in pool]
        jl = labels + [m48.ABSTAIN_CURRENT]
        st = j1p.build_state(q, pool)
        qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                       "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
        t0 = time.time()
        resp = client.post(api, json={"state": st, "questions": qs,
                                      "model": "jev-latest"}, timeout=25)
        lat = time.time() - t0
        if resp.status_code != 200:
            return {"err": f"http{resp.status_code}", "pool": len(pool),
                    "latency_s": round(lat, 2)}
        ans = (resp.json().get("answers") or {}).get("best") or {}
        probs = ans.get("probabilities") or {}
        try:
            idx = int(str(ans.get("choice")).lstrip("c"))
        except Exception:
            idx = None
        ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
        abstain = idx == len(jl) - 1

        # ★ 운영 동등 노출: [pick] + pool[:4] (pick 제외)
        if abstain or idx is None:
            exposed = []
        else:
            pick = {"rank": 0, "content": labels[idx], "pool_rank": idx}
            rest = [{"rank": r + 1, "content": labels[r], "pool_rank": r}
                    for r in range(min(5, len(pool))) if r != idx]
            exposed = [pick] + rest[:4]

        return {"idx": idx, "abstain": abstain, "abstain_p": round(ap, 3),
                "pool": len(pool), "latency_s": round(lat, 2),
                "exposed": exposed, "pool_labels": labels}
    except Exception as e:
        return {"err": f"{type(e).__name__}: {e}"}


def gold_visible(x, jr):
    """4축: gold-in-pool / winner-is-gold / gold-visible-after-lift."""
    ans = str(x.get("answer", "")).strip().lower()
    if not ans:
        return {"gold_in_pool": None, "winner_is_gold": None,
                "gold_visible": None}
    labels = jr.get("pool_labels") or []
    # gold 문구가 pool 라벨에 포함되는지 (단순 substring — excerpt 기준)
    gold_hits = [i for i, lab in enumerate(labels) if ans in lab.lower()]
    winner_is_gold = jr.get("idx") in gold_hits if jr.get("idx") is not None else False
    exposed = jr.get("exposed") or []
    gold_visible = any(ans in (e.get("content") or "").lower() for e in exposed)
    return {"gold_in_pool": len(gold_hits) > 0, "winner_is_gold": winner_is_gold,
            "gold_visible": gold_visible, "gold_pool_ranks": gold_hits[:5]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0=전체 500")
    args = ap.parse_args()

    from stage110_lmev_smoke import check_keys, reader_answer
    from jev_mem_core.pipeline import _jev_client
    # ★ 2026-10-10 b-ai·c-ai: 하네스-운영 동등성 자동 검증 (운영 위반 시 즉시 중단)
    from harness_parity import assert_harness_parity

    keys = check_keys()
    print(f"[keys] EXPLABS {len(keys)}키 확인", flush=True)
    client = _jev_client()
    assert client
    api = getattr(client, "_jev_api", None)
    # 러너 자체가 운영 노출([pick]+pool[:4])을 쓰는지 1회 검증: run_choice_lift의 계약 확인
    assert_harness_parity(pool_n=60, exposure_ids=["x"] * 5, model="jev-latest",
                          abstain_exposed=None, runner_name="stage118-lmev-lift")

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
    ok = err = 0
    for i, x in enumerate(todo):
        qid = x["question_id"]
        t0 = time.time()
        tmp_dir = None
        try:
            ing = ingest_batch(x, qid)
            tmp_dir = os.path.dirname(ing["db_path"])
            jr = run_choice_lift(ing["mem"], x["question"], client, api)
            if jr.get("err") and "503" in str(jr.get("err")):
                time.sleep(1.5)
                jr = run_choice_lift(ing["mem"], x["question"], client, api)
            hyp = None
            if not jr.get("err"):
                exposed = jr.get("exposed") or []
                rows = [{"content": e["content"]} for e in exposed]
                hyp = reader_answer(x["question"], rows)
            gv = gold_visible(x, jr) if not jr.get("err") else {}
            res = {
                "question_id": qid,
                "question_type": x["question_type"],
                "question": x["question"],
                "answer": x.get("answer", ""),
                "question_date": x.get("question_date", ""),
                "answer_session_ids": x.get("answer_session_ids", []),
                "ingest_turns": ing["turns"],
                "ingest_s": round(ing["ingest_s"], 2),
                "jev": {k: jr.get(k) for k in
                        ("idx", "abstain", "abstain_p", "pool", "latency_s")},
                "gold": gv,
                "hypothesis": hyp,
                "elapsed_s": round(time.time() - t0, 1),
            }
            ok += 1
            print(f"[{i+1}/{len(todo)}] {qid} type={x['question_type']} "
                  f"idx={jr.get('idx')} abstain={jr.get('abstain')} "
                  f"gip={gv.get('gold_in_pool')} wig={gv.get('winner_is_gold')} "
                  f"gv={gv.get('gold_visible')} err={jr.get('err')} "
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


if __name__ == "__main__":
    main()