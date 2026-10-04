"""pointwise noul 형식 테스트 — run_exp8a_rerun 재사용"""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.stdout.reconfigure(encoding="utf-8")

import importlib.util
spec = importlib.util.spec_from_file_location("rerun", os.path.join(HERE, "run_exp8a_rerun.py"))
rerun = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rerun)

q = "camelAI auto 라우팅에서 어려운 과제는 어떤 모델로 보내졌어?"
key = rerun.rot.next()
pool = rerun.stage1_pool(q, k=40)

import sqlite3
LIVE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
by_id = set()
for tbl in ["working_memory", "episodic_memory"]:
    for r in conn.execute(f"SELECT id FROM {tbl}"):
        by_id.add(r[0])
conn.close()
pool = [p for p in pool if p.get("id") in by_id]
cands = pool[:40]
print(f"pool {len(cands)}건")

scores, cost, err = rerun.pointwise_call(key, q, cands)
print(f"scores: {scores}")
print(f"cost: {cost} | err: {err}")
if scores:
    print(f"score 수: {len(scores)} | max: {max(scores):.3f} | mean: {sum(scores)/len(scores):.3f}")
    print("검증: score 수 == cands 수:", len(scores) == len(cands))