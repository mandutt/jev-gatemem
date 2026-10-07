# -*- coding: utf-8 -*-
"""stage93_consumer_2x2.py — 소비 측 프레이밍 + 노출 k 2×2 QA (2026-10-07)

사안 A(노출 k) + 사안 C(소비 프레이밍) 결합 실측.
- JEV 선택: live60에 대해 choice 1회 재호출 (60콜, stage85와 동일 조건 — pool 60, 시간 필터 없음)
  → 실제 pick + top-k 행 내용 확보 (stage85 raw에는 pick id가 없어 재구성 필요)
- 소비 모델: deepcombo (9router localhost:20128, OpenAI 호환) — 실제 Hermes 메인 모델
- 조건: {k=5, k=2} × {헤더 OFF, 헤더 ON} = 4셀 (소비 모델 240콜, 로컬 무료)
- 대상: live60 전체 (block 38 + yes 17 + valid 5)
- 지표:
  - block 38: '무관한 메모리 내용을 답변 근거로 인용한 환각' 비율
  - yes/valid 22: '정답(메모리 활용) 여부'
- 판정: deepcombo LLM 판정 + 사람 감사 20%
- 한계: zeroshot (대화 이력 없음) — '그래 계속해줘'형 저정보 발화는 live60에 없음

실행: python stage93_consumer_2x2.py [--subset N]  (JEV 60콜 + deepcombo 240콜)
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

# ---- deepcombo (Hermes 메인 모델, 9router 로컬) ----
DEEPCOMBO_URL = "http://localhost:20128/v1/chat/completions"

def chat(prompt, max_tokens=300, temperature=0.2):
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
        # 9router는 JSON + data: [DONE] 꼬리 (개행 없이 바로 붙음) — data: 앞까지가 JSON
        if raw.lstrip().startswith("{"):
            d = json.loads(raw.split("data:")[0])
        else:
            # 순수 SSE: data: {...} 줄 추출
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("data:") and "[DONE]" not in line:
                    d = json.loads(line[5:].strip())
                    break
            else:
                return f"[ERR 응답 파싱 실패] {raw[:100]}"
        return d["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERR {e}]"

# ---- JEV choice 재호출 → pick + top-k 행 ----
def _load_key_from_registry():
    """HKCU\\Environment에서 JEV API 키 로드 (bash 터미널 env 부재 대비)"""
    try:
        import winreg
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

_load_key_from_registry()
CLIENT = _jev_client()
assert CLIENT, "EXPLABS_API_KEY 필요 (레지스트리에도 없음)"
_API = getattr(CLIENT, "_jev_api", None)

def run_choice_rows(q):
    """pool 60 → choice → {idx, abstain_p, rows(top5 excerpt)}"""
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
    chose_abstain = (idx == len(jl) - 1)
    rows = [{"rank": r, "content": labels[r]} for r in range(min(5, len(pool)))]
    return {"q": q, "idx": idx, "abstain_p": ap, "chose_abstain": chose_abstain, "rows": rows}

def build_prompt(q, k, framing, rows):
    picked_rows = rows[:k] if rows else []
    body = "\n".join(f"- {r['content']}" for r in picked_rows) if picked_rows else "(메모리 없음)"
    if framing:
        body = (
            "[참고용 메모리: 아래 내용은 질문과 키워드가 유사하여 검색된 결과입니다. "
            "질문에 대한 직접적이고 명확한 답이 없다면 이 메모리를 무시하고 답변하십시오.]\n" + body
        )
    return (f"<retrieved_context>\n{body}\n</retrieved_context>\n\n"
            f"질문: {q}\n위 메모리를 참고하여 답변하세요.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", type=int, default=0, help="디버그용 부분 실행 (0=전체)")
    ap.add_argument("--skip_jev", action="store_true", help="기존 stage93 raw 재사용 (JEV 재호출 생략)")
    args = ap.parse_args()

    out_path = os.path.join("experiments", "operational-golden", "data", "stage93_consumer_2x2.json")
    jev_path = os.path.join("experiments", "operational-golden", "data", "stage93_jev_rows.json")

    d85 = json.load(open(os.path.join("experiments", "operational-golden", "data", "stage85_pool20_gate.json"), encoding="utf-8"))
    recs = d85["runs"][0]["k60"]["records"]
    queries = [{"query": r["query"], "cls": r["cls"]} for r in recs]
    if args.subset:
        queries = queries[:args.subset]

    # 1) JEV choice 재호출 (60콜) — 또는 기존 결과 재사용
    if args.skip_jev and os.path.exists(jev_path):
        jev_rows = json.load(open(jev_path, encoding="utf-8"))
        print(f"JEV 결과 재사용: {len(jev_rows)}건", flush=True)
    else:
        jev_rows = []
        for i, qd in enumerate(queries):
            r = run_choice_rows(qd["query"])
            r["cls"] = qd["cls"]
            jev_rows.append(r)
            if (i + 1) % 10 == 0 or r.get("err"):
                print(f"  JEV {i+1}/{len(queries)} err={r.get('err')} idx={r.get('idx')} ap={r.get('abstain_p', 0):.2f}", flush=True)
            json.dump(jev_rows, open(jev_path, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"JEV complete: {len(jev_rows)}콜", flush=True)

    # 2) 소비 QA 2×2 (deepcombo 로컬)
    results = []
    for i, jr in enumerate(jev_rows):
        q = jr["q"]; rows = jr.get("rows") or []
        for k in (5, 2):
            for framing in (False, True):
                prompt = build_prompt(q, k, framing, rows)
                ans = chat(prompt)
                results.append({
                    "i": i, "query": q, "cls": jr.get("cls"),
                    "k": k, "framing": framing,
                    "jev_idx": jr.get("idx"), "abstain_p": jr.get("abstain_p"),
                    "response": ans,
                })
        if (i + 1) % 10 == 0:
            print(f"  소비 {i+1}/{len(jev_rows)} 완료", flush=True)
            json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)

    json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n완료: {len(results)}건 → {out_path}")

if __name__ == "__main__":
    main()