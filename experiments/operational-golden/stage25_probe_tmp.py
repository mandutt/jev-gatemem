import json, os, sys, time, sqlite3, urllib.request, urllib.error
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")

from keyring import SmartRotator
rot = SmartRotator()

URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"
ABSTAIN_LABEL = "No candidate is usable evidence for answering the question"
CHOICE_INSTR = (
    "Which candidate memory is the single best evidence for answering the question? "
    "Pick exactly one. Consider directness and specificity. "
    "If no candidate is usable evidence for answering the question, pick the last option."
)

def post(url, body, key, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                rot.on_429(); time.sleep(1.5 * (attempt + 1)); continue
            return e.code, {"__msg": str(e)}
        except Exception:
            time.sleep(1.5)
    return -1, {"__msg": "timeout"}

def choice_call_full(key, query, labels):
    j_labels = list(labels) + [ABSTAIN_LABEL]
    body = {"model": MODEL, "state": {"question": query, "candidates": []},
            "questions": {"best": {"type": "choice", "instructions": CHOICE_INSTR,
                                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}}
    status, resp = post(URL, body, key)
    if status != 200:
        return None, f"http-{status}"
    rot.set_cost((resp.get("usage") or {}).get("cost", None))
    ans = (resp.get("answers") or {}).get("best") or {}
    return ans, None

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
noans = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))

# 1건만: 3개 라벨로 choice 호출
q = noans[0]["query"]
labels = ["웹 추출 백엔드 tavily 설정", "ddgs 검색 사용 기간", "Exa 키리스 mojibake"]
key = rot.next()
ans, err = choice_call_full(key, q, labels)
print("err:", err, flush=True)
if ans:
    print("choice:", ans.get("choice"), "conf:", ans.get("confidence"), flush=True)
    print("probs:", json.dumps(ans.get("probabilities"), ensure_ascii=False), flush=True)
print("OK", flush=True)