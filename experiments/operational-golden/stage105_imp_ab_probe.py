# -*- coding: utf-8 -*-
"""[IMPORTANT:] 자동 발화 — 지시문 보강 A/B 검증 (2026-10-09, JEV 콜 9건)

baseline(STORE_INSTRUCTIONS as-is) vs 신규(+system-generated 알림 규칙 1문장) — 
같은 utterance를 각각 판정. 정보 가치 있는 유형(fail)은 KEEP 유지,
단순 완료(plain_no_out)는 NO_STORE로 flip되는지 확인. 데몬 venv python으로 실행.
"""
import sys, os, json, time
REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
os.chdir(REPO)
import gateway.write_gate as wg
import httpx

ADD = ("\nSystem-generated background-process notifications ([IMPORTANT:], [ASYNC]) are "
       "NO_STORE if they merely report completion/progress/exit-0 without reusable "
       "content; STORE only if they carry durable information worth recalling later "
       "(failure cause, concrete numbers, findings, decisions).")
NEW_STORE = wg.STORE_INSTRUCTIONS + ADD

sel = json.load(open(os.path.join(REPO, "experiments/operational-golden/data/stage105_imp_sample.json"), encoding="utf-8"))

def get_key():
    import winreg
    try:
        from jev_mem_core.keyring import SmartRotator
        r = SmartRotator()
        k0 = r.keys[0]
        return k0[1] if isinstance(k0, (tuple, list)) else k0
    except Exception:
        pass
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        v, _ = winreg.QueryValueEx(k, "EXPLABS_API_KEY")
        return v or os.environ.get("EXPLABS_API_KEY", "")
    except Exception:
        return os.environ.get("EXPLABS_API_KEY", "")

class Client:
    def __init__(self):
        self.headers = {"Authorization": f"Bearer {get_key()}"}

def post_with(client, store_inst, utterance):
    utterance_cut = (utterance or "")[:1500]
    state = {"utterance": utterance_cut,
             "candidates": [{"id": f"t{i}", "label": t} for i, t in enumerate(wg.TYPES)]}
    questions = {
        "store": {"type": "choice", "instructions": store_inst,
                  "criteria": {"c0": "STORE", "c1": "NO_STORE"}},
        "classify": {"type": "choice", "instructions": wg.CLASSIFY_INSTRUCTIONS,
                     "criteria": {f"c{i}": t for i, t in enumerate(wg.TYPES)}},
    }
    body = {"state": state, "questions": questions, "model": wg.MODEL}
    resp = httpx.post(wg.API_URL, json=body, timeout=60, headers=client.headers)
    if resp.status_code != 200:
        return {"status": resp.status_code, "keep": None}
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
    # G-qual 실제 규칙 (write_gate.evaluate와 동일)
    if store == "STORE":
        keep, reason = True, "store"
    elif mtype not in (None, "NO_STORE"):
        keep, reason = True, "type-rescue"
    elif store_conf >= 0.6:
        keep, reason = False, "skip"
    else:
        keep, reason = True, "low-conf"
    return {"status": 200, "keep": keep, "store": store, "store_conf": round(store_conf, 3),
            "type": mtype, "type_conf": round(type_conf, 3), "reason": reason}

client = Client()
results = []
for label in ["plain_no_out", "plain_with_out", "fail", "watch", "batch"]:
    for i, u in enumerate(sel.get(label, [])):
        r0 = post_with(client, wg.STORE_INSTRUCTIONS, u)
        time.sleep(0.4)
        r1 = post_with(client, NEW_STORE, u)
        time.sleep(0.4)
        results.append({"label": label, "i": i, "baseline": r0, "with_rule": r1})
        print(f"[{label}#{i}] base: keep={r0['keep']} ({r0.get('store')}/{r0.get('type')} conf {r0.get('store_conf')}) "
              f"-> rule: keep={r1['keep']} ({r1.get('store')}/{r1.get('type')} conf {r1.get('store_conf')})", flush=True)

json.dump(results, open(os.path.join(REPO, "experiments/operational-golden/data/stage105_imp_ab_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n저장: stage105_imp_ab_raw.json")