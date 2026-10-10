# -*- coding: utf-8 -*-
"""stage101_consumer_rerun.py — 소비 2×2 재실행 (b-ai v7 설계, 2026-10-07)

stage93/94 무효화(stage100: JEV lift 미적용)에 따른 재실행.
b-ai 설계를 그대로 구현:
- 운영 format_block 출력 재현 (원문, 운영 헤더)
- 노출 = [pick] + pool[:k-1] (JEV lift 적용 — 운영과 동일)
- 조건: k ∈ {2, 3, 5} × {운영 헤더, 새 헤더} + 메모리 없음 기준선
- 셀당 3샘플 (temperature 0.2/0.5/0.8)
- 소비 모델: deepcombo (실제 Hermes 메인 모델)
- 대상: live60 (block 38 + yes/valid 22)
- JEV: 60콜 재호출 (full pool + pick + abstain 저장)

실행: venv python stage101_consumer_rerun.py
"""
import os, sys, json, time, argparse, sqlite3

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import urllib.request
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client
from canary_run import build_pool_prodex, ABSTAIN_CUR, INSTR
from core import j1_engine

# ---- deepcombo (Hermes 메인 모델, 9router 로컬) ----
DEEPCOMBO_URL = "http://localhost:20128/v1/chat/completions"

def chat(prompt, temperature=0.2, max_tokens=300):
    body = {
        "model": "deepcombo",
        "messages": [
            {"role": "system", "content": "당신은 Hermes 어시스턴트입니다. 한국어로 답변합니다."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        DEEPCOMBO_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
        if raw.lstrip().startswith("{"):
            d = json.loads(raw.split("data:")[0])
        else:
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("data:") and "[DONE]" not in line:
                    d = json.loads(line[5:].strip())
                    break
            else:
                return f"[ERR 파싱] {raw[:100]}"
        return d["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERR {e}]"

# ---- JEV 재호출: full pool + pick + abstain ----
def _load_key():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
            for name in ("EXPLABS_API_KEY", "TYPESAFE_API_KEY"):
                try:
                    v, _ = winreg.QueryValueEx(k, name)
                    if v and not os.environ.get(name):
                        os.environ[name] = v
                except OSError:
                    pass
    except Exception:
        pass

_load_key()
CLIENT = _jev_client()
assert CLIENT, "EXPLABS_API_KEY 필요"
_API = getattr(CLIENT, "_jev_api", None)

def run_choice_full(q):
    """pool 60 → choice → {pick_id, abstain_p, ranked[f"{pick} + pool[:k-1]"]}"""
    pool = build_pool_prodex(q)
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in pool]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, pool)
    qs = {"best": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = CLIENT.post(_API, json={"state": st, "questions": qs, "model": "jev-latest"}, timeout=25)
    if resp.status_code != 200:
        return {"q": q, "err": f"http{resp.status_code}"}
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    try:
        idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception:
        idx = None
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    # pick id (idx < len(pool)면 pick, 아니면 abstain)
    pick_id = None
    if idx is not None and 0 <= idx < len(pool):
        pick_id = pool[idx].get("id")
    # 운영 노출 순서: [pick] + pool[:k-1] (pick 제외)
    ordered = []
    if pick_id:
        ordered.append(pool[idx])
    for c in pool[:4]:
        if c.get("id") != pick_id:
            ordered.append(c)
    while len(ordered) < 5 and len(ordered) < len(pool):
        ordered.append(pool[len(ordered)])  # fallback (실제로는 5개면 충분)
    return {"q": q, "idx": idx, "pick_id": pick_id, "abstain_p": ap,
            "chose_abstain": (idx == len(jl) - 1), "ordered": ordered[:5]}

def render_block(rows, q):
    """운영 format_block 렌더 — 원문 전체"""
    return j1_engine.format_block(rows, q)

NEW_HEADER = "[참고용 메모리: 아래 내용은 질문과 키워드가 유사하여 검색된 결과입니다. 질문에 대한 직접적이고 명확한 답이 없다면 이 메모리를 무시하고 답변하십시오.]"

def build_prompt(q, rows, framing, memoryless=False, history=""):
    """운영 헤더 기준선: OFF=현행(헤더 없음+참고 지시 없음), ON=새 헤더."""
    if memoryless:
        body = "(메모리 없음)"
    else:
        block = render_block(rows, q)
        if framing:
            body = NEW_HEADER + "\n" + block
        else:
            body = block
    return f"{history}<retrieved_context>\n{body}\n</retrieved_context>\n\n질문: {q}\n위 메모리를 참고하여 답변하세요."

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", type=int, default=0)
    args = ap.parse_args()

    out_dir = os.path.join("experiments", "operational-golden", "data")
    os.makedirs(out_dir, exist_ok=True)
    JEV_OUT = os.path.join(out_dir, "stage101_jev_full.json")
    QA_OUT = os.path.join(out_dir, "stage101_consumer.json")

    d85 = json.load(open(os.path.join("experiments", "operational-golden", "data", "stage85_pool20_gate.json"), encoding="utf-8"))
    recs = d85["runs"][0]["k60"]["records"]
    queries = [{"query": r["query"], "cls": r["cls"]} for r in recs]
    if args.subset:
        queries = queries[:args.subset]

    # 1) JEV 재호출 (full pool + pick)
    jev_out = []
    for i, qd in enumerate(queries):
        r = run_choice_full(qd["query"])
        r["cls"] = qd["cls"]
        jev_out.append(r)
        if (i + 1) % 10 == 0 or r.get("err"):
            print(f"  JEV {i+1}/{len(queries)} err={r.get('err')} idx={r.get('idx')} pick={str(r.get('pick_id'))[:10]} ap={r.get('abstain_p', 0):.2f}", flush=True)
        json.dump(jev_out, open(JEV_OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"JEV complete: {len(jev_out)}콜", flush=True)

    # 2) 소비 QA: k∈{2,3,5} × framing∈{OFF,ON} × 3샘플 + memoryless 기준선
    results = []
    temps = [0.2, 0.5, 0.8]
    for i, jr in enumerate(jev_out):
        q = jr["q"]
        ordered = jr.get("ordered") or []
        for k in (2, 3, 5):
            rows_k = ordered[:k]
            for framing in (False, True):
                for ti, temp in enumerate(temps):
                    prompt = build_prompt(q, rows_k, framing)
                    ans = chat(prompt, temperature=temp)
                    results.append({
                        "i": i, "query": q, "cls": jr.get("cls"),
                        "k": k, "framing": framing, "sample": ti, "temp": temp,
                        "pick_id": jr.get("pick_id"), "abstain_p": jr.get("abstain_p"),
                        "response": ans,
                    })
        # memoryless 기준선 1샘플
        prompt = build_prompt(q, [], False, memoryless=True)
        ans = chat(prompt, temperature=0.2)
        results.append({"i": i, "query": q, "cls": jr.get("cls"),
                        "k": 0, "framing": None, "sample": 0, "temp": 0.2,
                        "pick_id": None, "abstain_p": None, "response": ans})
        if (i + 1) % 5 == 0:
            print(f"  소비 {i+1}/{len(jev_out)} ({len(results)}건)", flush=True)
            json.dump(results, open(QA_OUT, "w", encoding="utf-8"), ensure_ascii=False)

    json.dump(results, open(QA_OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n완료: {len(results)}건 → {QA_OUT}")

if __name__ == "__main__":
    main()