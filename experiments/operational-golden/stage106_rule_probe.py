# -*- coding: utf-8 -*-
"""게이트 규칙 수정 검증 (2026-10-09) — 'OK 파일' 접근

수정안: type-rescue가 NO_STORE+event/context 류를 KEEP시키는 걸 막는다.
규칙 변경 (write_gate.G-qual):
  - store == STORE            -> KEEP (store)
  - store == NO_STORE:
      * store_conf >= 0.6:
          - type in (NO_STORE, event, context, observation) -> SKIP (신규: event/context/observation도 NO_STORE 일관 시 SKIP)
          - 그 외 (fact/instruction/...) -> KEEP (type-rescue 유지)
      * store_conf < 0.6      -> KEEP (low-conf)
  - store == None(파싱 실패)  -> KEEP (안전)

기존 규칙 대비 변경: elif store_conf >= 0.6 분기가 'type==event/context/observation'이면 SKIP (기존엔 type-rescue가 우선해 전부 KEEP).
회귀 검증: ① 9샘플 재실행(skip 기대: plain/waste), ② op-90 gold50 등 기존 라벨과의 대조는 0콜 시뮬 + ③ noans 50 대상 게이트 재판정.
"""
import sys, os, json, time, re
REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
os.chdir(REPO)
import gateway.write_gate as wg
import httpx

# ---- 수정 규칙 적용 판정 함수 (write_gate.evaluate의 규칙부만 교체) ----
def decide(store, store_conf, mtype, type_conf):
    if store == "STORE":
        return True, "store"
    if store is None:
        return True, "parse-fail"
    # NO_STORE
    if store_conf >= 0.6:
        if mtype in (None, "NO_STORE", "event", "context", "observation"):
            return False, "skip"
        return True, "type-rescue"   # fact/instruction 등 — NO_STORE 취소
    return True, "low-conf"

def get_key():
    try:
        from jev_mem_core.keyring import SmartRotator
        r = SmartRotator()
        k0 = r.keys[0]
        return k0[1] if isinstance(k0, (tuple, list)) else k0
    except Exception:
        pass
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        v, _ = winreg.QueryValueEx(k, "EXPLABS_API_KEY")
        return v or ""
    except Exception:
        return os.environ.get("EXPLABS_API_KEY", "")

KEY = get_key()

def post(utterance):
    utterance_cut = (utterance or "")[:1500]
    state = {"utterance": utterance_cut,
             "candidates": [{"id": f"t{i}", "label": t} for i, t in enumerate(wg.TYPES)]}
    questions = {
        "store": {"type": "choice", "instructions": wg.STORE_INSTRUCTIONS,
                  "criteria": {"c0": "STORE", "c1": "NO_STORE"}},
        "classify": {"type": "choice", "instructions": wg.CLASSIFY_INSTRUCTIONS,
                     "criteria": {f"c{i}": t for i, t in enumerate(wg.TYPES)}},
    }
    resp = httpx.post(wg.API_URL, json={"state": state, "questions": questions, "model": wg.MODEL},
                      timeout=60, headers={"Authorization": f"Bearer {KEY}"})
    if resp.status_code != 200:
        return {"status": resp.status_code}
    ans = resp.json().get("answers") or {}
    store_idx = None; store_conf = 0.0; type_idx = None; type_conf = 0.0
    try:
        s = ans.get("store") or {}
        store_idx = int(str(s.get("choice", "")).lstrip("c"))
        store_conf = float((s.get("probabilities") or {}).get(f"c{store_idx}", 0.0) or 0.0)
    except Exception: pass
    try:
        t = ans.get("classify") or {}
        type_idx = int(str(t.get("choice", "")).lstrip("c"))
        type_conf = float((t.get("probabilities") or {}).get(f"c{type_idx}", 0.0) or 0.0)
    except Exception: pass
    store = "STORE" if store_idx == 0 else ("NO_STORE" if store_idx == 1 else None)
    mtype = wg.TYPES[type_idx] if type_idx is not None and 0 <= type_idx < len(wg.TYPES) else None
    keep, reason = decide(store, store_conf, mtype, type_conf)
    return {"status": 200, "keep": keep, "store": store, "store_conf": round(store_conf,3),
            "type": mtype, "type_conf": round(type_conf,3), "reason": reason}

# ---- ① 9샘플 재검증 ----
sel = json.load(open(os.path.join(REPO, "experiments/operational-golden/data/stage105_imp_sample.json"), encoding="utf-8"))
print("=== ① 9샘플 — 신규 규칙 판정 ===")
results = []
for label in ["plain_no_out", "plain_with_out", "fail", "watch", "batch"]:
    for i, u in enumerate(sel.get(label, [])):
        r = post(u)
        results.append({"label": label, "i": i, **r})
        print(f"  [{label}#{i}] keep={r.get('keep')} ({r.get('store')}/{r.get('type')} conf {r.get('store_conf')}) reason={r.get('reason')}")
        time.sleep(0.4)
json.dump(results, open(os.path.join(REPO, "experiments/operational-golden/data/stage106_rule_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---- ② 기존 라벨 샘플 회귀 (일반 발화 — 규칙이 오탐하지 않는지) ----
print("\n=== ② 일반 발화 회귀 (라벨: KEEP 기대 4 · SKIP 기대 4) ===")
reg = [
    ("내일까지 보고서 제출해야 해", True),          # commitment KEEP
    ("오류가 발생했어, 빌드가 실패했어", True),      # error KEEP
    ("앞으로 답변은 항상 표로 정리해줘", True),      # instruction KEEP
    ("config.yaml은 여기 있어", True),              # artifact KEEP
    ("좋아 진행해줘", False),                        # filler SKIP
    ("알겠습니다", False),                           # acknowledgment SKIP
    ("감사합니다", False),                           # filler SKIP
    ("네 그럼요", False),                            # filler SKIP
]
for u, expect in reg:
    r = post(u)
    ok = "✓" if r.get("keep") == expect else "✗ MISMATCH"
    print(f"  {ok} keep={r.get('keep')} ({r.get('store')}/{r.get('type')} conf {r.get('store_conf')}) reason={r.get('reason')} | {u[:30]}")
    time.sleep(0.4)

print("\n완료 — stage106_rule_raw.json 저장")