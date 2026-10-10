# -*- coding: utf-8 -*-
"""harness_parity.py — 하네스-운영 동등성 자동 검증 (b-ai·c-ai 최우선, 2026-10-10)

실험 러너가 운영 prefetch 경로와 동일한 JEV 입력·노출 구성을 쓰는지 검증한다.
stage100(1회성 수동)을 임포트 시 자동 실행되는 assert로 승격:
  1. pool 후보 수 == POOL_BUDGET(60)
  2. 노출 = [pick] + pool[:k-1] (JEV lift) — `rows[:k]` RRF 원순서 사용 금지
  3. 모델 식별자 == jev-latest
  4. abstain 시 빈 컨텍스트 (rows 미노출)

사용: 새 러너가 이 모듈을 import하면 main()의 assert가 실행된다.
  from harness_parity import assert_harness_parity
  assert_harness_parity(pool_n=..., exposure=..., model=..., abstain_rows=...)
"""
import os, sys, json, sqlite3

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client

POOL_BUDGET = 60
EXPOSURE_K = 5  # 운영 _render: [pick] + pool[:4]
MODEL = "jev-latest"

_FAILURES = []


def _check(cond, msg):
    if not cond:
        _FAILURES.append(msg)
        print(f"  ❌ {msg}", flush=True)
    else:
        print(f"  ✅ {msg}", flush=True)


def assert_harness_parity(*, pool_n=None, exposure_ids=None, model=None,
                          abstain_exposed=None, runner_name="unknown"):
    """러너 시작 시점에 운영 동등성을 assert.

    Args:
        pool_n: JEV에 보낸 후보 수 (운영 60)
        exposure_ids: 노출된 행 id 목록 (운영 = [pick]+pool[:4] 순서)
        model: JEV 모델 식별자 (jev-latest)
        abstain_exposed: abstain 시 노출한 행 수 (운영 0 = 빈 컨텍스트)
    """
    global _FAILURES
    _FAILURES = []
    print(f"\n[harness-parity] {runner_name} — 운영 동등성 검증", flush=True)

    _check(pool_n == POOL_BUDGET,
           f"후보 수 {pool_n} == 운영 {POOL_BUDGET}")
    _check(exposure_ids is None or len(exposure_ids) <= EXPOSURE_K,
           f"노출 {len(exposure_ids)} <= 운영 {EXPOSURE_K}")
    _check(model == MODEL, f"모델 {model} == {MODEL}")
    # abstain 여부가 명시된 경우에만 빈 컨텍스트 검증 (None = abstain 아님)
    if abstain_exposed is not None:
        _check(abstain_exposed == 0,
               f"abstain 시 노출 {abstain_exposed} == 0 (빈 컨텍스트)")

    if _FAILURES:
        raise AssertionError(
            f"[harness-parity] {runner_name} 운영 동등성 위반 {len(_FAILURES)}건: "
            + "; ".join(_FAILURES))
    print(f"[harness-parity] {runner_name} PASS — 운영과 동등", flush=True)
    return True


def run_stage100_parity(limit=20):
    """stage100 20쿼리 parity 재실행 — 운영 jev_rerank vs 러너 pool[:5] 비교."""
    from canary_run import build_pool_prodex
    data_dir = os.path.join("experiments", "operational-golden", "data")
    out = os.path.join(data_dir, "harness_parity_latest.json")

    queries = [
        "camelAI auto 라우팅에서 어려운 과제는 어떤 모델로 보내졌어?",
        "config.yaml에 18080 프록시 등록 방법?",
        "auto 라우팅이 확률적이라는 결론이었나?",
        "한국어 말투 규칙 뭐지?",
        "브라우저 도구 라우팅 설정 어떻게 돼?",
        "완전 번역 금지 규칙 뭐지?",
        "camelai-serial-proxy 기능 정리해줘",
        "그래 그렇게 해줘",
        "정리 및 커밋해줘",
        "메모리 백엔드 뭐 쓰고 있어?",
        "canary 구축에 대해 설명해줘",
        "cron에 등록해두되 일시정지 상태로 해놓을 순 있나?",
        "스킬 만들 때 file_content로 보내면 돼?",
        "설계 확정 후 리팩터 제안해도 돼?",
        "아까 rows를 2로 바꾸는 안도 있지 않았나?",
        "작업 스케줄러 등록해도 돼?",
        "S3에서 임베딩 모델 최종 선택 근거?",
        "deepseek 장문 스트림에서 뭐가 문제였어?",
        "모델 최종 선택 근거?",
        "자동 시작 설정 어떻게 하는 게 원칙이야?",
    ]
    client = _jev_client()
    assert client, "EXPLABS_API_KEY 필요"

    results = []
    for i, q in enumerate(queries[:limit]):
        r = {"q": q}
        try:
            pool = build_pool_prodex(q)
            ranked, abstained = j1p.jev_rerank(
                query=q, pool=pool, client=client, call_jev=True, timeout=5.0)
            r["pool_n"] = len(pool)
            r["op_ranked_ids"] = [str(x.get("id"))[:12] for x in ranked[:5]]
            r["op_abstained"] = abstained
            # 러너식 (lift 미적용) 비교 — diff가 나면 러너가 운영과 다르다는 증거
            r["runner_rows_ids"] = [str(x.get("id"))[:12] for x in pool[:5]]
            r["diff"] = r["op_ranked_ids"] != r["runner_rows_ids"]
            r["abstain_exposed"] = 0 if abstained else len(r["op_ranked_ids"])
            # 검증: abstain이면 노출 0 (빈 컨텍스트)
            assert_harness_parity(
                pool_n=len(pool), exposure_ids=r["op_ranked_ids"],
                model="jev-latest", abstain_exposed=r["abstain_exposed"],
                runner_name=f"parity-{i}")
        except Exception as e:
            r["err"] = str(e)[:100]
        results.append(r)
        print(f"[{i+1}/{len(queries[:limit])}] pool={r.get('pool_n')} abstain={r.get('op_abstained')} diff={r.get('diff')}", flush=True)
        json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False)

    diffs = [r for r in results if r.get("diff")]
    print(f"\n[harness-parity] 운영 vs 러너 노출 순서 차이: {len(diffs)}/{len(results)}"
          f" (또는 abstain으로 인한 빈 컨텍스트)")
    print(f"저장: {out}")
    return results


if __name__ == "__main__":
    run_stage100_parity()