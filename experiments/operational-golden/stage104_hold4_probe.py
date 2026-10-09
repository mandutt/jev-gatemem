# -*- coding: utf-8 -*-
"""stage104 — agentmemory 검토 보류 4건 0콜 실측 (2026-10-09)

① `_adjusted` 강등 유병률: stage87 op 90 gold_rank vs 기존 raw의 RRF/lane rank 비교로 '강등 실측'
   (exp8a의 'score·signal 재정렬 강등' 사례가 전체적으로 몇 건인지)
② 자동 supersede(Jaccard>0.9) 후보 쌍: mem0 프로브 확장 — 최근 active 행 간 Jaccard>0.9 쌍 전수
③ retention 점수 0콜 시뮬: salience·e^{-λt} + access 강화 → tier 분포·evictable 후보 성격
④ 작업 지시형 pool 진입율: 최근 trace |pool| 쿼리 vs |jev| abstain 행동
"""
import sqlite3, re, json, os, math
from collections import Counter

DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
TRACE_DIR = r"C:\Users\mandu\AppData\Local\hermes\logs"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage104_hold4_raw.json")

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

result = {}

# ============ ③ retention 0콜 시뮬 (먼저 — DB만 사용) ============
rows = cur.execute("""
    SELECT id, content, importance, created_at, superseded_by, valid_until,
           memory_type, source, recall_count, last_recalled
    FROM working_memory
""").fetchall()
active = [r for r in rows if not r["superseded_by"] and (not r["valid_until"] or r["valid_until"] > "2026-10-09")]
print(f"[retention] 전체 {len(rows)} / active {len(active)}")

def salience(r):
    base = 0.5
    mtype = (r["memory_type"] or "").lower()
    type_w = {"architecture": 0.9, "bug": 0.7, "pattern": 0.8, "preference": 0.85,
              "workflow": 0.6, "fact": 0.5}
    base = type_w.get(mtype, 0.5)
    rc = r["recall_count"] or 0
    return min(1.0, base + min(0.2, rc * 0.02))

def retention_score(r, lam, sigma):
    sal = salience(r)
    t = max(0.0, (datetime_ts(r["created_at"]) ) )
    return None

def datetime_ts(s):
    import datetime
    if not s: return 0
    s = str(s)[:19].replace("T", " ")
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        try:
            return datetime.datetime.strptime(str(s)[:10], "%Y-%m-%d").timestamp()
        except Exception:
            return 0

now = datetime_ts("2026-10-09 14:00:00")
if now == 0:
    import time; now = time.time()

def compute(lam, sigma):
    scored = []
    for r in active:
        t_days = max(0.0, (now - datetime_ts(r["created_at"])) / 86400.0)
        decay = math.exp(-lam * t_days)
        # access 강화: recall_count -> 최근성은 last_recalled로 근사
        boost = 0.0
        lr = r["last_recalled"]
        if lr and datetime_ts(lr) > 0:
            d = (now - datetime_ts(lr)) / 86400.0
            if d > 0:
                boost += sigma / d
        score = min(1.0, salience(r) * decay + boost)
        scored.append((r, score))
    return scored

def tiers(scored, hot=0.7, warm=0.4, cold=0.15):
    c = Counter()
    for _, s in scored:
        if s >= hot: c["hot"] += 1
        elif s >= warm: c["warm"] += 1
        elif s >= cold: c["cold"] += 1
        else: c["evictable"] += 1
    return dict(c)

sim = {}
for lam, sigma in [(0.01, 0.3), (0.05, 0.3), (0.01, 0.0), (0.1, 0.3)]:
    sc = compute(lam, sigma)
    sim[f"λ={lam}/σ={sigma}"] = {
        "tiers": tiers(sc),
        "evictable": [r["id"] for r, s in sc if s < 0.15][:20],
        "evictable_n": sum(1 for _, s in sc if s < 0.15),
        "evictable_importance": Counter(
            (r["importance"] if r["importance"] is not None else 0.5) for r, s in sc if s < 0.15),
    }
result["retention"] = sim
print("[retention] λ=0.01/σ=0.3 tiers:", sim["λ=0.01/σ=0.3"]["tiers"],
      "evictable:", sim["λ=0.01/σ=0.3"]["evictable_n"])
# evictable 후보 상세 (성격 판정용)
ev0 = sorted([(r, s) for r, s in compute(0.01, 0.3) if s < 0.15], key=lambda x: x[1])
sim["λ=0.01/σ=0.3"]["evictable_detail"] = {
    "importance": Counter((r["importance"] if r["importance"] is not None else 0.5) for r, _ in ev0),
    "types": Counter((r["memory_type"] or "?") for r, _ in ev0),
    "samples": [{"id": r["id"], "imp": r["importance"], "type": r["memory_type"],
                 "age_days": round((now - datetime_ts(r["created_at"])) / 86400.0, 1),
                 "content": (r["content"] or "")[:80]} for r, _ in ev0[:5]],
}

# ============ ② Jaccard>0.9 쌍 (최근 300 active 행) ============
def norm(s):
    s = re.sub(r"\[(USER|ASSISTANT|SYSTEM)\]", "", s or "")
    return re.sub(r"\s+", " ", s).strip()

def toks(s):
    s = norm(s)
    return set(re.findall(r"[가-힣]{2,}|[A-Za-z_][A-Za-z0-9_]{2,}", s.lower()))

def jac(a, b):
    sa, sb = toks(a), toks(b)
    if not sa or not sb: return 0.0
    inter = sa & sb
    return len(inter) / (len(sa) + len(sb) - len(inter))

recent = sorted(active, key=lambda r: datetime_ts(r["created_at"]), reverse=True)[:300]
pairs = []
for i in range(len(recent)):
    for j in range(i + 1, len(recent)):
        s = jac(recent[i]["content"], recent[j]["content"])
        if s > 0.9:
            pairs.append({
                "sim": round(s, 3),
                "id1": recent[i]["id"], "id2": recent[j]["id"],
                "c1": norm(recent[i]["content"])[:90], "c2": norm(recent[j]["content"])[:90],
                "t1": (recent[i]["created_at"] or "")[:10], "t2": (recent[j]["created_at"] or "")[:10],
            })
pairs.sort(key=lambda p: -p["sim"])
# mem0 프로브: 정확 중복(content 동일) 그룹
exact = cur.execute("""
    SELECT content, COUNT(*) c FROM working_memory
    GROUP BY content HAVING c > 1 ORDER BY c DESC
""").fetchall()
result["jaccard"] = {
    "pairs_over_0.9": len(pairs),
    "top_pairs": pairs[:20],
    "exact_dup_groups": len(exact),
    "exact_dup_rows": sum(r["c"] for r in exact),
}
print(f"[jaccard] 쌍(300행): {len(pairs)} / 정확중복 그룹 {len(exact)}·행 {sum(r['c'] for r in exact)}")

# ============ ① gold_rank 유병률 — stage87 (production-exact, op 90) ============
# agentmemory 보류 ①의 선행: 'JEV choice 후에도 top-7 밖' gold 유병률.
# stage79~82에서 재정렬 정책 A(RRF 보존)/B(평균 순위)는 3셋 회귀로 기각(noans FP +2~5) —
# 여기서는 유병률 확인만.
try:
    s87 = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage87_exposure_k.json", encoding="utf-8"))
    op87 = s87["k5"]["op"]
    ranks = [r["gold_rank"] for r in op87 if r.get("gold_rank") is not None]
    demoted = [r for r in op87 if r.get("gold_rank") is not None and r["gold_rank"] >= 8]
    result["adjusted_demotion"] = {
        "stage87_op_gold_rank": {
            "n": len(ranks),
            "min": min(ranks), "max": max(ranks),
            "rank>=8": len(demoted),
            "rank>=8_idx": [r["i"] for r in demoted],
            "dist": dict(sorted(Counter(ranks).items())),
        },
        "note": "gold_rank>=8 = JEV choice 후에도 top-7 밖(게이트/RRF 병합/재정렬 누적). stage79~82에서 A/B 기각 — 유병률 확인용."
    }
    print(f"[adjusted] stage87 op gold_rank>=8: {len(demoted)}/{len(ranks)} (max {max(ranks)})")
except Exception as e:
    result["adjusted_demotion"] = {"error": str(e)}
    print("[adjusted] stage87 조회 실패:", e)

# ============ ④ trace 쿼리 전체 저장 (regex 단정 대신 전수 검토용) ============
queries = []
for fn in sorted(os.listdir(TRACE_DIR)):
    if not fn.startswith("jev_trace_20261009"): continue
    for line in open(os.path.join(TRACE_DIR, fn), encoding="utf-8", errors="replace"):
        if "|pool|" in line:
            m = re.search(r"query=([^ ]+)", line)
            if m:
                queries.append({"q": m.group(1), "ts": line[:19], "line": line.strip()[:240]})
result["trace"] = {"pool_events": len(queries), "queries_all": queries[:80]}
print(f"[trace] pool 쿼리 {len(queries)}건 저장")

json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n저장:", OUT)