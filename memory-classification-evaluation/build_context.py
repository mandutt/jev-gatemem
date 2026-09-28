"""P3 작업4용 문맥 복구: id 경로에서 원본 대화의 이전 1~2턴 추출.

- kdb  : {task}#{i}#{j} -> 파일 task의 i번째 대화, j-1/j-2턴
- kosgd: {dialogue_id}#{ti} -> dialogues_*.json에서 dialogue_id 찾아 ti-1/ti-2턴
- koalpaca: 문맥 없음 (독립 instruction)

출력: P3_RETEST_CTX.jsonl (id/utterance/context/gold_type, context = 이전 발화들)
"""
import json
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"C:\code\dataset\260928testdata")
EVAL = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")


def load_dialogues():
    """kdb: {task: {i: [turns]}} / kosgd: {dialogue_id: [turns]}"""
    kdb = {}
    for f in sorted((ROOT / "kodialogbench").rglob("*.jsonl")):
        task = str(f.relative_to(ROOT / "kodialogbench")).replace("\\", "/")
        with open(f, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                dlg = r.get("dialogue")
                if isinstance(dlg, list):
                    kdb[(task, i)] = dlg
    kosgd = {}
    for f in sorted((ROOT / "kosgd" / "data" / "test").glob("dialogues_*.json")):
        for d in json.load(open(f, encoding="utf-8")):
            kosgd[d.get("dialogue_id", "?")] = d.get("turns", [])
    return kdb, kosgd


def prev_context(kdb, kosgd, rid: str):
    """id -> (대화 이전 1~2턴 텍스트)"""
    if "#" not in rid:
        return ""
    parts = rid.split("#")
    # kdb: task#i#j
    if len(parts) == 3 and parts[0].startswith(("dialogue", "response")):
        task, i, j = parts[0], int(parts[1]), int(parts[2])
        dlg = kdb.get((task, i))
        if dlg and j > 0:
            prevs = []
            for k in range(max(0, j - 2), j):
                if k < len(dlg):
                    t = dlg[k]
                    if isinstance(t, (list, tuple)) and len(t) >= 2:
                        prevs.append(str(t[1]).strip())
            return " | ".join(p for p in prevs if p)
        return ""
    # kosgd: dialogue_id#ti
    if len(parts) == 2:
        did, ti = parts[0], int(parts[1])
        turns = kosgd.get(did)
        if turns and ti > 0:
            prevs = []
            for k in range(max(0, ti - 2), ti):
                if k < len(turns):
                    u = (turns[k].get("utterance") or "").strip()
                    if u:
                        prevs.append(u)
            return " | ".join(prevs)
        return ""
    return ""


def main():
    kdb, kosgd = load_dialogues()
    print(f"kdb dialogues: {len(kdb)}, kosgd dialogues: {len(kosgd)}")

    rows = [json.loads(l) for l in open(EVAL / "P3_RETEST.jsonl", encoding="utf-8")]
    with open(EVAL / "P3_RETEST_CTX.jsonl", "w", encoding="utf-8") as f:
        n_ctx = 0
        for r in rows:
            ctx = prev_context(kdb, kosgd, r["id"])
            r["context"] = ctx
            if ctx:
                n_ctx += 1
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote P3_RETEST_CTX.jsonl — context 있는 {n_ctx}/{len(rows)}")

    # 샘플 3개 출력
    for r in rows[:3]:
        print(f"  {r['id'][:60]}")
        print(f"    utt: {r['utterance'][:50]!r}")
        print(f"    ctx: {prev_context(kdb, kosgd, r['id'])[:80]!r}")


if __name__ == "__main__":
    main()