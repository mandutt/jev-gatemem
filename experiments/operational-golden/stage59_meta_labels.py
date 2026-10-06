# -*- coding: utf-8 -*-
"""stage59: read-path meta 라벨 실험 (2026-10-06, JEV 120콜)

배경: stage58 — 라이브 IRREL 오주입의 공급원은 '규칙/프로필 행 클러스터'(허브 84%,
그 외 규칙 행 4종이 상호 대체). 개별 제거 불가 + VALID 5건이 의존.
대안: choice criteria 라벨에 행 출처(meta)를 포함 → JEV가 '규칙/사용자 선호' 행을
'규칙 질문일 때만' 정답으로 인식하도록.

조건:
- base: 현행 excerpt 라벨
- meta: 규칙 클러스터 행 id에 접두 "[USER-RULE|사용자 규칙·선호 메모리] " 추가

셋: 라이브 60 (49c human verdicts 기준 — block 38 / valid 5 / yes 17)
KPI: block abstain 수(↑) · valid+yes 오차단(↓) · err 0
콜: 60 × 2 = 120콜 (같은 세션 paired)
규칙 클러스터 id: stage58에서 확인된 6개
"""
import os, sys, json, sqlite3, time

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod
from jev_mem_core.pipeline import _jev_client

SNAP = m48.SNAP
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row

ABSTAIN_CUR = m48.ABSTAIN_CURRENT
INSTR = m48.INSTR

# stage58에서 확인된 규칙/프로필 클러스터 id (전방 16자)
RULE_IDS = {
    "d1c90516d9870c95",  # default 프로필 규칙 (허브, 32건)
    "2ecef73164830638",  # 사용자 제약/스타일
    "9f04ed2c8e14f11b",  # 설계 확정(ADR Final)
    "5a3ebc06a87940da",  # 설계 리뷰
    "a13019e1f438960c",  # 감사/리뷰 산출물 형식
    "1cef4743165b7707",  # 아키텍처 선호
}
META_PREFIX = "[USER-RULE|사용자 규칙·선호 메모리] "

def get_full_id(row):
    return (row.get("id") or "")[:16]

def recall_raw_factory(q):
    def recall_raw(kind, arg, kk):
        if kind == "fts": return beam_mod._fts_search_working(s, arg, k=kk)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(s, qemb[0], k=kk)
        if kind == "imp": return j1p._imp_search(s, k=kk)
        if kind == "graph": return j1p._graph_lane_search(s, arg, kk)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw

def build_pool(q):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    return j1p._filter_and_rank(pool, q)[:60]

CLIENT = _jev_client(); assert CLIENT
_API = getattr(CLIENT, "_jev_api", None)
_rot_i = getattr(CLIENT, "_jev_rotator", None)
if _rot_i is not None and hasattr(_rot_i, "_active"):
    _act = _rot_i._active()
    if len(_act) >= 2:
        CLIENT.headers["Authorization"] = f"Bearer {_act[1][1]}"
        sys.stderr.write(f"[start] {_act[1][0]}\n")

_LAST_CALL = [0.0]
def throttle():
    while True:
        now = time.time()
        if now - _LAST_CALL[0] >= 0.34:
            _LAST_CALL[0] = now; return
        time.sleep(0.05)

def post(state, questions):
    rot = getattr(CLIENT, "_jev_rotator", None)
    for attempt in range(10):
        throttle()
        try:
            resp = CLIENT.post(_API, json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=25)
            if resp.status_code == 429:
                if rot is not None and hasattr(rot, "on_429"):
                    try: nk = rot.on_429()
                    except Exception: nk = None
                    if nk: CLIENT.headers["Authorization"] = f"Bearer {nk}"
                time.sleep(2.0); continue
            if resp.status_code == 503:
                time.sleep(3.0); continue
            return resp
        except Exception:
            time.sleep(2.0)
    return None

def run_choice(q, rows, meta):
    labels = []
    for c in rows:
        ex = j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a"
        if meta and get_full_id(c) in RULE_IDS:
            ex = META_PREFIX + ex
        labels.append(ex)
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows)
    qs = {"best": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200:
        return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    abstain = (idx is None) or (idx == len(jl)-1) or (ap > 0.3)
    return idx, abstain, None

# 라이브 60 쿼리
queries = m48.load_queries(s)
print(f"라이브 60: {len(queries)}건", flush=True)
# 49c human verdicts 로드
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
# query → cls
q_cls = {}
for r, l in zip(d49c, [V2[verdicts[str(x["idx"])]] for x in d49c]):
    q_cls[r["query"]] = l
print("cls 분포:", {k: sum(1 for q in queries if q_cls.get(q) == k) for k in ("block", "valid", "yes")}, flush=True)

pools = {q: build_pool(q) for q in queries}
print("pool 구성 완료", flush=True)

# 규칙 행이 pool에 있는지 확인
rule_in_pool = sum(1 for q in queries if any(get_full_id(c) in RULE_IDS for c in pools[q]))
print(f"규칙 클러스터 행이 pool에 있는 쿼리: {rule_in_pool}/60", flush=True)

results = {"base": [], "meta": []}
t0 = time.time()
for cond, meta in (("base", False), ("meta", True)):
    for qi, q in enumerate(queries, 1):
        rows = pools[q]
        idx, abst, err = run_choice(q, rows, meta)
        results[cond].append({"query": q, "cls": q_cls.get(q), "abstain": abst, "err": err,
                              "choice_idx": idx, "pool_n": len(rows)})
    blk_abst = sum(1 for r in results[cond] if r["cls"] == "block" and r["abstain"] and not r["err"])
    val_abst = sum(1 for r in results[cond] if r["cls"] in ("valid", "yes") and r["abstain"] and not r["err"])
    err_n = sum(1 for r in results[cond] if r["err"])
    print(f"{cond}: block abstain {blk_abst}/38 · valid+yes 오차단 {val_abst}/22 · err {err_n} ({time.time()-t0:.0f}s)", flush=True)

json.dump(results, open(os.path.join(DATA, "stage59_meta_labels.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage59_meta_labels.json")
# 쿼리별 대조
print("\n=== block 쿼리별 abstain (base vs meta) ===")
for b, m in zip(results["base"], results["meta"]):
    if b["cls"] == "block" and (b["abstain"] != m["abstain"]):
        print(f"  {'ABSTAIN' if m['abstain'] else 'pick':8} | {b['query'][:45]}")
print("=== valid/yes 오차단 대조 ===")
for b, m in zip(results["base"], results["meta"]):
    if b["cls"] in ("valid", "yes") and (b["abstain"] != m["abstain"]):
        print(f"  {b['cls']:5} | base={'A' if b['abstain'] else 'P'} meta={'A' if m['abstain'] else 'P'} | {b['query'][:45]}")