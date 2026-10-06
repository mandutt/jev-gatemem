# -*- coding: utf-8 -*-
"""stage49d-1: yes-NO/maybe-NO 21건의 rank 6~60 후보 추출 (0콜, sim 없이 빠르게)"""
import os, sys, sqlite3, json

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48

SNAP = m48.SNAP
s = sqlite3.connect(SNAP)
s.row_factory = sqlite3.Row

VERDICTS = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
input49c = json.load(open(os.path.join(REPO, "experiments", "operational-golden", "data", "stage49c_label_booster_input.json"), encoding="utf-8"))

targets = []
for d in input49c:
    v = VERDICTS[str(d["idx"])]
    if d["verdict"] == "yes" and v == "NO": targets.append((d["idx"], "yes"))
    elif d["verdict"] == "maybe" and v == "NO": targets.append((d["idx"], "maybe"))

def created_of(rid):
    r = s.execute("SELECT created_at FROM working_memory WHERE id=?", (rid,)).fetchone() \
        or s.execute("SELECT created_at FROM episodic_memory WHERE id=?", (rid,)).fetchone()
    return (r["created_at"] or "?")[:10] if r else "?"

out = []
for idx, grp in targets:
    q = next(d["query"] for d in input49c if d["idx"] == idx)
    rows = m48.build_pool(s, q)
    rest = rows[5:]
    cands = [{"rank": j + 6, "id": (c.get("id") or "")[:16], "created": created_of(c.get("id")),
              "text": (c.get("content") or "")[:260]} for j, c in enumerate(rest)]
    out.append({"idx": idx, "grp": grp, "query": q, "pool_n": len(rows), "rest_n": len(rest), "cands": cands})
    print(f"#{idx:02d} pool={len(rows)} rest={len(rest)} | {q[:40]}", flush=True)

json.dump(out, open(os.path.join(REPO, "experiments", "operational-golden", "data", "stage49d_poolinscan_input.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("input 저장 완료")
