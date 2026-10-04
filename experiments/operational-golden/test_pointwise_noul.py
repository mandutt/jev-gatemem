"""pointwise noul 형식 2건 테스트 (exp8a 재실행 전 검증)"""
import sys, os, json, time
sys.path.insert(0, "experiments/operational-golden")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("MNEMOSYNE_DB", os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db"))

from experiments.operational_golden.run_exp8a_rerun import pointwise_call, rot, stage1_pool, by_id  # noqa
# by_id는 main 안에서 정의 — 직접 로드
import sqlite3
LIVE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
by_id = set()
conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
for tbl in ["working_memory", "episodic_memory"]:
    for r in conn.execute(f"SELECT id FROM {tbl}"):
        by_id.add(r[0])
conn.close()

# 1건만 테스트
q = "camelAI auto 라우팅에서 어려운 과제는 어떤 모델로 보내졌어?"
pool = stage1_pool(q, k=40)
pool = [p for p in pool if p.get("id") in by_id]
cands = pool[:40]
print(f"pool {len(cands)}건")

key = rot.next()
scores, cost, err = pointwise_call(key, q, cands)
print(f"scores: {scores}")
print(f"cost: {cost} | err: {err}")
if scores:
    print(f"score 수: {len(scores)} | max: {max(scores):.3f} | mean: {sum(scores)/len(scores):.3f}")
    print("검증: score 수 == cands 수:", len(scores) == len(cands))