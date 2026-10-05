"""stage39: abstain 라벨 문구 — 동일 pool 고정 재검증 (2026-10-06)

stage32 raw(hybrid pool30, 2026-10-06 00:27)의 noans 50건 pool_ids + labels를
그대로 재사용해, 라벨 문구만 바꿔 choice 1콜씩 재호출.

- pool 고정 → DB 시점 변화 효과 제거 ("noans 셋 변질" 이슈 격리)
- 비교: current 라벨 vs improved 라벨 (세 AI 제안 문구)
- 동일 조건: pool 30, state는 stage32와 동일 구성(win-300 excerpt 150)
- 실패 기준 (C AI): noans FPR이 current보다 2건 이상 증가하면 폐기

런너: stage32 hybrid 결과에서 noans 50건의 query pool 정보를 로드.
"""
import sys, os, time, json, sqlite3, sqlite_vec
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware")

from gateway import j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client

ABSTAIN_LABEL_IMPROVED = (
    "No candidate contains the specific fact, value, version, or decision the "
    "question asks for — same-topic mention alone is not evidence"
)

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
s32 = json.load(open(os.path.join(DATA, "stage32_hybrid_pool30.json"), encoding="utf-8"))["records"]
noans32 = [r for r in s32 if r["grp"] == "noans" and r.get("pool_ids")]

# stage32에서 labels는 _query_window(content, query, 300)[:150] 형태였다.
# pool_ids는 있지만 labels는 저장 안 됨 → content 재조회로 라벨 재구성 (win-300 동일 규칙)
conn = sqlite3.connect(r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db")
conn.row_factory = sqlite3.Row

def get_content(mid):
    r = conn.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (mid,)).fetchone()
    if not r:
        r = conn.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (mid,)).fetchone()
    if not r: return None
    return {"id": r[0], "content": r[1], "importance": r[2]}

def labels_for(pool_ids, query):
    labs = []
    for mid in pool_ids:
        row = get_content(mid)
        if row and row["content"]:
            labs.append(j1p._excerpt(j1p._query_window(row["content"], query, 300), 150) or "n/a")
        else:
            labs.append("n/a")
    return labs

client = _jev_client()
print("client:", "OK" if client else "NONE", flush=True)
print(f"stage32 noans pool 보유 {len(noans32)}건 — 재호출", flush=True)

results = []
for cond, label in [("current", j1p.ABSTAIN_LABEL), ("improved", ABSTAIN_LABEL_IMPROVED)]:
    print(f"\n=== {cond} 라벨 (pool 고정) ===", flush=True)
    for i, r in enumerate(noans32, 1):
        q = r["query"]
        pool_ids = r["pool_ids"]
        labels = labels_for(pool_ids, q)
        # stage32와 동일: pool캡 30 (이미 30)
        state = j1p.build_state(q, [get_content(mid) for mid in pool_ids])
        t0 = time.perf_counter()
        orig = j1p.ABSTAIN_LABEL
        j1p.ABSTAIN_LABEL = label
        try:
            if os.environ.get("JEV_ABSTAIN") == "0":
                idx, abstain_p, probs = j1p._jev_choice(client, state, labels, timeout=10.0)
                abstained = False
            else:
                idx, abstain_p, probs = j1p._jev_choice(client, state, labels, timeout=10.0)
                abstained = (idx is not None and idx == len(labels)) or (abstain_p > j1p._SOFT_ABSTAIN_TAU)
        finally:
            j1p.ABSTAIN_LABEL = orig
        results.append({
            "cond": cond, "query": q, "abstained": bool(abstained),
            "abstain_p": round(abstain_p, 3),
            "idx": idx, "pool_n": len(pool_ids),
            "lat_ms": int((time.perf_counter() - t0) * 1000),
        })
        if i % 25 == 0:
            print(f"  {i}/{len(noans32)}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "abstain-label-poolfixed",
           "records": results},
          open(os.path.join(DATA, "stage39_abstain_label_poolfixed.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# 비교
cur = {r["query"]: r for r in results if r["cond"] == "current"}
imp = {r["query"]: r for r in results if r["cond"] == "improved"}
cur_fp = sum(1 for q, r in cur.items() if not r["abstained"])
imp_fp = sum(1 for q, r in imp.items() if not r["abstained"])
print(f"\n[pool 고정] current noans FP={cur_fp}/50 ({cur_fp/50*100:.1f}%)")
print(f"[pool 고정] improved noans FP={imp_fp}/50 ({imp_fp/50*100:.1f}%)")
print(f"델타={imp_fp-cur_fp:+d}")

# 개별 변화
print("\n=== 개별 변화 (current abstain ↔ improved FP 등) ===")
for q in cur:
    c, g = cur[q], imp[q]
    if c["abstained"] != g["abstained"]:
        print(f"  {q[:50]}: current abs={c['abstained']}(p={c['abstain_p']}) → improved abs={g['abstained']}(p={g['abstain_p']})")
conn.close()