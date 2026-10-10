# -*- coding: utf-8 -*-
"""jev-canary: 일일 모델/파이프라인 drift 감지 (2026-10-07)

2계층 설계:
- L1 (사용자 독립, 12콜): 범용 일반지식 쿼리 — JEV 모델/API 상태 감시
  (abstain율·abstain_p·latency·결정성 — 어떤 사용자 DB에서든 동일 기대)
- L2 (사용자 의존, 20콜): 내 라벨 쿼리 (무답 10 + 정답 10) — 파이프라인 회귀 감시
  (pick 분포·규칙 행 노출 — stage83/87/92 기준선 재사용)

실행: python canary_run.py [--init | --check]
- --init: 기준선 수집 (첫 실행 — canary_baseline.json 저장)
- --check: 기준선 대비 drift 판정 + 이상 시 텔레그램 (hermes send)

⚠️ cron 등록은 사용자 승인 후. 이 스크립트 자체는 수동 실행.
"""
import os, sys, json, time, sqlite3, subprocess, argparse

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client

DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
BASELINE = os.path.join(DATA, "canary_baseline.json")
LOG = os.path.join(DATA, "canary_log.jsonl")

# ---- L1: 범용 쿼리 (사용자 독립) ----
L1_QUERIES = [
    "한국의 수도는 어디야?",            # 사실 — 답 있음
    "물의 화학식은?",                  # 사실 — 답 있음
    "지구에서 가장 가까운 별은?",       # 사실 — 답 있음
    "1+1은?",                        # 사실 — 답 있음
    "대한민국의 공용어는?",            # 사실 — 답 있음
    "어제 날씨가 어땠어?",             # 무답 (에이전트가 모름) — abstain 기대
    "내일 복권 당첨 번호 알려줘",       # 무답 — abstain 기대
    "지금 내 위치에서 맛집 추천해줘",    # 무답 (위치 없음) — abstain 기대
    "이 컴퓨터의 비밀번호는?",          # 무답 (그런 메모리 없음) — abstain 기대
    "지난주 금요일 내가 뭘 했는지 말해줘", # 무답 (시점 부재) — abstain 기대
    "설명할 수 없는 것을 설명해줘",      # 무답 (모호) — abstain 기대
    "우주의 끝은 어디야?",             # 사실 (답 있음 — 개념) — pick 기대
]

# ---- L2: 내 라벨 쿼리 (무답 10 + 정답 10, stage83/87/92 기준선 재사용) ----
L2_NOANS = [
    "리뷰 전용 턴에서 커밋해도 돼?",
    "구현됐다는 말 믿기 전에 뭘 확인해?",
    "provider가 뭐지?",
    "전환 전 어떤 문제 있었지?",
    "auto 라우팅이 확률적이라는 결론이었나?",
    "config.yaml에 18080 프록시 등록 방법?",
    "custom_providers에서 Local 프록시 어떻게 설정하지?",
    "gemini 별칭으로 모델 호출되는 거야?",
    "자동 시작 설정 어떻게 하는 게 원칙이야?",
    "DTO 분리 어디까지 하면 돼?",
]

L2_YES = [
    "camelAI auto 라우팅에서 어려운 과제는 어떤 모델로 보내졌어?",
    "92번 호출 실험에서 라우팅 결과 어땠지?",
    "라우팅 플립 트리거 패딩 토큰 가설 맞았어?",
    "모델 최종 선택 근거?",
    "koen이랑 bekko 벤치 비교 결과?",
    "S3에서 임베딩 모델 최종 선택 근거?",
    "브라우저 도구 라우팅 설정 어떻게 돼?",
    "camelai-serial-proxy 기능 정리해줘",
    "deepseek 장문 스트림에서 뭐가 문제였어?",
    "pi 에이전트에 등록된 프록시 목록?",
]

ABSTAIN_CUR = m48.ABSTAIN_CURRENT
INSTR = m48.INSTR

def build_pool_prodex(q):
    s = sqlite3.connect(m48.SNAP); s.row_factory = sqlite3.Row
    def recall_raw_factory(qry):
        def recall_raw(kind, arg, kk):
            from mnemosyne.core import beam as beam_mod
            from mnemosyne.core import embeddings as emb_mod
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
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    s.close()
    return j1p._filter_and_rank(pool, q)[:60]

CLIENT = _jev_client(); assert CLIENT
_API = getattr(CLIENT, "_jev_api", None)

def run_choice(q):
    pool = build_pool_prodex(q)
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in pool]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, pool)
    qs = {"best": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    # ★ 2026-10-10 b-ai D-3: timeout/503은 1회 재시도 (canary는 매일 1회라 부담 0)
    for attempt in range(2):
        t0 = time.time()
        try:
            resp = CLIENT.post(_API, json={"state": st, "questions": qs,
                                           "model": "jev-latest"}, timeout=5)
        except Exception as e:
            lat = (time.time() - t0) * 1000
            if attempt == 0:
                time.sleep(2)
                continue
            return {"q": q, "err": f"exc:{type(e).__name__}", "latency_ms": lat}
        lat = (time.time() - t0) * 1000
        if resp.status_code == 200:
            break
        if attempt == 0 and resp.status_code in (503, 502, 504, 408):
            time.sleep(2)
            continue
        return {"q": q, "err": f"http{resp.status_code}", "latency_ms": lat}
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    chose_abstain = (idx == len(jl) - 1)
    abstain = chose_abstain or (ap > 0.3)
    return {"q": q, "abstain": abstain, "chose_abstain": chose_abstain,
            "abstain_p": ap, "choice_idx": idx, "latency_ms": lat}

def summarize(recs, prefix):
    n = len(recs)
    abst = sum(1 for r in recs if r.get("abstain"))
    chose = sum(1 for r in recs if r.get("chose_abstain"))
    aps = sorted(r.get("abstain_p", 0) for r in recs if r.get("abstain_p") is not None)
    ap_med = aps[len(aps)//2] if aps else 0
    ap_gt03 = sum(1 for r in recs if (r.get("abstain_p") or 0) > 0.3)
    picks = [r.get("choice_idx") for r in recs if r.get("choice_idx") is not None]
    lats = [r.get("latency_ms", 0) for r in recs if r.get("latency_ms", 0) > 0]
    lat_med = sorted(lats)[len(lats)//2] if lats else 0
    errs = sum(1 for r in recs if r.get("err"))
    return {"prefix": prefix, "n": n, "abstain": abst, "chose_abstain": chose,
            "abstain_p_med": ap_med, "abstain_p_gt03": ap_gt03,
            "pick_med": sorted(picks)[len(picks)//2] if picks else None,
            "latency_med_ms": lat_med, "errs": errs}

def check_daemon_health():
    """데몬 /v1/health probe — 실패 시 알림(게이트웨이와 독립 채널) 후 종료.
    2026-10-10 v8 3-AI(G·D) 대응: canary는 JEV 직결이라 데몬 부재를 못 봄."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:47821/v1/health", timeout=5) as r:
            ok = r.status == 200 and b"ready" in r.read()
        if ok:
            print("[health] 데몬 OK", flush=True)
            return True
        print("[health] 데몬 응답 비정상", flush=True)
    except Exception as e:
        print(f"[health] 데몬 연결 실패: {e}", flush=True)
    try:
        subprocess.run(["hermes", "send", "-t", "telegram", "-m",
                        "⚠️ JEV 데몬 health 실패 — 47821 응답 없음. 로그 확인 필요"],
                       capture_output=True, timeout=60)
    except Exception:
        pass
    return False


SCHEMA_VERSION = 2  # ★ 2026-10-10 b-ai D-2: baseline 스키마 버전 (abstain_p_gt03 추가로 1→2)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="기준선 수집 (첫 실행)")
    ap.add_argument("--check", action="store_true", help="drift 판정")
    args = ap.parse_args()

    print("canary 실행:", "INIT" if args.init else "CHECK", flush=True)

    if not check_daemon_health():
        print("⚠️ 데몬 비정상 — canary 중단 (알림 전송됨)", flush=True)
        return

    # L1
    l1 = [run_choice(q) for q in L1_QUERIES]
    # L2 (무답 10 + 정답 10 = 20)
    l2n = [run_choice(q) for q in L2_NOANS]
    l2y = [run_choice(q) for q in L2_YES]
    l2 = l2n + l2y
    print(f"L1 {len(l1)}콜, L2 {len(l2)}콜 완료", flush=True)

    s_l1 = summarize(l1, "L1")
    s_l2n = summarize(l2n, "L2_NOANS")
    s_l2y = summarize(l2y, "L2_YES")

    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "schema_version": SCHEMA_VERSION,
             "l1": s_l1, "l2_noans": s_l2n, "l2_yes": s_l2y}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps(entry, ensure_ascii=False, indent=2))

    if args.init:
        json.dump(entry, open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"\n기준선 저장: {BASELINE}")
        return

    if not os.path.exists(BASELINE):
        print("\n⚠️ 기준선 없음 — --init 먼저 실행")
        return

    base = json.load(open(BASELINE, encoding="utf-8"))
    # ★ b-ai D-2: baseline 스키마 버전 불일치 시 비교 중단 (조용한 0→N 경고 방지)
    b_sv = base.get("schema_version")
    if b_sv is not None and b_sv != SCHEMA_VERSION:
        print(f"⚠️ baseline schema_version {b_sv} ≠ {SCHEMA_VERSION} — 비교 생략, --init으로 재생성 필요")
        return
    alerts = []
    # L1 abstain율 drift (±20pp → 2콜 플립)
    b_a = base["l1"]["abstain"]; c_a = s_l1["abstain"]
    if abs(c_a - b_a) >= 2:  # 12개 중 2개 = ~17pp
        alerts.append(f"L1 abstain율: {b_a}/12 → {c_a}/12")
    # L1 abstain_p drift (±0.1)
    b_p = base["l1"]["abstain_p_med"]; c_p = s_l1["abstain_p_med"]
    if abs(c_p - b_p) >= 0.1:
        alerts.append(f"L1 abstain_p 중앙: {b_p} → {c_p}")
    # L2 noans abstain율 drift (무답 감시)
    b_n = base["l2_noans"]["abstain"]; c_n = s_l2n["abstain"]
    if abs(c_n - b_n) >= 2:  # 10개 중 2개
        alerts.append(f"L2 무답 abstain율: {b_n}/10 → {c_n}/10")
    # ★ L2_YES 감시 — 정답 10개 중 1개라도 abstain이면 즉시 (과다거부 센서, c-ai 지적)
    b_y = base["l2_yes"]["abstain"]; c_y = s_l2y["abstain"]
    if c_y > b_y:
        alerts.append(f"L2 정답 abstain: {b_y}/10 → {c_y}/10 (과다거부 위험)")
    # ★ abstain_p > 0.3 발생 수 감시 (τ 게이트 발동 근접, 사안 F)
    b_g = base["l1"].get("abstain_p_gt03", 0); c_g = s_l1["abstain_p_gt03"]
    if c_g > b_g:
        alerts.append(f"L1 abstain_p>0.3: {b_g} → {c_g}건")
    # pick 중앙 drift (choice_idx — 모델 선택 경향 변화)
    b_pk = base["l1"].get("pick_med"); c_pk = s_l1["pick_med"]
    if b_pk is not None and c_pk is not None and abs(c_pk - b_pk) >= 5:
        alerts.append(f"L1 pick 중앙: {b_pk} → {c_pk}")
    # L1 latency drift (2배)
    b_l = base["l1"]["latency_med_ms"]; c_l = s_l1["latency_med_ms"]
    if b_l > 0 and c_l > 2 * b_l:
        alerts.append(f"L1 latency 중앙: {b_l:.0f}ms → {c_l:.0f}ms")
    # 오류
    if s_l1["errs"] > 0:
        alerts.append(f"L1 오류 {s_l1['errs']}건")

    if alerts:
        msg = "⚠️ JEV canary drift 감지\n" + "\n".join(f"- {a}" for a in alerts)
        print("\n" + msg)
        # 텔레그램 전송 (Hermes CLI)
        try:
            r = subprocess.run(["hermes", "send", "-t", "telegram", "-m", msg],
                               capture_output=True, text=True, timeout=60)
            print("텔레그램 전송:", r.returncode, r.stdout[-100:] if r.stdout else "")
        except Exception as e:
            print("텔레그램 전송 실패:", e)
    else:
        print("\n정상 — drift 없음")

if __name__ == "__main__":
    main()