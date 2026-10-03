"""아카이브(재판정 skip) 행이 live recall 경로에서 배제되는지 회귀 검증.

배경 (2026-10-03 실측 회귀):
  fail-open 재판정으로 archived된 행이 두 결함의 조합으로 live recall에 재유입:
    (a) P3 recover.py / rejudge_v2 가 valid_until을 metadata에만 쓰고 컬럼을
        누락 → beam 필터(`valid_until IS NULL OR valid_until > now`) 무력.
        24건 백필 + 코드 수정 완료.
    (b) 컬럼을 채워도 FTS/imp/graph lane 원시 쿼리에는 temporal 필터가 없고
        vec lane만 보유 → FTS 경유 행이 hydration(chokepoint)에서 살아남음.
        hydration_get / get_hydrated / _imp_search 수정 대상.

검증 (live DB read-only, 쓰기 없음, JEV 호출 없음):
  1) 아카이브 행 전부 hydration_get() -> None (배제)
  2) FTS raw lane에 잡히는 아카이브 행이 hydration 후 사라짐 (leak vector 문서화)
  3) build_lane_pool 출력에 아카이브 행 0 (probe 쿼리 2종)
  4) positive control: 비아카이브 행 hydration 성공 + imp/vec lane 비어있지 않음
     (과잉 필터로 정상 행까지 죽이지 않았는지)
"""
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

MNEMO_DB = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")

failures = []


def check(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        failures.append(name)


def main():
    from mnemosyne.core.beam import BeamMemory
    import mnemosyne.core.beam as beam_mod
    from core import j1_engine
    from gateway import j1_pipeline as j1p

    beam = BeamMemory(session_id="probe_archived_regress", db_path=MNEMO_DB)
    conn = beam.conn
    conn.row_factory = sqlite3.Row

    # -- 목표집합: 아카이브(skip) 행 -------------------------------------
    archived_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM working_memory"
        " WHERE metadata_json LIKE '%rejudged:skip%'"
        " OR metadata_json LIKE '%\"rejudged\": \"skip\"%'"
        " OR metadata_json LIKE '%\"rejudged\":\"skip\"%'"
    ).fetchall()]
    print(f"[0] 아카이브(skip) 행: {len(archived_ids)}건")
    check("아카이브 행 존재(>=20)", len(archived_ids) >= 20, f"got {len(archived_ids)}")

    # -- 1) hydration 배제 -----------------------------------------------
    print("[1] hydration_get: 아카이브 전부 None 이어야 함")
    leaked = []
    for mid in archived_ids:
        r = j1_engine.hydration_get(beam, mid)
        if r is not None:
            leaked.append(mid)
    check("아카이브 hydration 배제", not leaked,
          f"leaked {len(leaked)}: {[m[:12] for m in leaked[:5]]}")

    # -- 2) FTS raw lane leak vector (정보) ------------------------------
    print("[2] FTS raw lane 누출 벡터 확인 (informational)")
    q1 = "이어서 해줄 수 있어?"
    fts1 = beam_mod._fts_search_working(conn, q1, k=60)
    fts_ids = [r["id"] for r in fts1]
    arch_in_fts = [i for i in fts_ids if i in archived_ids]
    print(f"    fts hits={len(fts_ids)} archived_in_raw={len(arch_in_fts)} "
          f"{[m[:12] for m in arch_in_fts[:4]]}")
    # hydration 후 목록에서 전부 제외
    surviving = [mid for mid in arch_in_fts
                 if j1_engine.hydration_get(beam, mid) is not None]
    check("FTS 경유 아카이브 hydration 후 0", not surviving,
          f"survived {len(surviving)}")

    # -- 3) build_lane_pool 출력에 아카이브 0 ---------------------------
    print("[3] build_lane_pool: probe 쿼리 2종 아카이브 0")

    def recall_raw(kind, arg, k):
        if kind == "fts":
            return beam_mod._fts_search_working(conn, arg, k=k)
        if kind == "vec":
            emb = beam_mod._embeddings.embed([arg])
            if emb is None or not len(emb):
                return []
            return beam_mod._wm_vec_search(conn, emb[0], k=k)
        if kind == "imp":
            return j1p._imp_search(conn, k=k)
        if kind == "graph":
            return j1p._graph_lane_search(conn, arg, k=k)
        if kind == "get":
            row = j1_engine.hydration_get(beam, arg)
            return row if isinstance(row, dict) else None
        return []

    for q in (q1, "좋아 진행해줘"):
        pool = j1p.build_lane_pool(recall_raw, q)
        pool_ids = [str(r.get("id") or "") for r in pool]
        hit = [i for i in pool_ids if i in archived_ids]
        print(f"    q={q!r} pool={len(pool_ids)} archived={len(hit)}")
        check(f"pool 무아카이브 {q!r}", not hit, f"got {[m[:12] for m in hit[:5]]}")

    # -- 4) positive control --------------------------------------------
    print("[4] positive control: 정상 행/레인 생존")
    normal = [i for i in fts_ids if i not in archived_ids]
    ok_normal = 0
    for mid in normal[:5]:
        if j1_engine.hydration_get(beam, mid) is not None:
            ok_normal += 1
    check("비아카이브 hydration 성공(>=1/5)", ok_normal >= 1,
          f"ok={ok_normal}/5")

    imp = j1p._imp_search(conn, k=8)
    imp_ids = [r["id"] for r in imp]
    check("imp lane 반환 존재", len(imp_ids) >= 1, f"n={len(imp_ids)}")
    check("imp lane 아카이브 0", not [i for i in imp_ids if i in archived_ids])

    emb = beam_mod._embeddings.embed([q1])
    vec = beam_mod._wm_vec_search(conn, emb[0], k=60) if emb is not None else []
    vec_ids = [r["id"] for r in vec]
    check("vec lane 반환 존재", len(vec_ids) >= 1, f"n={len(vec_ids)}")
    check("vec lane 아카이브 0", not [i for i in vec_ids if i in archived_ids])

    beam.conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        failures.append(f"EXC:{type(e).__name__}")
    print(f"\n=== 아카이브 recall 회귀: "
          f"{'전부 통과' if not failures else f'실패 {len(failures)}건: {failures}'} ===")
    sys.exit(1 if failures else 0)
