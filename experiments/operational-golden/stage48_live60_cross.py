"""stage48: 라이브 60쿼리 교차 검증 — cur vs improved 라벨 (2026-10-06)

용도: 사용자 판정(yes/no/maybe)과 시스템 결과(pick/abstain)의 교차표를 얻어
u_true·실제 FP율·recall 산출 + improved 라벨 효과 라이브 검증.

- 쿼리: trace에서 수집한 실사용 60건 (실험/명령형 제외)
- cond cur: current 라벨 + 300→150 (현행 운영)
- cond imp: improved 라벨 + 300→150 (stage45 후보)
- 스냅샷 DB 고정 / 60쿼리 × 2 cond = 120콜
"""
import json, os, re, sys, time, sqlite3

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
os.chdir(REPO)

from gateway import j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006.db")
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")

ABSTAIN_CURRENT = "No candidate is usable evidence for answering the question"
ABSTAIN_IMPROVED = ("No candidate contains the specific fact, value, version, or decision the "
                    "question asks for \u2014 same-topic mention alone is not evidence")
INSTR = "Choose the single candidate that best directly answers the question. If none is usable evidence, choose the final abstain option."


def load_queries(snap):
    """시트(live60_label_review.html)에 고정된 60건 반환 — trace 재수집 금지
    (2026-10-06: 실행 시점 trace에 실험 쿼리가 섞여 60건 선택이 달라지는 버그 수정)"""
    return ["auto \ub77c\uc6b0\ud305\uc774 \ud655\ub960\uc801\uc774\ub77c\ub294 \uacb0\ub860\uc774\uc5c8\ub098?", "config.yaml\uc5d0 18080 \ud504\ub85d\uc2dc \ub4f1\ub85d \ubc29\ubc95?", "custom_providers\uc5d0\uc11c Local \ud504\ub85d\uc2dc \uc5b4\ub5bb\uac8c \uc124\uc815\ud558\uc9c0?", "gemini \ubcc4\uce6d\uc73c\ub85c \ubaa8\ub378 \ud638\ucd9c\ub418\ub098?", "upstream 404 \ub728\ub294 \ubcc4\uce6d\uc774 \uc5b4\ub290 \uac83\ub4e4\uc774\uc5c8\uc9c0?", "\ud504\ub85d\uc2dc\uc5d0\uc11c \ud2b9\uc815 \ubaa8\ub378 \uac15\uc81c \uc9c0\uc815 \uae30\ub2a5 \uc788\uc5b4?", "model_override\uc640 effort \uc8fc\uc785 \uae30\ub2a5 \uc5b8\uc81c \ucd94\uac00\ub410\uc9c0?", "\ud55c\uad6d\uc5b4 \ub9d0\ud22c \uaddc\uce59 \ubb50\uc9c0?", "\ubc18\ub9d0 \uc368\ub3c4 \ub3fc?", "\uc791\uc5c5 \uc2a4\ucf00\uc904\ub7ec \ub4f1\ub85d\ud574\ub3c4 \ub3fc?", "\uc790\ub3d9 \uc2dc\uc791 \uc124\uc815 \uc5b4\ub5bb\uac8c \ud558\ub294 \uac8c \uc6d0\uce59\uc774\uc57c?", "\uc124\uacc4 \ud655\uc815 \ud6c4 \ub9ac\ud329\ud130 \uc81c\uc548\ud574\ub3c4 \ub3fc?", "ADR Final \uc774\ud6c4\uc5d0 \ubb50 \ud558\uba74 \uc548 \ub3fc?", "\uac10\uc0ac \ubcf4\uace0\uc11c\ub294 \uc5b4\ub5a4 \uc139\uc158\uc73c\ub85c \uc368?", "\ub9ac\ubdf0 \uc0b0\ucd9c\ubb3c \ud615\uc2dd \uaddc\uce59?", "\ub9ac\ubdf0 \uc804\uc6a9 \ud134\uc5d0\uc11c \ucee4\ubc0b\ud574\ub3c4 \ub3fc?", "commit governance \uaddc\uce59\uc774 \ubb50\uc9c0?", "\uc124\uacc4 \ub9ac\ubdf0\uc5d0\uc11c SOLID\ub791 \uc77c\uad00\uc131 \uc911 \ubb50 \uc6b0\uc120?", "\uc2e0\uaddc \ud0c0\uc785 \ub9cc\ub4dc\ub294 \uac8c \uc6d0\uce59\uc774\uc57c?", "evidence \uaddc\uce59 \uc5b4\ub560\uc9c0?", "\uc0ac\uc6a9\uc790 \uc5b8\uc5b4 \uc2b5\uad00\uc774 \uc5b4\ub54c?", "\ud55c\uad6d\uc5b4 \uc601\uc5b4 \uc5b4\ub5bb\uac8c \uc11e\uc5b4 \uc368?", "\uc544\ud0a4\ud14d\ucc98 \uc124\uacc4 \uc2dc \ubd84\ub9ac \uc6d0\uce59\uc774 \ubb50\uc600\uc9c0?", "DTO \ubd84\ub9ac \uc5b4\ub514\uae4c\uc9c0 \ud558\uba74 \ub3fc?", "verifier-pilot\uc740 \ucf54\ub529 \ud488\uc9c8\ub9cc \ubcf4\uba74 \ub3fc?", "\uadf8 \ud504\ub85c\uc81d\ud2b8 \uc9c4\uc9dc \ubaa9\ud45c\uac00 \ubb50\uc9c0?", "\uc2a4\ud0ac \ub9cc\ub4e4 \ub54c file_content\ub85c \ubcf4\ub0b4\uba74 \ub3fc?", "skill_manage create \ud30c\ub77c\ubbf8\ud130 \ubb50 \uc368\uc57c \ud558\uc9c0?", "opencode\uc5d0\uc11c \uba54\ubaa8\ub9ac \uc790\ub3d9 \uae30\ub85d\ub3fc?", "Mnemosyne \ud50c\ub7ec\uadf8\uc778 repo \uc8fc\uc18c \ubb50\uc57c?", "commitment FP \ud544\ud130 \uc2e4\uce21 \uacb0\uacfc \uc5b4\ub54c?", "hermes update \ud6c4 cua-driver \uc65c \uc2e4\ud328\ud574?", "660\ucd08 \ud0c0\uc784\uc544\uc6c3 \uc6d0\uc778 \ubb50\uc600\uc9c0?", "start_proxy.cmd \uc7ac\ubd80\ud305 \ud6c4 \uc65c \uc548 \ub3cc\uc544\uac00?", "\ubc30\uce58 \ud30c\uc77c \uc778\ucf54\ub529 \ubb38\uc81c\uc600\uc5b4?", "\ud504\ub85d\uc2dc \ub300\uc2dc\ubcf4\ub4dc\uc5d0 \uc885\ub8cc \ubc84\ud2bc \uc788\uc5b4?", "shutdown API \uc5b4\ub5bb\uac8c \ub9cc\ub4e4\uc5c8\uc9c0?", "Hermes \ub370\uc2a4\ud06c\ud1b1 \uc6cc\uce58\ub3c5 \ub7f0\ucc98 \uc5b4\ub514 \uc788\uc5b4?", "Hermes_With_Watchdog.cmd \uc704\uce58?", "\ub370\uc2a4\ud06c\ud1b1 \uc571 \ub744\uc6b0\uba74 \ud154\ub808\uadf8\ub7a8 \uc218\uc2e0 \ub04a\uaca8?", "orphan gateway reap \ud68c\uadc0 \ub9de\uc544?", "KoDialogBench 4\uc885 \uac80\uc99d \uacb0\uacfc \uc5b4\ub560\uc5b4?", "X1 \uc678\ubd80 \ub370\uc774\ud130\uc14b \uc2e4\ud5d8\uc5d0\uc11c bekko \uc131\ub2a5?", "best-of-5\uc5d0 recovery \uc5b9\uc73c\uba74 \uac1c\uc120\ub3fc?", "67\ucc28 \uc2e4\ud5d8 \ucd5c\uc885 \uacb0\ub860 \ubb50\uc600\uc9c0?", "codex CLI\uc5d0\uc11c \uba54\ubaa8\ub9ac \uae30\ub85d\ub418\ub098?", "codex config.toml \ud6c5 \uc5b4\ub5bb\uac8c \uc124\uc815\ud588\uc9c0?", "bekko\ub791 koen \ubca4\uce58 \ube44\uad50 \uacb0\uacfc?", "P3b \ud655\uc7a5 gold MRR \uc218\uce58?", "bekko-a8m \ucc44\ud0dd \uc774\uc720\uac00 \ubb50\uc57c?", "S3\uc5d0\uc11c \uc784\ubca0\ub529 \ubaa8\ub378 \ucd5c\uc885 \uc120\ud0dd \uadfc\uac70?", "\ucf54\ub4dc \uc124\uba85\uacfc \uad6c\uc870 \ub77c\ubca8 \uc5b8\uc5b4 \uaddc\uce59?", "\uc644\uc804 \ubc88\uc5ed \uae08\uc9c0 \uaddc\uce59 \ubb50\uc9c0?", "\ube0c\ub77c\uc6b0\uc800 \ub3c4\uad6c \ub77c\uc6b0\ud305 \uc124\uc815 \uc5b4\ub5bb\uac8c \ub3fc?", "CAMOFOX_URL \uc81c\uac70\ud55c \uc774\uc720?", "models.json\uc5d0 \uc5b4\ub5a4 \uc5d4\ub4dc\ud3ec\uc778\ud2b8 \uc788\uc9c0?", "stealth \ube0c\ub77c\uc6b0\uc800 \uc5b8\uc81c \uc368\uc57c \ud574?", "webdriver \uc228\uae40\uc774 \ud544\uc694\ud55c \uacbd\uc6b0\uac00 \ubb50\uc9c0?", "\uba54\ubaa8\ub9ac \ubc31\uc5d4\ub4dc \ubb50 \uc4f0\uace0 \uc788\uc5b4?", "hermes update \uc911\uac04\uc5d0 \uaebc\uc9c0\uba74 \uc5b4\ub5bb\uac8c \ud574?"]


def build_pool(s, query):
    def recall_raw(kind, arg, k):
        if kind == "fts":
            return beam_mod._fts_search_working(s, arg, k=k)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb):
                return []
            return beam_mod._wm_vec_search(s, qemb[0], k=k)
        if kind == "imp":
            return j1p._imp_search(s, k=k)
        if kind == "graph":
            return j1p._graph_lane_search(s, arg, k=k)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return {"id": r[0], "content": r[1], "importance": r[2]} if r else None
        return []

    pool = j1p.build_lane_pool(recall_raw, query)
    filtered = j1p._filter_and_rank(pool, query) if pool else []
    return filtered[:j1p.POOL_BUDGET]


def run_choice(client, query, rows, abstain_label):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), query, 300), 150) or "n/a" for c in rows]
    j_labels = labels + [abstain_label]
    state = j1p.build_state(query, rows)
    questions = {"best": {"type": "choice", "instructions": INSTR,
                          "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    _api = getattr(client, "_jev_api", None) or "https://api.typesafe.ai/v1/systemone"
    resp = client.post(_api, json={"state": state, "questions": questions,
                                   "model": "jev-latest"}, timeout=12.0)
    if resp.status_code != 200:
        return None, 0.0, f"http{resp.status_code}:{resp.text[:60]}"
    ans = resp.json()["answers"]["best"]
    choice = ans.get("choice")
    probs = ans.get("probabilities") or {}
    abstain_p = float(probs.get(f"c{len(j_labels)-1}", 0.0)) if probs else 0.0
    if choice is None:
        return None, abstain_p, "no-choice"
    idx = int(str(choice).lstrip("c"))
    if idx == len(j_labels) - 1 or abstain_p > 0.3:
        return None, abstain_p, None
    return idx, abstain_p, None


def main():
    client = _jev_client()
    print("client:", "OK" if client else "NONE", flush=True)
    assert client
    s = sqlite3.connect(SNAP)
    s.row_factory = sqlite3.Row
    queries = load_queries(s)
    print(f"쿼리 {len(queries)}건", flush=True)
    conds = [("cur", ABSTAIN_CURRENT), ("imp", ABSTAIN_IMPROVED)]
    all_runs = []
    for cond, abstain_label in conds:
        print(f"\n=== {cond} 시작 ===", flush=True)
        recs = []
        for qi, q in enumerate(queries, 1):
            rows = build_pool(s, q)
            if not rows:
                recs.append({"query": q, "pool_n": 0, "abstained": False, "abstain_p": 0.0, "err": "empty-pool"})
                continue
            idx, ap, err = run_choice(client, q, rows, abstain_label)
            recs.append({"query": q, "pool_n": len(rows),
                         "abstained": idx is None and err is None,
                         "abstain_p": round(ap, 3), "err": err})
            if qi % 10 == 0:
                print(f"  {qi}/{len(queries)}", flush=True)
            time.sleep(0.2)
        all_runs.append({"cond": cond, "records": recs})
        na = sum(1 for r in recs if r["abstained"])
        fp = sum(1 for r in recs if not r["abstained"] and not r["err"])
        err = sum(1 for r in recs if r["err"])
        print(f"{cond}: abstain={na}/60, pick={fp}/60, err={err}", flush=True)
    json.dump(all_runs, open(os.path.join(DATA, "stage48_live60_cross.json"), "w", encoding="utf-8"))
    print("\n저장 완료: stage48_live60_cross.json", flush=True)


if __name__ == "__main__":
    main()