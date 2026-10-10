# -*- coding: utf-8 -*-
"""stage110_lmev_full.py — LongMemEval-S 500문항 전체 실행 (2026-10-10)

설계 문서: docs/longmemeval/2026-10-10_longmemeval-design.md (사용자 승인)
스모크: stage110_lmev_smoke.py (검증 완료 — ingest 43ms/턴, JEV 평균 1.6s/콜)

파이프라인 (문항당):
  1. ingest: haystack 세션 전부 → 임시 sqlite DB (mnemosyne remember, 0 JEV 콜)
  2. JEV choice 1콜 (EXPLABS 2키, SmartRotator 429 전환, abstain 포함)
  3. reader: deepcombo (로컬 무료) — JEV 상위 5개 노출, abstain 시 메모리 미노출
  4. 결과 JSONL append (문항당 1행)

- 6 워커 병렬 (RAM 15.6GB 안전선) — 문항 독립이라 확장 가능
- 체크포인트: data/stage110_lmev_results.jsonl — 완료 qid는 재시작 시 skip
- 격리: 임시 DB만 사용, 라이브 DB(%LOCALAPPDATA%\\jev-mem) 접근 없음,
  데몬 프로세스·설정 수정 없음

실행 (데몬 venv — mnemosyne 라이브러리 필요):
  %LOCALAPPDATA%/jev-mem/venv/Scripts/python.exe stage110_lmev_full.py [--workers N] [--limit M]
"""
import os, sys, json, time, argparse, shutil, multiprocessing as mp

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

from stage110_lmev_smoke import (
    ingest_question, run_choice, reader_answer, check_keys, LMEV_DATA, DATA_DIR,
)

RESULTS = os.path.join(DATA_DIR, "stage110_lmev_results.jsonl")

# ---------------- 워커 (spawn: 프로세스당 1회 init) ----------------
_WDATA = None
_WCLIENT = None
_WAPI = None
_WJEV_KEYS = None


def _init_worker(data_path):
    global _WDATA, _WCLIENT, _WAPI, _WJEV_KEYS
    _WDATA = json.load(open(data_path, encoding="utf-8"))
    from jev_mem_core.pipeline import _jev_client
    _WCLIENT = _jev_client()
    _WAPI = getattr(_WCLIENT, "_jev_api", None)
    _WJEV_KEYS = check_keys()  # 사용자 지시: EXPLABS 2키만


def _work_one(idx):
    """문항 1건: ingest → JEV choice → reader. idx는 _WDATA 인덱스."""
    x = _WDATA[idx]
    qid = x["question_id"]
    qtype = x["question_type"]
    q = x["question"]
    t0 = time.time()

    # 1) ingest (임시 DB, 0 JEV 콜)
    try:
        ing = ingest_question(x, qid)
    except Exception as e:
        return {"question_id": qid, "error": f"ingest: {type(e).__name__}: {e}",
                "elapsed_s": round(time.time() - t0, 1)}
    tmp_dir = os.path.dirname(ing["db_path"])

    try:
        # 2) JEV choice (503은 일시적 — 1회 재시도, 스킬 지침)
        jr = run_choice(ing["mem"], q, _WCLIENT, _WAPI)
        if jr.get("err") and "503" in str(jr.get("err")):
            time.sleep(1.5)
            jr = run_choice(ing["mem"], q, _WCLIENT, _WAPI)
        # 3) reader (abstain이면 메모리 미노출 — Hermes 운영 동작)
        hyp = None
        if not jr.get("err"):
            if jr.get("abstain"):
                rows = []
            else:
                rows = (jr.get("rows") or [])[:5]
            hyp = reader_answer(q, rows)
        return {
            "question_id": qid,
            "question_type": qtype,
            "question": q,
            "answer": x.get("answer", ""),
            "question_date": x.get("question_date", ""),
            "answer_session_ids": x.get("answer_session_ids", []),
            "ingest_turns": ing["turns"],
            "ingest_s": round(ing["ingest_s"], 2),
            "jev": jr,
            "hypothesis": hyp,
            "elapsed_s": round(time.time() - t0, 1),
        }
    except Exception as e:
        return {"question_id": qid, "error": f"{type(e).__name__}: {e}",
                "elapsed_s": round(time.time() - t0, 1)}
    finally:
        # 임시 DB 정리 (연결 닫기 + 디렉토리 삭제)
        try:
            ing["mem"].beam.conn.close()
        except Exception:
            pass
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="0=전체 500")
    args = ap.parse_args()

    # 키 사전 확인 (메인) — 워커 init에서도 재확인
    keys = check_keys()
    print(f"[keys] EXPLABS {len(keys)}키 확인: " +
          ", ".join(f"{n}={v[:6]}..." for n, v in keys), flush=True)

    # 데이터 로드 (메타만) + 완료분 스킵
    data = json.load(open(LMEV_DATA, encoding="utf-8"))
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
    idxs = [i for i, x in enumerate(data) if x["question_id"] not in done]
    if args.limit:
        idxs = idxs[: args.limit]
    print(f"[data] 전체 {len(data)} / 완료 {len(done)} / 실행 {len(idxs)}", flush=True)
    if not idxs:
        print("[done] 실행할 문항 없음", flush=True)
        return

    t_start = time.time()
    ok = 0
    err = 0
    with mp.Pool(args.workers, initializer=_init_worker, initargs=(LMEV_DATA,)) as pool:
        for i, res in enumerate(pool.imap_unordered(_work_one, idxs, chunksize=1)):
            if res.get("error"):
                err += 1
                print(f"[{i+1}/{len(idxs)}] ERR {res['question_id']}: {res['error']}", flush=True)
            else:
                ok += 1
                jr = res.get("jev") or {}
                print(f"[{i+1}/{len(idxs)}] {res['question_id']} "
                      f"type={res['question_type']} ingest={res['ingest_s']}s "
                      f"jev={jr.get('idx')}/abstain={jr.get('abstain')}/ap={jr.get('abstain_p', 0):.2f} "
                      f"lat={jr.get('latency_s')}s err={jr.get('err')} "
                      f"elapsed={res['elapsed_s']}s", flush=True)
            with open(RESULTS, "a", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
            if (i + 1) % 25 == 0:
                el = time.time() - t_start
                rate = (i + 1) / el * 60
                remain = (len(idxs) - i - 1) / max(rate, 1e-9)
                print(f"  --- 진행 {i+1}/{len(idxs)} | {rate:.1f}문항/분 | 잔여 ≈ {remain:.0f}분 "
                      f"(경과 {el/60:.1f}분) ---", flush=True)

    el = time.time() - t_start
    print(f"\n[완료] 성공 {ok} / 오류 {err} | 총 {el/60:.1f}분 → {RESULTS}", flush=True)
    print(f"[완료 마커] LMEV_FULL_DONE ok={ok} err={err} total_s={el:.0f}", flush=True)


if __name__ == "__main__":
    main()