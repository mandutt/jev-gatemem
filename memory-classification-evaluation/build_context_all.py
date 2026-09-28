"""ALL1975 컨텍스트 주입 — ko_dialog(933) + ko_sgd(622) 원본 대화에서 이전 1~2턴 추출.

- ko_dialog: id = 'dialogue_comprehension/.../test.jsonl#i#j' → 파일 i번째 대화의 j-1/j-2턴
- ko_sgd   : id = 'dialogue_id#ti' → dialogues_*.json에서 dialogue_id의 ti-1/ti-2턴
- ko_alpaca/None/synthetic: 독립 발화 — context 없음 (원본 특성)

출력: ALL1975_CTX.jsonl (id/utterance/context/gold_type/should_store)
"""
import json
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"C:\code\dataset\260928testdata")
EVAL = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")


def load_dialogues():
    """ko_dialog: {(task, i): [turns]} / ko_sgd: {dialogue_id: [turns]}"""
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
                # dialogue_comprehension 형식: {'dialogue': [{'text': ...}] or [speaker, text]}
                if isinstance(dlg, list):
                    kdb[(task, i)] = dlg
    kosgd = {}
    for f in sorted((ROOT / "kosgd" / "data" / "test").glob("dialogues_*.json")):
        for d in json.load(open(f, encoding="utf-8")):
            kosgd[d.get("dialogue_id", "?")] = d.get("turns", [])
    return kdb, kosgd


def turn_text(t):
    """대화 턴 → 텍스트. kdb 튜플/딕셔너리, kosgd dict 모두 처리."""
    if isinstance(t, (list, tuple)) and len(t) >= 2:
        return str(t[1]).strip()
    if isinstance(t, dict):
        for k in ("text", "utterance", "content"):
            if t.get(k):
                return str(t[k]).strip()
    return str(t).strip()


def prev_context(kdb, kosgd, rid: str):
    if "#" not in rid:
        return ""
    parts = rid.split("#")
    # ko_dialog: task#i#j (kdb)
    if len(parts) == 3 and parts[0].startswith(("dialogue", "response")):
        task, i, j = parts[0], int(parts[1]), int(parts[2])
        dlg = kdb.get((task, i))
        if dlg and j > 0:
            prevs = []
            for k in range(max(0, j - 2), j):
                if k < len(dlg):
                    t = turn_text(dlg[k])
                    if t:
                        prevs.append(t)
            return " | ".join(prevs)
        return ""
    # ko_sgd: dialogue_id#ti
    if len(parts) == 2:
        did, ti = parts[0], int(parts[1])
        turns = kosgd.get(did)
        if turns and ti > 0:
            prevs = []
            for k in range(max(0, ti - 2), ti):
                if k < len(turns):
                    u = turn_text(turns[k])
                    if u:
                        prevs.append(u)
            return " | ".join(prevs)
        return ""
    return ""


def main():
    kdb, kosgd = load_dialogues()
    print(f"kdb dialogues: {len(kdb)}, kosgd dialogues: {len(kosgd)}")

    rows = [json.loads(l) for l in open(EVAL / "ALL1975.jsonl", encoding="utf-8")]
    out = []
    n_ctx = 0
    no_ctx = 0
    for r in rows:
        ctx = prev_context(kdb, kosgd, r["id"])
        out.append({
            "id": r["id"],
            "dataset": r.get("dataset"),
            "utterance": r["utterance"],
            "context": ctx,
            "gold_type": r.get("gold_type"),
            "gold_should_store": r.get("should_store"),
        })
        if ctx:
            n_ctx += 1
        else:
            no_ctx += 1

    with open(EVAL / "ALL1975_CTX.jsonl", "w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"wrote ALL1975_CTX.jsonl — context 있음 {n_ctx}, 없음 {no_ctx} (총 {len(out)})")

    # 샘플 3개
    for o in out:
        if o["context"]:
            print(f"  id={o['id'][:60]}\n    utt={o['utterance'][:45]!r}\n    ctx={o['context'][:70]!r}")
            break
    for o in out:
        if not o["context"] and o["dataset"] == "ko_alpaca":
            print(f"  (no-ctx) id={o['id'][:40]} utt={o['utterance'][:40]!r}")
            break


if __name__ == "__main__":
    main()