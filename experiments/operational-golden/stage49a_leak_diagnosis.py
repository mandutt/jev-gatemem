# -*- coding: utf-8 -*-
"""stage49a: stage48 리플레이 누수 진단 (0콜)

B AI 가설 검증:
  H1 (자기참조 누수): 무답 22건의 pool 상위 행이 "쿼리 자신 또는 그 답변"의 근복제(배킹 sim≥0.85)이고
                      created_at이 쿼리 도착일(10-05~06)과 같으면 → 리플레이만의 유령 정답 (누수)
  H0 (실재 무력):     pool 상위 행이 주제 근접 이웃(sim 0.4~0.7)이고 수개월 전 기록이면 → abstain 무력은 실재

추가: A AI retrieval floor — no vs yes 그룹의 pool[0] vec_sim 분포 (컷오프 0.25 시뮬레이션)
"""
import os, re, sys, json, sqlite3, glob

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import stage48_live60_cross as m
from mnemosyne.core import embeddings as emb_mod

SNAP = m.SNAP
s = sqlite3.connect(SNAP)
s.row_factory = sqlite3.Row

# 사용자 판정 (시트 순서, stage48 러너의 시트 순서와 동일)
VERDICTS = {
 "1": "no", "2": "no", "3": "yes", "4": "yes", "5": "no", "6": "no", "7": "yes", "8": "yes", "9": "no", "10": "yes",
 "11": "no", "12": "yes", "13": "yes", "14": "yes", "15": "yes", "16": "no", "17": "yes", "18": "yes", "19": "no", "20": "yes",
 "21": "no", "22": "yes", "23": "yes", "24": "yes", "25": "no", "26": "no", "27": "yes", "28": "yes", "29": "no", "30": "yes",
 "31": "maybe", "32": "yes", "33": "no", "34": "yes", "35": "yes", "36": "no", "37": "yes", "38": "yes", "39": "yes", "40": "no",
 "41": "maybe", "42": "yes", "43": "yes", "44": "yes", "45": "yes", "46": "no", "47": "yes", "48": "no", "49": "yes", "50": "no",
 "51": "maybe", "52": "no", "53": "no", "54": "yes", "55": "no", "56": "no", "57": "yes", "58": "yes", "59": "yes", "60": "yes"
}

def norm(t):
    return re.sub(r"\s+", "", (t or "").lower())

def content_of(row_id):
    r = s.execute("SELECT content, created_at, timestamp, source, session_id FROM working_memory WHERE id=?", (row_id,)).fetchone()
    if r: return dict(r), "wm"
    r = s.execute("SELECT content, created_at, timestamp, source, session_id FROM episodic_memory WHERE id=?", (row_id,)).fetchone()
    return (dict(r) if r else None), ("em" if r else None)

qs = m.load_queries(None)
assert len(qs) == 60
qtexts = [q for q in qs]
qembs = emb_mod.embed(qtexts)

out = []
for qi, (q, qemb) in enumerate(zip(qtexts, qembs), 1):
    verdict = VERDICTS[str(qi)]
    rows = m.build_pool(s, q)
    n = norm(q)
    top = rows[:6]
    # 임베딩 유사도 (top-6)
    sims = []
    if top:
        cembs = emb_mod.embed([(c.get("content") or "")[:1000] for c in top])
        for c, cemb in zip(top, cembs):
            if qemb is None or cemb is None:
                sims.append(0.0); continue
            qv = qemb; cv = cemb
            dot = sum(a*b for a, b in zip(qv, cv))
            nq = sum(a*a for a in qv) ** 0.5 or 1.0
            nc = sum(a*a for a in cv) ** 0.5 or 1.0
            sims.append(dot/(nq*nc))
    # containment: 쿼리가 본문에 그대로 들어있거나 본문이 쿼리에 들어있는 경우
    contain = None
    near_dup_idx = None
    for i, c in enumerate(top):
        cc = c.get("content") or ""
        cn = norm(cc)
        if len(n) >= 12 and (n in cn or (len(cn) >= 12 and cn in n)):
            contain = i
            break
    if sims:
        mx = max(range(len(sims)), key=lambda i: sims[i])
        if sims[mx] >= 0.85:
            near_dup_idx = mx
    # top 행들의 생성 시각
    times = []
    for c in top[:3]:
        meta, _src = content_of(c.get("id") or "")
        times.append((meta or {}).get("created_at", "?"))
    out.append({
        "idx": qi, "verdict": verdict, "query": q, "pool_n": len(rows),
        "top_sims": [round(float(x), 3) for x in sims],
        "max_sim": round(float(max(sims)), 3) if sims else None,
        "near_dup": near_dup_idx, "contain": contain,
        "top_created": times,
    })
    print(f"[{verdict:5}] q{qi:02d} pool={len(rows):3d} max_sim={out[-1]['max_sim']} near_dup={near_dup_idx} contain={contain} created0={times[0] if times else '?'} | {q[:36]}")

# 요약
def summarize(group):
    g = [o for o in out if o["verdict"] in group]
    ms = [o["max_sim"] for o in g if o["max_sim"] is not None]
    nd = sum(1 for o in g if o["near_dup"] is not None)
    ct = sum(1 for o in g if o["contain"] is not None)
    same_day = sum(1 for o in g if o["top_created"] and o["top_created"][0] and o["top_created"][0].startswith("2026-10-0"))
    floor025 = sum(1 for o in g if o["top_sims"] and o["top_sims"][0] < 0.25)
    return {"n": len(g), "max_sim_med": sorted(ms)[len(ms)//2] if ms else None,
            "max_sim_min": min(ms) if ms else None, "near_dup_cnt": nd, "contain_cnt": ct,
            "top1_same_week_1006": same_day, "floor_lt025": floor025}

print("\n=== 요약 ===")
print("no(22):  ", summarize(["no"]))
print("yes(35): ", summarize(["yes"]))
print("maybe(3):", summarize(["maybe"]))

json.dump(out, open(os.path.join(REPO, "experiments", "operational-golden", "data", "stage49a_leak_diagnosis.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n저장: data/stage49a_leak_diagnosis.json")
