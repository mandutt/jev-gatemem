"""⑤ Shadow 모드 배치 스크립트 — 400자+게이트 파이프라인 shadow 실행 (2026-10-04)

방식: Hermes cron (10분 주기) → 본 스크립트 실행
대상: core_state.db query_log의 **신규 미처리 쿼리** (처리됨 마킹)
      + backlog이 비어 있으면 op 90 스냅샷 쿼리로 대체 (shadow 검증용)

실행:
  1. query_log에서 아직 shadow 처리 안 된 쿼리 (shadow_marked=0) 읽기
  2. 각 쿼리에 400자 choice → full-text 게이트(head600+tail200) → R2(θ=0.5) 실행
  3. shadow_log 테이블에 기록 (gate verdict, winner_score, R2 결정, 지연)
  4. 처리된 쿼리는 shadow_marked=1 마킹

중단 기준 (b AI): 정당한 주입 차단 > 해로운 차단이면 R2 폐기 — 배치 로그로 수집

비용: 쿼리당 choice 1 + gate 1 = 2콜 FREE (SmartRotator)
출력: core_state.db shadow_log 테이블
"""
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "experiments/operational-golden"))

CORE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "jev-mem", "core_state.db")
DATA = os.path.join(ROOT, "experiments/operational-golden/data")
URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
MAX_CRIT = 64
MAX_CAND = MAX_CRIT - 1
WORKERS = 2
GATE_LIMIT = 800
THETA = 0.5
BATCH_LIMIT = 20  # 1회 배치 최대 쿼리 수 (3분 cron 제한 내)

CHOICE_INSTR = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. Consider directness and specificity. "
    "If no candidate is usable evidence for answering the question, pick the last option."
)
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"
GATE_PROMPT = (
    "Does this memory directly state or entail the answer to the question? "
    "Answer YES if it contains the specific fact/value/rule the question asks for. "
    "Answer NO if it only shares the topic, related keywords, or background."
)

from keyring import SmartRotator
rot = SmartRotator()
print(f"[shadow] 키: {rot.stats()}", flush=True)


def post(url, body, key, timeout=180.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    for attempt in range(6):
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                nk = rot.on_429()
                if nk:
                    key = nk
                    continue
                ra = e.headers.get("Retry-After")
                try:
                    wait = float(ra) if ra else 30.0
                except ValueError:
                    wait = 30.0
                print(f"    429 → {wait:.0f}s (attempt {attempt+1}/6)", flush=True)
                time.sleep(wait)
                continue
            return e.code, {"__msg": e.read().decode()[:200]}
        except Exception as e:
            if attempt == 5:
                return -1, {"__msg": f"{type(e).__name__}"}
            time.sleep(1.5)
    return 429, {"__msg": "rate limited"}


def choice_call(key, query, cands, excerpt_len=400):
    labels = [(c.get("content") or "")[:excerpt_len] or "n/a" for c in cands]
    j_labels = list(labels) + [ABSTAIN_LABEL]
    body = {"model": MODEL, "state": {"question": query, "candidates": []},
            "questions": {"best": {"type": "choice", "instructions": CHOICE_INSTR,
                                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}}
    t0 = time.perf_counter()
    status, resp = post(URL, body, key)
    lat = (time.perf_counter() - t0) * 1000
    if status != 200:
        return None, None, f"http-{status}", lat
    cost = (resp.get("usage") or {}).get("cost", None)
    rot.set_cost(cost)
    ans = (resp.get("answers") or {}).get("best") or {}
    ch = ans.get("choice")
    if ch is None:
        return None, cost, "no-choice", lat
    i = int(str(ch).lstrip("c"))
    if i == len(labels):
        return -1, cost, None, lat
    if not (0 <= i < len(labels)):
        return None, cost, "bad-idx", lat
    return i, cost, None, lat


def gate_call(key, query, cand_text, cand_id):
    body = {
        "model": MODEL,
        "state": {"question": query, "candidate": cand_text, "candidate_id": cand_id},
        "questions": {
            "entails": {
                "type": "choice",
                "instructions": GATE_PROMPT,
                "criteria": {"c0": "YES", "c1": "NO"},
            }
        },
    }
    t0 = time.perf_counter()
    status, resp = post(URL, body, key)
    lat = (time.perf_counter() - t0) * 1000
    if status != 200:
        return None, None, f"http-{status}", lat
    cost = (resp.get("usage") or {}).get("cost", None)
    rot.set_cost(cost)
    ans = (resp.get("answers") or {}).get("entails") or {}
    ch = ans.get("choice")
    if ch is None:
        return None, cost, "no-choice", lat
    i = int(str(ch).lstrip("c"))
    if i == 0:
        return "YES", cost, None, lat
    if i == 1:
        return "NO", cost, None, lat
    return None, cost, f"bad-idx-{i}", lat


def cap_window(text, limit=GATE_LIMIT):
    if len(text) <= limit:
        return text
    return text[:600] + "\n...[중략]...\n" + text[-200:]


def get_beam_refs():
    LIVE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
    os.environ.setdefault("MNEMOSYNE_DB", LIVE_DB)
    sys.path.insert(0, ROOT)
    import gateway.j1_pipeline as j1p
    import mnemosyne.core.beam as bm
    from mnemosyne.core import embeddings as emb_mod
    b = bm.BeamMemory(session_id="shadow")

    def recall_raw(kind, arg, k_):
        if kind == "fts":
            return bm._fts_search_working(b.conn, arg, k=k_)
        if kind == "vec":
            e = emb_mod.embed([arg])
            if e is None or not len(e):
                return []
            return bm._wm_vec_search(b.conn, e[0], k=k_)
        if kind == "imp":
            return j1p._imp_search(b.conn, k=k_)
        if kind == "graph":
            return j1p._graph_lane_search(b.conn, arg, k=k_)
        if kind == "get":
            from core import j1_engine
            row = j1_engine.hydration_get(b, arg)
            return row if isinstance(row, dict) else None
        return []
    return recall_raw, j1p, b


def stage1_pool(query, k=40):
    recall_raw, j1p, b = get_beam_refs()
    pool = j1p.build_lane_pool(recall_raw, query)
    ranked = j1p._filter_and_rank(pool, query) if pool else []
    return ranked[:k]


def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS shadow_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT, agent TEXT, session_id TEXT, source TEXT,
        winner_id TEXT, gate_verdict TEXT, winner_score REAL,
        r2_decision TEXT, abstained INTEGER, err TEXT,
        lat_ms REAL, cost REAL, created_at TEXT
    )""")
    conn.commit()


def main():
    conn = sqlite3.connect(CORE_DB)
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)

    # 1) 미처리 쿼리 확인 (shadow_marked 컬럼 없으면 추가)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(query_log)").fetchall()]
    if "shadow_marked" not in cols:
        conn.execute("ALTER TABLE query_log ADD COLUMN shadow_marked INTEGER DEFAULT 0")
        conn.commit()
    rows = conn.execute(
        "SELECT * FROM query_log WHERE shadow_marked = 0 ORDER BY id LIMIT ?",
        (BATCH_LIMIT,)).fetchall()

    if not rows:
        # backlog 없음 — op 90 스냅샷 쿼리로 shadow 검증 대체
        op = json.load(open(os.path.join(DATA, "golden_eval_v2.json"), encoding="utf-8"))
        op_eval = [x for x in op if x.get("gold_id") and x.get("cat") != "NO_ANSWER"]
        # 이미 처리된 쿼리 제외
        done = {r["query"] for r in conn.execute("SELECT query FROM shadow_log WHERE source='op-snapshot'").fetchall()}
        pending = [x for x in op_eval if x["query"] not in done][:BATCH_LIMIT]
        print(f"[shadow] query_log 비어있음 → op 스냅샷 {len(pending)}건 shadow 실행", flush=True)
        for x in pending:
            rows.append({
                "query": x["query"], "agent": "op-snapshot",
                "session_id": x.get("gold_id"), "source": "op-snapshot"
            })
    else:
        print(f"[shadow] query_log 미처리 {len(rows)}건", flush=True)
        for r in rows:
            r = dict(r)
            r["source"] = "query_log"
        rows = [dict(r) for r in rows]

    # 2) 각 쿼리 shadow 실행
    for x in rows:
        q = x["query"]
        try:
            pool = stage1_pool(q, k=40)
        except Exception as e:
            print(f"  pool 실패: {e}", flush=True)
            continue
        if not pool:
            continue
        cands = pool[:MAX_CAND]

        key = rot.next()
        idx, cost, err, lat_c = choice_call(key, q, cands, 400)
        rec = {"agent": x.get("agent", ""), "session_id": x.get("session_id", ""),
               "source": x.get("source", "?"), "cost": cost, "err": err}
        if err:
            rec.update({"gate_verdict": None, "winner_score": None, "r2_decision": f"choice-err-{err}", "abstained": 1})
        elif idx == -1:
            rec.update({"gate_verdict": "ABSTAIN", "winner_score": None, "r2_decision": "A-abstain", "abstained": 1})
        else:
            wid = cands[idx].get("id")
            full = cands[idx].get("content") or ""
            # winner score는 별도 pointwise 없이 게이트만 (비용 절감) — score는 추후 실측 보강
            gv, gcost, gerr, lat_g = gate_call(key, q, cap_window(full), wid)
            # R2: gate YES → inject / gate NO & score>=θ → inject (score 미측정 시 gate NO → abstain)
            if gv == "YES":
                r2 = "inject"
                abst = 0
            elif gerr:
                r2 = f"gate-err-{gerr}"
                abst = 0  # fail-open: 기존 A 유지
            else:
                r2 = "abstain(gate-NO)"
                abst = 1
            rec.update({
                "winner_id": wid, "gate_verdict": gv, "winner_score": None,
                "r2_decision": r2, "abstained": abst,
                "lat_ms": round(lat_c + lat_g, 1) if lat_g else round(lat_c, 1),
            })
        rec["query"] = q
        rec["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        conn.execute("""INSERT INTO shadow_log
            (query, agent, session_id, source, winner_id, gate_verdict,
             winner_score, r2_decision, abstained, err, lat_ms, cost, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec["query"], rec["agent"], rec["session_id"], rec["source"],
             rec.get("winner_id"), rec.get("gate_verdict"), rec.get("winner_score"),
             rec.get("r2_decision"), rec.get("abstained"), rec.get("err"),
             rec.get("lat_ms"), rec.get("cost"), rec["created_at"]))
        print(f"  {q[:40]}... → gate={rec.get('gate_verdict')} R2={rec.get('r2_decision')}", flush=True)

    # query_log 마킹
    if rows and rows[0].get("source") == "query_log":
        for r in rows:
            conn.execute("UPDATE query_log SET shadow_marked=1 WHERE id=?", (r["id"],))
    conn.commit()

    # 요약
    n = conn.execute("SELECT COUNT(*) FROM shadow_log").fetchone()[0]
    by_gate = conn.execute("SELECT gate_verdict, COUNT(*) FROM shadow_log GROUP BY gate_verdict").fetchall()
    print(f"[shadow] shadow_log 총 {n}건:", flush=True)
    for g, c in by_gate:
        print(f"  {g}: {c}건", flush=True)
    conn.close()


if __name__ == "__main__":
    main()