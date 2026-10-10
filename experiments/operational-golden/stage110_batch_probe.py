# -*- coding: utf-8 -*-
"""stage110_batch_probe.py — 배치 ingest 경로 검증 (2026-10-10)

목적: 단일 프로세스 + bulk insert + 배치 임베딩이 (1) 작동하고
      (2) JEV pool 검색(FTS/vec)이 기존 remember() 경로와 동일하게 동작하는지 검증.

절차:
  1. 문항 1건 haystack을 working_memory에 bulk INSERT (content + 역할 프리픽스, remember 미사용)
  2. 존재하는 배치 임베딩 경로로 벡터 생성·저장
  3. JEV choice 1콜 (FTS/vec lane이 pool을 만들 수 있는지)
  4. 기존 remember() 경로 결과(스모크: e47becba idx=1)와 비교

비교 대상 스모크 결과: e47becba single-session-user, pool=41, idx=1
"""
import os, sys, json, time, tempfile, sqlite3

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client
import stage48_live60_cross as m48

DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"
BENCH_DIR = os.path.join(REPO, "experiments", "operational-golden", "data", "tmp_bench")
os.makedirs(BENCH_DIR, exist_ok=True)

from mnemosyne import Mnemosyne
import mnemosyne.core.embeddings as emb_mod


def ingest_batch(x, tag):
    """working_memory bulk INSERT + 배치 임베딩 저장 (실제 스키마: memory_embeddings + vec_working)."""
    tmp = tempfile.mkdtemp(prefix="lmev_batch_", dir=BENCH_DIR)
    db_path = os.path.join(tmp, "x.db")
    mem = Mnemosyne(session_id=tag, db_path=db_path)
    conn = mem.beam.conn
    t0 = time.time()

    # 1) bulk INSERT — 임베딩 off remember() (FTS 트리거 자동, vec 저장만 스킵)
    import mnemosyne.core.embeddings as emb_mod
    _orig_available = emb_mod.available
    emb_mod.available = lambda: False  # remember() 내부 임베딩 스킵
    from mnemosyne.core import beam as beam_mod
    rows = []
    for sess in x["haystack_sessions"]:
        for turn in sess:
            c = turn.get("content", "")
            if c:
                rows.append(f"{turn.get('role','user')}: {c}")
    ins_t0 = time.time()
    memory_ids = []
    for content in rows:
        mid = mem.remember(content, source="conversation", importance=0.5, extract=False)
        if mid:
            memory_ids.append(mid)
        if len(memory_ids) % 50 == 0 and len(memory_ids) > 0:
            conn.commit()
    conn.commit()
    ins_dt = time.time() - ins_t0
    emb_mod.available = _orig_available  # 복원

    # 2) 배치 임베딩: working_memory 전체 → embed(batch) → _store_working_embedding
    emb_t0 = time.time()
    pool_rows = conn.execute(
        "SELECT id, content FROM working_memory WHERE id IS NOT NULL"
    ).fetchall()
    contents = [r["content"] for r in pool_rows]
    batch_size = 64
    n_emb = 0
    for start in range(0, len(contents), batch_size):
        chunk = contents[start:start + batch_size]
        vecs = emb_mod.embed(chunk)
        if vecs is None:
            break
        for r, vec in zip(pool_rows[start:start + batch_size], vecs):
            try:
                beam_mod._store_working_embedding(conn, r["id"], vec.tolist() if hasattr(vec, "tolist") else list(vec), commit_vec=False)
                n_emb += 1
            except Exception as e:
                print(f"  emb store fail: {e}")
    conn.commit()
    emb_dt = time.time() - emb_t0

    total = time.time() - t0
    print(f"[batch] {len(rows)}턴: insert={ins_dt:.1f}s embed={emb_dt:.1f}s (배치 {n_emb}건) total={total:.1f}s")
    return {"db_path": db_path, "mem": mem, "turns": len(rows), "ingest_s": total,
            "insert_s": ins_dt, "embed_s": emb_dt, "embedded": n_emb}


def run_choice_on_db(mem, q, client, api):
    """run_choice를 mem(배치 DB)에 대해 실행 — FTS/vec lane이 동작하는지."""
    conn = mem.beam.conn

    def recall_raw_factory(qry):
        def recall_raw(kind, arg, kk):
            from mnemosyne.core import beam as beam_mod
            if kind == "fts":
                return beam_mod._fts_search_working(conn, arg, k=kk)
            if kind == "vec":
                from mnemosyne.core import embeddings as emb2
                qemb = emb2.embed_query(arg) if hasattr(emb2, "embed_query") else emb2.embed([arg])[0]
                if qemb is None:
                    return []
                return beam_mod._wm_vec_search(conn, qemb, k=kk)
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
        print(f"  pool: {len(pool)}건 (FTS/vec/imp/graph lane 정상?)")
        labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in pool]
        jl = labels + [m48.ABSTAIN_CURRENT]
        st = j1p.build_state(q, pool)
        qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                       "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
        t0 = time.time()
        resp = client.post(api, json={"state": st, "questions": qs, "model": "jev-latest"}, timeout=25)
        lat = time.time() - t0
        if resp.status_code != 200:
            return {"err": f"http{resp.status_code}", "pool": len(pool), "latency_s": lat}
        ans = (resp.json().get("answers") or {}).get("best") or {}
        probs = ans.get("probabilities") or {}
        try:
            idx = int(str(ans.get("choice")).lstrip("c"))
        except Exception:
            idx = None
        ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
        return {"idx": idx, "abstain": idx == len(jl) - 1, "abstain_p": ap,
                "pool": len(pool), "latency_s": round(lat, 2)}
    except Exception as e:
        return {"err": f"{type(e).__name__}: {e}"}


def main():
    # 키/클라이언트
    from stage110_lmev_smoke import check_keys
    check_keys()
    client = _jev_client()
    assert client
    api = getattr(client, "_jev_api", None)

    data = json.load(open(DATA, encoding="utf-8"))
    # 스모크와 같은 문항 (비교 가능): e47becba
    x = next(d for d in data if d["question_id"] == "e47becba")
    print(f"[1] 배치 ingest 시작: {x['question_id']} ({x['question_type']})")

    ing = ingest_batch(x, "batch_probe")
    print(f"[2] ingest 완료: {ing['turns']}턴, {ing['ingest_s']:.1f}s")

    # DB 직접 확인: working_memory + memory_embeddings/vec_working 존재
    conn = ing["mem"].beam.conn
    wm = conn.execute("SELECT COUNT(*) c FROM working_memory").fetchone()["c"]
    try:
        emb = conn.execute("SELECT COUNT(*) c FROM memory_embeddings").fetchone()["c"]
        vw = conn.execute("SELECT COUNT(*) c FROM vec_working").fetchone()["c"]
        print(f"[3] DB 확인: working_memory={wm} memory_embeddings={emb} vec_working={vw}")
    except Exception as e:
        print(f"[3] DB 확인: working_memory={wm}, 벡터 테이블 조회 실패: {e}")

    # JEV choice
    jr = run_choice_on_db(ing["mem"], x["question"], client, api)
    print(f"[4] JEV choice: {jr}")
    print(f"[5] 스모크 비교 (기대): pool=41, idx=1 (e47becba)")

    # 임시 DB 유지 (디버깅용), 프로세스 종료 시 정리
    print(f"[6] DB 경로: {ing['db_path']}")


if __name__ == "__main__":
    main()