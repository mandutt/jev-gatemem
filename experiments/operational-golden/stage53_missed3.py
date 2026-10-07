# -*- coding: utf-8 -*-
"""stage53: A-7 pool 60→20 / B-4 두 라벨 분리 / C-4 진짜 2콜 실측 (2026-10-06)

3종 AI 검토 미실측 3건을 동일 벤치(live 60 + op 20 + noans 20 = 100쿼리)에서 실측.

구조:
  base      : 현행 (pool 60, choice 1콜, abstain_p>0.3) — 기준선
  pool20    : pool 60→20 축소 후 choice (A-7) — softmax 집중도 회복
  dual_label: abstain 라벨을 2개로 분리 ("주제 유사하나 답 없음" + "후보 전부 무관")
              — abstain_p = 두 라벨 확률 합 (B-4)
  two_call  : 1콜째 choice(60) → winner에 대해 noul 1콜 (winner_noul < 0.5 → abstain) (C-4)

판정 축 (live):
  IRREL 15 차단 수 / 정답(protect) 희생 수 / noans_hard FP
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

# ---- 라벨 ----
ABSTAIN_CUR = m48.ABSTAIN_CURRENT
ABSTAIN_TOPIC = "No candidate contains the specific information the question asks for — some candidates discuss the topic, but none answers it directly"
ABSTAIN_NONE = "No candidate is relevant to the question at all"

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

def build_pool(q, cap):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    return j1p._filter_and_rank(pool, q)[:cap]

CLIENT = _jev_client()
assert CLIENT
_API = getattr(CLIENT, "_jev_api", None)
# 429·일일 한도 대비: 시작 키를 키2(잔여 가능성 높음)로 강제
_rot_i = getattr(CLIENT, "_jev_rotator", None)
if _rot_i is not None and hasattr(_rot_i, "_active"):
    _act = _rot_i._active()
    if len(_act) >= 2:
        _nk = _act[1][1]
        CLIENT.headers["Authorization"] = f"Bearer {_nk}"
        sys.stderr.write(f"  [start] 키2로 시작: {_act[1][0]}\n")

# 분당 조직 한도(240/분) 대비 자기 디바운스: 초당 최대 3콜 = 분당 180
_LAST_CALL = [0.0]
def throttle():
    while True:
        now = time.time()
        dt = now - _LAST_CALL[0]
        if dt >= 0.34:  # ~3콜/초 = 180/분 < 240
            _LAST_CALL[0] = now
            return
        time.sleep(0.05)

def post(state, questions):
    """분당 한도 디바운스 + 429 시 키 전환 + 대기."""
    rot = getattr(CLIENT, "_jev_rotator", None)
    for attempt in range(12):
        throttle()
        try:
            resp = CLIENT.post(_API, json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=25)
            if resp.status_code == 429:
                sys.stderr.write(f"  [429 attempt={attempt}] 키 전환(on_429)\n")
                sys.stderr.flush()
                body = resp.text or ""
                is_daily = "daily free allowance" in body or "resets at 00:00 UTC" in body
                if is_daily and rot is not None:
                    # 일일 한도 소진 키는 정각까지 영구 제외
                    try:
                        import time as _t
                        rot.exhausted_until[rot.last_key] = _t.monotonic() + 3600
                        sys.stderr.write(f"  [daily-quota] 키 제외: {str(rot.last_key)[:8]}...\n")
                    except Exception:
                        pass
                if rot is not None and hasattr(rot, "on_429"):
                    try:
                        nk = rot.on_429()  # 현재 키를 끝으로 밀고 다른 키 반환
                    except Exception:
                        nk = None
                    if nk:
                        CLIENT.headers["Authorization"] = f"Bearer {nk}"
                time.sleep(2.0)
                continue
            if resp.status_code == 503:
                time.sleep(3.0)
                continue
            return resp
        except Exception:
            time.sleep(2.0)
    return None

def fmt_labels(rows, q):
    return [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows[:60]]

def run_base(rows, q):
    labels = fmt_labels(rows, q)
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows)
    qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200: return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    abstain = (idx is None) or (idx == len(jl)-1) or (ap > 0.3)
    return idx, abstain, None

def run_pool20(rows, q):
    rows20 = rows[:20]
    labels = fmt_labels(rows20, q)
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows20)
    qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200: return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    abstain = (idx is None) or (idx == len(jl)-1) or (ap > 0.3)
    return idx, abstain, None

def run_dual(rows, q):
    """abstain 라벨 2개: cN-1='주제 유사 무답', cN='전체 무관'. abstain = 둘 중 하나 선택, 또는 각 확률 합>0.3"""
    labels = fmt_labels(rows, q)
    jl = labels + [ABSTAIN_TOPIC, ABSTAIN_NONE]
    st = j1p.build_state(q, rows)
    qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200: return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    n = len(jl)
    ap_topic = float(probs.get(f"c{n-2}", 0.0) or 0.0)
    ap_none = float(probs.get(f"c{n-1}", 0.0) or 0.0)
    ap = ap_topic + ap_none
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    abstain = (idx in (n-2, n-1)) or (ap > 0.3)
    return idx, abstain, None

def run_two_call(rows, q):
    """1콜 choice(60) → winner에 noul 1콜"""
    labels = fmt_labels(rows, q)
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows)
    qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200: return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    if idx is None or idx >= len(labels) or ap > 0.3:
        return idx, True, None  # 이미 abstain
    # 2콜: winner noul
    winner_label = labels[idx]
    qs2 = {"w": {"type": "noul", "instructions": {
        "question": "Does this candidate memory directly state or entail the answer to the question? Output a 0-1 score.",
        "candidate": winner_label}}}
    resp2 = post(st, qs2)
    if resp2 is None or resp2.status_code != 200:
        return idx, False, f"http2{getattr(resp2,'status_code',None)}"
    noul = (resp2.json().get("answers") or {}).get("w") or {}
    nv = float(noul.get("noul", 0.0) or 0.0)
    return idx, (nv < 0.5), None

# ---- 벤치 구성 ----
v49c = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
input49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
qtext = {d["idx"]: d["query"] for d in input49c}
live = m48.load_queries(None)

def cls_of(idx):
    orig = next(d["verdict"] for d in input49c if d["idx"] == idx)
    v = v49c[str(idx)]
    if orig == "no":
        return "block" if v in ("IRREL", "PLAUS") else "valid"
    return "protect"

bench = []
for i, q in enumerate(live, 1):
    bench.append({"src": "live", "idx": i, "q": q, "cls": cls_of(i)})
# op 20 / noans 20 샘플
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"][::4][:20]
no = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))[::2][:20]
for q, g in op:
    bench.append({"src": "op", "idx": None, "q": q, "cls": "op"})
for n in no:
    bench.append({"src": "noans", "idx": None, "q": n["query"], "cls": "noans"})

print(f"벤치 {len(bench)}건 (live 60 / op 20 / noans 20)", flush=True)
pools = {}
for k, b in enumerate(bench):
    pools[k] = build_pool(b["q"], 60)
print("pool 구성 완료", flush=True)

RUNNERS = {"base": run_base, "pool20": run_pool20, "dual": run_dual, "two_call": run_two_call}
all_res = {name: [] for name in RUNNERS}
for k, b in enumerate(bench):
    for name, fn in RUNNERS.items():
        idx, abst, err = fn(pools[k], b["q"])
        all_res[name].append({"idx": b["idx"], "src": b["src"], "cls": b["cls"], "abstain": abst, "err": err})
    if (k+1) % 20 == 0:
        print(f"{k+1}/{len(bench)}", flush=True)

# 요약
for name, res in all_res.items():
    errs = sum(1 for r in res if r["err"])
    live_r = [r for r in res if r["src"] == "live"]
    blk = sum(1 for r in live_r if r["cls"] == "block" and r["abstain"])
    prot = sum(1 for r in live_r if r["cls"] == "protect" and r["abstain"])
    noans_fp = sum(1 for r in res if r["src"] == "noans" and not r["abstain"])
    print(f"{name:10}: IRREL차단 {blk}/17 | 정답희생 {prot}/{sum(1 for r in live_r if r['cls']=='protect')} | noans FP {noans_fp}/20 | err {errs}", flush=True)

json.dump(all_res, open(os.path.join(DATA, "stage53_missed3.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage53_missed3.json")