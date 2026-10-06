# -*- coding: utf-8 -*-
"""stage51: v2(형태 기반 식별자) 필터 — 현행 조건(live 60, choice-only, win-300) 0콜 재검증
(A·B AI 공통 요구: stage45/48 현행 조건에서 v2 재계산 + 분모 보고)

v2 규칙 (B AI·A AI 명세):
  쿼리에 [a-zA-Z0-9_]*_[a-zA-Z0-9_]+ 또는 [a-zA-Z]+\.[a-zA-Z]+ 형태 식별자 존재 시,
  JEV choice winner 원문에 해당 토큰이 0개면 abstain 강제 (또는 C AI: top-5 support)

데이터: stage50 raw (choice_idx + pool_ids 보유) — pick = pool_ids[choice_idx]
판정:
  1) winner-only: winner 텍스트에 식별자 없으면 abstain
  2) top5-any (C AI): top-5 중 아무데나 식별자 있으면 pass
  3) winner-only AND top5-none (C AI)
분모 보고 (B AI): 식별자 포함 라이브 쿼리 수 = 발동 쿼리 수
"""
import os, sys, json, re, sqlite3

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006.db")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row

d50 = json.load(open(os.path.join(DATA, "stage50_noul_answerability.json"), encoding="utf-8"))
v49c = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
input49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))

# 시트 쿼리 텍스트 (idx → query)
qtext = {d["idx"]: d["query"] for d in input49c}

# 클래스: live 60
def cls_of(idx):
    orig = next(d["verdict"] for d in input49c if d["idx"] == idx)
    v = v49c[str(idx)]
    if orig == "no":
        return "block" if v in ("IRREL", "PLAUS") else "valid"
    return "protect"  # yes / maybe

def content_of(rid):
    r = s.execute("SELECT content FROM working_memory WHERE id=?", (rid,)).fetchone()
    if r: return r["content"] or ""
    r = s.execute("SELECT content FROM episodic_memory WHERE id=?", (rid,)).fetchone()
    return (r["content"] or "") if r else ""

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+_[a-zA-Z0-9_]+|[a-zA-Z]+\.[a-zA-Z]+")

def v2_tokens(q):
    return set(TOKEN_RE.findall(q))

live = [r for r in d50["results"] if r["src"] == "live" and not r["err"]]

def evaluate(policy, name):
    """policy: (query, pool_ids, choice_idx, token) → True면 차단(abstain 강제)"""
    triggered = blocked = err_ok = 0
    detail = []
    for r in live:
        idx = int(r["qid"].split("_")[1])
        q = qtext[idx]
        toks = v2_tokens(q)
        if not toks:
            continue
        triggered += 1
        ci = r["choice_idx"]
        pool_ids = r["pool_ids"]
        winner_id = pool_ids[ci] if ci is not None and isinstance(ci, int) and ci < len(pool_ids) else None
        if not winner_id:
            continue
        winner_txt = content_of(winner_id)
        top5_txt = " ".join(content_of(pid) for pid in pool_ids[:5] if pid)
        # C: winner-only
        winner_has = any(t in winner_txt for t in toks)
        top5_has = any(t in top5_txt for t in toks)
        if policy == "winner_only":
            block = not winner_has
        elif policy == "top5_any":
            block = not top5_has
        elif policy == "winner_and_top5none":
            block = (not winner_has) and (not top5_has)
        if block:
            blocked += 1
            detail.append({"idx": idx, "cls": cls_of(idx), "toks": list(toks),
                           "winner_has": winner_has, "top5_has": top5_has})
    return triggered, blocked, detail

print("=== v2 필터 — 현행 조건(live 60) 0콜 재검증 ===")
print(f"발동 가능(식별자 포함) 쿼리: ... (각 정책별)")
by_cls = {"block": 0, "valid": 0, "protect": 0}
for r in live:
    idx = int(r["qid"].split("_")[1])
    if v2_tokens(qtext[idx]):
        by_cls[cls_of(idx)] += 1
print(f"식별자 포함 쿼리 분포: {by_cls}  ← B AI의 '분모'")

for pol, name in [("winner_only", "winner-only"), ("top5_any", "top5-any"), ("winner_and_top5none", "winner-only ∧ top5-none")]:
    trig, block, detail = evaluate(pol, name)
    # 클래스별 차단
    bc = {"block": 0, "valid": 0, "protect": 0}
    for x in detail:
        bc[cls_of(x["idx"])] += 1
    print(f"\n[{name}] 발동 {trig}건 → 차단 {block}건 | IRREL/PLAUS(block) {bc['block']} · VALID(valid) {bc['valid']} · 답있음(protect) {bc['protect']}")
    for x in detail:
        if cls_of(x["idx"]) == "protect":
            print(f"    ⚠️ 오차단: #{x['idx']} {qtext[x['idx']][:45]} toks={x['toks']}")
        elif cls_of(x["idx"]) == "block":
            print(f"    ✅ 구제:  #{x['idx']} {qtext[x['idx']][:45]} toks={x['toks']}")