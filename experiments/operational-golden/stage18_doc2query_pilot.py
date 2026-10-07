import json, os, sys, time, sqlite3, urllib.request, urllib.error, winreg, math
import numpy as np
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")
os.environ["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/bekko-a8m"

import sqlite_vec
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"

from keyring import SmartRotator
rot = SmartRotator()
print("키 상태:", rot.stats(), flush=True)

URL = "http://localhost:20128/v1/chat/completions"
MODEL = "deepcombo"

def post(url, body, key, timeout=120):
    """9router OpenAI-compatible chat completion (로컬 무료)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
                # stream 혼합 대응: 첫 '}' 뒤 'data:' 잘라내기
                idx = raw.find("data: [")
                if idx != -1:
                    raw = raw[:idx].rstrip()
                # 혹시 JSON 아닌 텍스트 앞에 붙은 경우 (첫 { 기준)
                b = raw.find("{")
                if b != -1:
                    raw = raw[b:]
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            return e.code, {"__msg": str(e)}
        except Exception:
            time.sleep(2)
    return -1, {"__msg": "timeout"}

# Doc2Query: 쿼리 → '정답 메모리가 가질 법한 문장' 재표현 (9router, 1콜)
DOC2Q_SYS = (
    "You rewrite user questions into the exact style of a memory entry / log line "
    "that would contain the answer. Output ONLY the rewritten sentence, no prefix, no quotes. "
    "Keep technical terms (camelAI, TTFT, config.toml, TimeoutExpired, 18080, Exa, etc.) intact. "
    "Korean questions -> Korean statement; English terms preserved."
)

def doc2query(key, query):
    body = {
        "model": "deepcombo",
        "messages": [
            {"role": "system", "content": DOC2Q_SYS},
            {"role": "user", "content": "Rewrite: " + query},
        ],
        "max_tokens": 120,
        "temperature": 0.2,
    }
    status, resp = post("http://localhost:20128/v1/chat/completions", body, key)
    if status != 200:
        return None, f"http-{status}"
    try:
        if isinstance(resp, dict) and "choices" in resp:
            txt = resp["choices"][0]["message"]["content"].strip()
        else:
            txt = str(resp)
    except Exception as e:
        return None, f"parse: {e}"
    txt = txt.strip("\"'` ")
    return txt, None

def get_gold_vec(conn, gid):
    r = conn.execute("SELECT embedding_json FROM memory_embeddings WHERE memory_id=?", (gid,)).fetchone()
    if not r or not r["embedding_json"]:
        return None
    return np.array(json.loads(r["embedding_json"]), dtype=np.float32)

def cos(a, b):
    a = a / np.linalg.norm(a); b = b / np.linalg.norm(b)
    return float(np.dot(a, b))

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    from mnemosyne.core import embeddings as emb_mod

    DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
    rows = json.load(open(os.path.join(DATA, "stage16_poolout_23_gold_content.json"), encoding="utf-8"))

    out = []
    for i, r in enumerate(rows, 1):
        q = r["query"]; gid = r["gold_id"]
        rec = {"query": q, "gold_id": gid, "cat": r["cat"]}

        # 원래 쿼리 cosine
        gv = get_gold_vec(conn, gid)
        if gv is not None:
            qemb0 = emb_mod.embed([q])[0]
            rec["orig_cos"] = round(cos(qemb0, gv), 4)
        else:
            rec["orig_cos"] = None

        # Doc2Query 재표현
        key = rot.next()
        rw, err = doc2query(key, q)
        rec["rewrite"] = rw
        rec["rewrite_err"] = err
        if err:
            out.append(rec); continue

        # 재표현 문장으로 vec 검색
        rwemb = emb_mod.embed([rw])[0]
        rec["rw_cos"] = round(cos(rwemb, gv), 4) if gv is not None else None
        # top-40 검색에서 gold rank
        emb_arr = rwemb / np.linalg.norm(rwemb)
        emb_json = json.dumps(emb_arr.tolist())
        try:
            top = conn.execute("""
                SELECT wm.id, vw.distance FROM vec_working vw
                JOIN working_memory wm ON wm.rowid = vw.rowid
                WHERE wm.superseded_by IS NULL AND (wm.valid_until IS NULL OR wm.valid_until > ?)
                  AND vw.embedding MATCH vec_quantize_int8(?, "unit")
                  AND k=200 ORDER BY vw.distance
            """, (time.strftime("%Y-%m-%dT%H:%M:%S"), emb_json)).fetchall()
            found = next((j+1 for j, x in enumerate(top) if x["id"] == gid), None)
            rec["rw_rank"] = found
            rec["rw_in40"] = found is not None and found <= 40
        except Exception as e:
            rec["rw_rank"] = None
            rec["rw_err2"] = str(e)[:100]

        out.append(rec)
        print(f"[{i}/23] {q[:35]} | orig_cos={rec.get('orig_cos')} rw_cos={rec.get('rw_cos')} rw_rank={rec.get('rw_rank')} in40={rec.get('rw_in40')}", flush=True)
        print(f"   rewrite: {rw[:100] if rw else None}", flush=True)

    json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "n": len(out), "records": out},
              open(os.path.join(DATA, "stage18_doc2query_pilot_9router.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장:", os.path.join(DATA, "stage18_doc2query_pilot_9router.json"))
    conn.close()

if __name__ == "__main__":
    main()