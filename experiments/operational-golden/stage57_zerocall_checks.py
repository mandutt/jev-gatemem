# -*- coding: utf-8 -*-
"""stage57: 0콜 검증 5종 (2026-10-06, 3-AI v3 후속)

B AI 0콜 점검 + C AI v2 정책 재계산 + B 문형 분리:
1. rank-veto 시뮬: base FP pick의 pool rank 분포, "pick rank>20 → abstain" 정책 구제량
2. hit@k 노출: k=1·2·3·5별 hit@k + FP 시 노출 행 수
3. 허브 행 집중도: IRREL pick id가 소수 행에 몰리는지
4. v2 세 정책 재계산 (winner-only / top5-any / winner-absent & top5-absent) — current 라벨 raw 기준
5. 문형 분리: 질문형 vs 지시문형 u·FP 비율
전부 0콜 — stage56/48/49d raw 재분석.
"""
import os, json, re, collections, sqlite3

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006.db")

# ---------- 1. rank-veto 시뮬 ----------
print("="*70)
print("1. rank-veto 시뮬 (base FP pick의 pool rank 분포)")
s56 = json.load(open(os.path.join(DATA, "stage56_full_compare.json"), encoding="utf-8"))
base_no = [r["records"] for r in s56["noans"] if r["cond"] == "base"]
# base FP 쿼리 = abstain 0/3인 noans
fp_q = [k for k in range(len(base_no[0])) if all(not r[k]["abstain"] for r in base_no)]
print(f"base noans FP (3-run 전부 pick): {len(fp_q)}건")

# pool rank 분포: stage54 base raw의 gold_rank_pool은 op만. noans는 pool rank 별도 필요 → 49d input으로 대체
# stage49d_poolinscan_input.json: noans 21건 cands (rank 6~60)
d49 = json.load(open(os.path.join(DATA, "stage49d_poolinscan_input.json"), encoding="utf-8"))
print(f"49d pool-in-scan 입력: {len(d49)}건 (noans형)")
# cands의 rank 분포 (1~5는 없음 — pool 상위는 별도)
all_ranks = []
for row in d49:
    for cd in row.get("cands", []):
        all_ranks.append(cd["rank"])
print(f"  cands rank 분포: {collections.Counter(all_ranks)}")

# rank-veto 시뮬: "pick rank>20이면 abstain" — base FP 중 pick rank>20인 건 구제
# (stage56 base raw에는 pick의 pool rank가 없음 — gold_after만. 근사: noans FP 쿼리에서
#  choice_idx가 20 이상이면 rank>20 pick으로 간주)
print("\n[rank-veto 시뮬] base raw에서 pick rank>20 (choice_idx >= 20) 구제량:")
cnt_gt20 = 0
for k in fp_q:
    idxs = [r[k]["gold_after"] for r in base_no]  # proxy — 실제로는 choice_idx 필요
print("  (stage56 raw에 choice_idx 미저장 — 0콜 한계: gold_after로는 pick rank 추정 불가)")
print("  → 정확한 rank-veto는 stage56 raw에 choice_idx 기록 필요 (다음 실행 시 저장)")

# ---------- 2. hit@k 노출 구조 ----------
print("\n" + "="*70)
print("2. hit@k 노출 구조 (k=1·2·3·5)")
# stage54 raw: gold_rank_pool + choice_idx
s54 = json.load(open(os.path.join(DATA, "stage54_op90_regress.json"), encoding="utf-8"))
base54 = s54["base"]
# choice lift 후 gold 순위 재계산 (gold_after와 동일 로직)
def gold_after_of(r):
    if r["abstain"] or r["err"] or r["gold_rank_pool"] is None:
        return None
    gp = r["gold_rank_pool"]; ci = r["choice_idx"]
    if ci is None or not isinstance(ci, int):
        return gp
    return 1 if ci == gp - 1 else (gp if gp <= ci else gp + 1)

for k in (1, 2, 3, 5):
    hit = sum(1 for r in base54 if gold_after_of(r) is not None and gold_after_of(r) <= k)
    print(f"  k={k}: hit@{k} = {hit}/90 ({hit/90:.0%})")

# op에서 노출 = top-k. FP 시 노출 행 수 = noans에서 pick 시 노출 5 — stage48로 확인
s48 = json.load(open(os.path.join(DATA, "stage48_live60_cross.json"), encoding="utf-8"))
cur = s48[0]["records"] if s48[0]["cond"] == "cur" else s48[1]["records"]
noans48 = [r for r in cur if r.get("noans_label") == "no"]  # 라벨 확인
print(f"  stage48 cur noans: {len(noans48)}건, abstain {sum(1 for r in noans48 if r['abstained'])}")

# ---------- 3. 허브 행 집중도 ----------
print("\n" + "="*70)
print("3. 허브 행 집중도 (IRREL pick id가 소수 행에 몰리는지)")
# stage49c input에서 IRREL로 라벨된 쿼리와 pick id
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
print(f"  49c input: {len(d49c)}건")
if isinstance(d49c, list) and d49c:
    print("  샘플 키:", list(d49c[0].keys()) if isinstance(d49c[0], dict) else type(d49c[0]))
    print("  샘플:", json.dumps(d49c[0], ensure_ascii=False)[:300])

# ---------- 4. v2 세 정책 재계산 (current raw) ----------
print("\n" + "="*70)
print("4. v2 세 정책 — stage56 base raw에서 재계산 (0콜)")
# stage51 결과가 이미 있으나, current 라벨·stage56 base 3-run 기준 재확인
# 49d cands에서 식별자 포함 여부로 세 정책 시뮬 (top5 기준)
ID_RE = re.compile(r"[a-zA-Z0-9_]*_[a-zA-Z0-9_]+|[a-zA-Z]+\.[a-zA-Z]+|[a-zA-Z]+[0-9]+", re.I)
for row in d49:
    q = row.get("query", "")
    toks = set(ID_RE.findall(q))
    if toks:
        # cands 전체 중 식별자 포함 여부
        has_any = any(toks & set(ID_RE.findall(cd.get("text", ""))) for cd in row.get("cands", []))
        print(f"  식별자 쿼리: {q[:40]} | toks={sorted(toks)[:3]} | cands 중 식별자 보유: {has_any}")
if not any(ID_RE.search(row.get("query", "")) for row in d49):
    print("  (49d 21건 중 식별자 쿼리 없음)")

# ---------- 5. 문형 분리 ----------
print("\n" + "="*70)
print("5. 문형 분리 (질문형 vs 지시문형) — stage48 라이브 60")
def qtype(q):
    q = q.strip()
    if q.endswith("?"): return "질문형"
    if q.endswith(("해줘", "해", "줘", "줘요", "해주세요")): return "지시문형"
    return "기타"
s48r = s48[0]["records"] if s48[0]["cond"] == "cur" else s48[1]["records"]
# noans 라벨 — stage48에 없으면 49c verdicts로
verdicts = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage49c_label_booster_verdicts.json", encoding="utf-8"))
# verdicts 키는 1-indexed... 실제 매핑 확인
print(f"  stage48 cur {len(s48r)}건, 49c verdicts {len(verdicts)}건")
# stage48 쿼리와 49c 쿼리가 같은 순서인지 확인
for i, r in enumerate(s48r[:3]):
    print(f"  s48[{i}]: {r['query'][:40]}")
print("  verdicts 키 샘플:", list(verdicts.keys())[:5])