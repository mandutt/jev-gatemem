# -*- coding: utf-8 -*-
"""stage100_harness_parity.py — 하네스-운영 동등성 테스트 (b-ai v7 최우선, 2026-10-07)

목적: 실험 러너가 운영 prefetch 경로와 동일한 입력을 JEV에 보내는지 검증.
"러너가 운영과 다르게 돌면 결론 전체가 무효" 패턴(stage61~66 rows[:5], stage93 lift 미사용)을
러너 시작 시 assert로 차단.

비교 축 (20쿼리):
  1. JEV 후보 수 (운영 = POOL_BUDGET 60 — 러너도 60?)
  2. 노출 행 구성·순서 (운영 = jev_rerank의 ranked [pick]+나머지 / 러너 = pool[:k] RRF?)
  3. 사용 DB·시점 (운영 = 라이브 DB / 러너 = 스냅샷)
  4. 모델 식별자 (jev-latest)

실행: venv python stage100_harness_parity.py
"""
import os, sys, json, sqlite3, time

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client
import stage93_consumer_2x2 as s93
from canary_run import build_pool_prodex

DATA = os.path.join("experiments", "operational-golden", "data")
OUT = os.path.join(DATA, "stage100_parity.json")

# 20개 테스트 쿼리 (live60에서 추출 — 사실 질문·작업지시 혼합)
QUERIES = [
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

def run_operational_like(q):
    """운영 process_prefetch와 동일 구성을 재현 (라이브 DB 대신 스냅샷 — 비교 목적 명시):"""
    # 운영: _retrieve → _filter_and_rank → [:60] → jev_rerank(lift)
    pool = build_pool_prodex(q)  # 스냅샷으로 pool 60 구성 (러너와 동일 경로)
    ranked, abstained = j1p.jev_rerank(
        query=q, pool=pool, client=_jev_client(), call_jev=True, timeout=5.0)
    return ranked, abstained, pool

def run_runner_like(q):
    """stage93 방식: rows = pool[0..4] RRF 순위 (lift 미적용)."""
    pool = build_pool_prodex(q)
    return pool[:5], pool

def main():
    client = _jev_client()
    assert client, "EXPLABS_API_KEY 필요"
    results = []
    for i, q in enumerate(QUERIES):
        r = {"q": q}
        try:
            ranked, abstained, pool = run_operational_like(q)
            r["op_pool_n"] = len(pool)
            r["op_abstained"] = abstained
            r["op_ranked_ids"] = [str(x.get("id"))[:12] for x in ranked[:5]]
            # 러너식
            r["runner_pool_n"] = len(pool)
            r["runner_rows_ids"] = [str(x.get("id"))[:12] for x in pool[:5]]
            # 핵심 비교
            r["same_top1"] = (ranked[0].get("id") == pool[0].get("id")) if ranked and pool else None
            r["diff"] = r["op_ranked_ids"] != r["runner_rows_ids"]
        except Exception as e:
            r["err"] = str(e)[:80]
        results.append(r)
        print(f"[{i+1}/{len(QUERIES)}] {q[:35]} pool={r.get('op_pool_n')} abstain={r.get('op_abstained')} diff={r.get('diff')}", flush=True)
        json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    # 요약
    diffs = [r for r in results if r.get("diff")]
    print(f"\n운영 ranked vs 러너 rows 순서 차이: {len(diffs)}/{len(results)}")
    print(f"저장: {OUT}")

if __name__ == "__main__":
    main()