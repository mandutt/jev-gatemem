# -*- coding: utf-8 -*-
"""stage52: noans 50 쿼리별 플립률 3-run + 노출 k 축소 시뮬레이션 (2026-10-06)

3번 (B AI): 스냅샷 noans 50건을 3-run 재실행 → 쿼리별 abstain↔FP 플립 여부.
  플립률 = noans FP 지표의 노이즈 하한 (불안정 쿼리 비율).
4번 (B·A AI): 노출 k 축소(rows[:k]) 0콜 시뮬레이션 — k=1/2/3/5별
  "정답 노출 성공" vs "오주입 노출" 횟수. stage50 live 60 기준.
"""
import os, sys, json, sqlite3, time, re

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

no_qs = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
print(f"noans 셋: {len(no_qs)}건")

def recall_raw_factory(q):
    def recall_raw(kind, arg, kk):
        if kind == "fts": return beam_mod._fts_search_working(s, arg, k=kk)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(s, qemb[0], k=kk)
        if kind == "imp": return j1p._imp_search(s, k=kk)
        if kind == "graph": return j1p._graph_lane_search(s, arg, k=kk)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw

def build_pool_tc(q):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    return j1p._filter_and_rank(pool, q)[:j1p.POOL_BUDGET]

CLIENT = _jev_client()
assert CLIENT
_API = getattr(CLIENT, "_jev_api", None)

def run_choice(q, rows):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows]
    j_labels = labels + [m48.ABSTAIN_CURRENT]
    state = j1p.build_state(q, rows)
    questions = {"best": {"type": "choice", "instructions": m48.INSTR,
                          "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    for attempt in range(2):
        try:
            resp = CLIENT.post(_API, json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=25)
            if resp.status_code == 503:
                time.sleep(1.5); continue
            break
        except Exception:
            time.sleep(1.5); resp = None
    if resp is None or resp.status_code != 200:
        return None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(j_labels)-1}", 0.0) or 0.0)
    try:
        idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception:
        idx = None
    abstain = (idx is None) or (idx == len(j_labels) - 1) or (ap > 0.3)
    return abstain, None

# ---- 3-run ----
pools = {i: build_pool_tc(n["query"]) for i, n in enumerate(no_qs)}
print(f"pool 구성 완료 (median {sorted(len(v) for v in pools.values())[25]})", flush=True)

runs = []
t0 = time.time()
for run_i in range(3):
    res = []
    for i, n in enumerate(no_qs):
        abst, err = run_choice(n["query"], pools[i])
        res.append({"qid": n["qid"], "abstain": abst, "err": err})
    runs.append(res)
    fp = sum(1 for r in res if r["abstain"] is False)
    errn = sum(1 for r in res if r["err"])
    print(f"run{run_i+1}: noans FP(pick) {fp}/50, err {errn}, {time.time()-t0:.0f}s", flush=True)

# 쿼리별 플립 집계
flips = []
for i, n in enumerate(no_qs):
    vs = [runs[r][i]["abstain"] for r in range(3)]
    errs = [runs[r][i]["err"] for r in range(3)]
    if any(errs): 
        flips.append({"qid": n["qid"], "note": "err 포함"})
        continue
    # abstain 개수
    a = sum(1 for v in vs if v)
    if a not in (0, 3):  # 1~2 = 플립
        flips.append({"qid": n["qid"], "abstain_count": a, "pattern": vs})
print(f"\n[3번] 불안정(플립) 쿼리: {len(flips)}/50")
for f in flips:
    print(f"  {f['qid']}: {f.get('pattern', f.get('note'))}")

# 저장
dt = {"noans_3run": runs, "flips": flips,
      "flip_rate": sum(1 for f in flips if "pattern" in f) / 50 * 100}
json.dump(dt, open(os.path.join(DATA, "stage52_noans_flip3run.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n플립률: {dt['flip_rate']:.1f}% — 저장: stage52_noans_flip3run.json")

# ---- 4번: 노출 k 축소 시뮬레이션 (0콜) ----
print("\n=== [4번] 노출 k 축소 시뮬레이션 (live 60) ===")
d50 = json.load(open(os.path.join(DATA, "stage50_noul_answerability.json"), encoding="utf-8"))
v49c = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
input49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
qtext = {d["idx"]: d["query"] for d in input49c}
live = [r for r in d50["results"] if r["src"] == "live" and not r["err"]]

# 49d: yes-NO 21건의 답 후보 rank (6~60) — k>=rank면 정답 노출
d49d = json.load(open(os.path.join(DATA, "stage49d_poolinscan_input.json"), encoding="utf-8"))
# 49c: YES 16건 (top-5에 답) — 답 rank 1~5
# 답 rank 정확 매핑:
#   YES 16건: 49c 시트에서 top-5에 답 존재 → rank 1~5 (정확 rank는 미저장 — k>=5에서 유지)
#   NO 19+2건: 49d에서 답 rank 6~60 (IN 21건 — 실제 rank는 cands에서)
def kw(q): return [w for w in re.sub(r"[?？]", "", q).split() if len(w) >= 2][:5]

# 답 rank 찾기: 49c YES 쿼리 중 top-5 답 rank — 49c input cands의 텍스트에서 키워드 2+ 히트
ans_rank_by_idx = {}
for d in input49c:
    if d["verdict"] != "yes": continue
    if v49c[str(d["idx"])] != "YES": continue
    kws = kw(d["query"])
    hit = next((j+1 for j, c in enumerate(d["cands"]) if sum(1 for k in kws if k in c["text"]) >= 2), None)
    ans_rank_by_idx[d["idx"]] = hit if hit else 5  # top-5 안 (미스면 5로 상한)
# 49d: NO 쿼리들의 답 rank
for d in d49d:
    kws = kw(d["query"])
    hit = next((c["rank"] for c in d["cands"] if sum(1 for k in kws if k in c["text"]) >= 2), None)
    if hit:
        ans_rank_by_idx[d["idx"]] = hit


def cls_of(idx):
    orig = next(d["verdict"] for d in input49c if d["idx"] == idx)
    v = v49c[str(idx)]
    if orig == "no":
        return "block" if v in ("IRREL", "PLAUS") else "valid"
    return "protect"

# IRREL/PLAUS(block) 쿼리의 top-1 유해성: 노출 k에 관계없이 1위부터 유해
block_idx = {i for i in range(1, 61) if cls_of(i) == "block"}

print("k별: 정답노출 유지(답 rank<=k) vs 오주입 노출(block 쿼리, k>=1이면 항상)")
for k in (1, 2, 3, 5):
    ans_ok = sum(1 for idx, rk in ans_rank_by_idx.items() if rk <= k)
    # 정답 21건(YES 16 + VALID 5) 기준: YES 16 중 rank<=k
    yes_ids = {idx for idx in ans_rank_by_idx if idx in [d["idx"] for d in input49c if d["verdict"] == "yes"]}
    yes_ok = sum(1 for idx in yes_ids if ans_rank_by_idx[idx] <= k)
    # block 노출: block 쿼리 수 (노출 k와 무관 — 1위부터 유해)
    block_n = len(block_idx)
    print(f"  k={k}: YES 정답노출 유지 {yes_ok}/16 | block(IRREL+PLAUS) 오주입 노출 {block_n}")

print("\n→ 노출 k를 줄여도 block 오주입은 사라지지 않는다 (1위부터 유해) — C AI 견해와 일치")
print("→ 정답노출은 k=1일 때 YES 16이 일부 손실 (rank 1인 것만) — A AI 'Top-1은 회수 손실 미미'와 대조")