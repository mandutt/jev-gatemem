"""Stage A: dataset discovery — scan the 3 local datasets and emit DATASET_INFO.md.

Read-only.  Summarizes structure, record counts, fields, utterance sources.
"""
import json
import sys
import io
from pathlib import Path
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"C:\code\dataset\260928testdata")
OUT = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")


def scan_kodialogbench():
    base = ROOT / "kodialogbench"
    files = sorted(base.rglob("*.jsonl"))
    rows = []
    for f in files:
        n = sum(1 for _ in open(f, encoding="utf-8"))
        rows.append((str(f.relative_to(base)), n))
    # sample one record per file to find fields
    fields = {}
    for f in files:
        with open(f, encoding="utf-8") as fh:
            rec = json.loads(fh.readline())
        # strip huge dialogues
        keys = list(rec.keys())
        dlg = rec.get("dialogue")
        fields[str(f.relative_to(base))] = {
            "keys": keys,
            "n_dialogues": len(dlg) if isinstance(dlg, list) else None,
            "sample_utts": [t[1] for t in (dlg[:2] if isinstance(dlg, list) else [])],
        }
    return rows, fields


def scan_kosgd():
    base = ROOT / "kosgd"
    files = sorted((base / "data" / "test").glob("dialogues_*.json"))
    schema = base / "extended_schema.json"
    n_dialogues = 0
    turns = 0
    spk = Counter()
    acts = Counter()
    services = Counter()
    utt_len = []
    for f in files:
        dlist = json.load(open(f, encoding="utf-8"))
        n_dialogues += len(dlist)
        for d in dlist:
            for t in d.get("turns", []):
                turns += 1
                spk[t.get("speaker", "?")] += 1
                u = t.get("utterance", "")
                utt_len.append(len(u))
                for fr in t.get("frames", []):
                    acts[fr.get("act", "?")] += 1
            for s in d.get("services", []):
                services[s] += 1
    schema_info = None
    if schema.exists():
        s = json.load(open(schema, encoding="utf-8"))
        schema_info = {"keys": list(s.keys()) if isinstance(s, dict) else type(s).__name__}
    return {
        "files": len(files),
        "n_dialogues": n_dialogues,
        "turns": turns,
        "speakers": dict(spk),
        "top_acts": acts.most_common(12),
        "top_services": services.most_common(10),
        "utt_len_min_max": (min(utt_len), max(utt_len)),
        "schema": schema_info,
    }


def scan_koalpaca():
    base = ROOT / "koalpaca"
    out = {}
    for name in ["ko_alpaca_data.json", "KoAlpaca_v1.1.jsonl", "alpaca_data.json", "seed_tasks.jsonl"]:
        f = base / name
        if not f.exists():
            out[name] = "MISSING"
            continue
        ext = f.suffix
        if ext == ".json":
            data = json.load(open(f, encoding="utf-8"))
            out[name] = {
                "records": len(data),
                "keys": list(data[0].keys()),
                "sample": {k: str(v)[:60] for k, v in data[0].items()},
                "instr_len_avg": round(sum(len(d.get("instruction", "")) for d in data[:500]) / 500),
            }
        else:  # jsonl
            rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
            out[name] = {
                "records": len(rows),
                "keys": list(rows[0].keys()),
                "sample": {k: str(v)[:60] for k, v in rows[0].items()},
            }
    return out


def main():
    kdb_rows, kdb_fields = scan_kodialogbench()
    kosgd = scan_kosgd()
    koalpaca = scan_koalpaca()

    lines = []
    lines.append("# DATASET_INFO.md")
    lines.append("")
    lines.append("Stage A 결과 — 로컬 3개 데이터셋 구조 스캔 (2026-09-28, read-only)")
    lines.append("")
    lines.append("## KoDialogBench (seongbo/kodialogbench)")
    lines.append("")
    lines.append("- local: `C:/code/dataset/260928testdata/kodialogbench/` (31M)")
    lines.append("- format: JSONL, HF snapshot (test split 만 존재 — 21개 테스트셋 중 13개 파일)")
    lines.append("- 전체 예시 수: `82,962` (README 기준), 로컬 파일 수:")
    for rel, n in kdb_rows:
        lines.append(f"  - `{rel}` — {n} records")
    lines.append("- 공통 필드: dialogue(화자/발화 쌍 목록), option_description, label 계열")
    lines.append("- 발화 추출: dialogue 내 2번째 요소 (utterance), 원문 라벨은 task별 상이 (topic/emotion/act/fact 등)")
    lines.append("")
    lines.append("## KoSGD (AIWORKX/KoSGD)")
    lines.append("")
    for k, v in kosgd.items():
        if k == "schema":
            lines.append(f"- schema: {v}")
        elif k == "top_acts":
            lines.append(f"- top acts: {v}")
        elif k == "top_services":
            lines.append(f"- top services: {v}")
        else:
            lines.append(f"- {k}: {v}")
    lines.append("- 발화 추출: turns[].utterance, speaker USER/SYSTEM, frames[].act 원본 라벨")
    lines.append("")
    lines.append("## KoAlpaca (Beomi/KoAlpaca)")
    lines.append("")
    for name, v in koalpaca.items():
        if isinstance(v, dict):
            lines.append(f"- `{name}`: {v}")
        else:
            lines.append(f"- `{name}`: {v}")
    lines.append("")
    lines.append("## Sampling notes")
    lines.append("")
    lines.append("- KoDialogBench: 13개 파일 전부를 균등 샘플링 (파일당 N), dialogue의 모든 발화에서 추출")
    lines.append("- KoSGD: USER 턴 우선 (목적 지향 요청), SYSTE팀 과도 포함 방지를 위해 USER 80% / SYSTEM 20%")
    lines.append("- KoAlpaca: instruction 필드만 (output은 정답이므로 제외), 중복 instruction 제거")
    lines.append("- deduplication: KoDialogBench/KoSGD는 대화 ID로, KoAlpaca는 instruction 텍스트 해시로 중복 제거")
    lines.append("- 원본 파일은 수정하지 않음. 추출물만 evaluation 디렉터리에 저장.")

    (OUT / "DATASET_INFO.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:60]))
    print(f"\n... written to {OUT / 'DATASET_INFO.md'}")


if __name__ == "__main__":
    main()