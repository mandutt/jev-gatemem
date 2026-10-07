"""q8 vs q4f16 드리프트 + op-90 품질 비교 (동일 세션, 같은 스냅샷).
1) 30개 대표 문장의 벡터 cosine 드리프트 (q4f16 vs q8)
2) op-90 전체를 q8로 재실행 (q4f16 결과는 op90_result.json에서 재사용)
Usage: python q8_bench.py
"""
import os, sys, json, sqlite3
import numpy as np

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")
REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden"

sys.path.insert(0, B)
from embgemma2_runner import EmbGemma2Runner

r4 = EmbGemma2Runner(os.path.join(B, "model-src"), model_file="model_q4f16.onnx")
r8 = EmbGemma2Runner(os.path.join(B, "model-src"), model_file="model_quantized.onnx")

# 1) 드리프트: 대표 문장 30개 (한국어 운영 도메인 + 다국어)
PROBES = [
    "게이트웨이 텔레그램 수신 문제 해결", "임베딩 모델 교체 실험 설계", "Hermes 프로필 백업 및 복구 절차",
    "SQLite WAL 모드 동시 쓰기 직렬화", "벤치마크 사전 등록 게이트 기준", "비밀번호 볼트 origin 바인딩 검증",
    "윈도우 프로세스 커밋 메모리 실측", "세션 로그 아카이브 정리 방법", "플러그인 자체 완결성 원칙",
    "재임베딩 배치 크기 OOM 분석", "The quick brown fox jumps over the lazy dog.",
    "仕事中に集中力を高めるには？", "如何提高工作时的专注力？", "¿Cómo mejorar la concentración?",
    "Comment améliorer la concentration au travail ?", "Wie verbessere ich die Konzentration?",
] + ["기술과학 문서 기계독해에서 정답 문단을 찾는 방법", "외래해충 방제를 위한 천연살충제 개발 실험"] * 7

v4 = np.array(r4.embed(PROBES, batch_size=4), dtype=np.float32)
v8 = np.array(r8.embed(PROBES, batch_size=4), dtype=np.float32)
v4n = v4 / np.linalg.norm(v4, axis=1, keepdims=True)
v8n = v8 / np.linalg.norm(v8, axis=1, keepdims=True)
cos = (v4n * v8n).sum(axis=1)
print("드리프트 cos (q4f16 vs q8): mean=%.5f min=%.5f max=%.5f" % (cos.mean(), cos.min(), cos.max()), flush=True)

# 2) op-90 q8 실행
DB = os.path.join(B93, "data", "mnemosyne.db")
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = conn.execute(
    "SELECT id, content FROM working_memory WHERE content IS NOT NULL AND length(content) > 0 ORDER BY id"
).fetchall()
conn.close()
id_text = {r[0]: r[1] for r in rows}
all_ids = [r[0] for r in rows]
texts = [r[1] for r in rows]
id_pos = {mid: i for i, mid in enumerate(all_ids)}
print("corpus:", len(texts), flush=True)

raw = json.load(open(os.path.join(REPO, "data", "stage54_op90_regress.json"), encoding="utf-8"))
items = [(r["q"], r["gold"]) for r in raw["base"]]
items = [(q, g) for q, g in items if g in id_pos]
print("valid op-90 items:", len(items), flush=True)

dvecs = np.array(r8.embed(texts, batch_size=4, doc=True), dtype=np.float32)
dn = dvecs / (np.linalg.norm(dvecs, axis=1, keepdims=True) + 1e-12)
per = []
for q, g in items:
    qv = np.array(r8.embed([q], batch_size=1)[0], dtype=np.float32)
    qn = qv / (np.linalg.norm(qv) + 1e-12)
    s = dn @ qn
    rank = int(np.where(np.argsort(-s) == id_pos[g])[0][0]) + 1
    per.append({"rank": rank, "rr": 1.0 / rank})

agg = {
    "hit@1": float(np.mean([1 if p["rank"] <= 1 else 0 for p in per])),
    "hit@5": float(np.mean([1 if p["rank"] <= 5 else 0 for p in per])),
    "hit@10": float(np.mean([1 if p["rank"] <= 10 else 0 for p in per])),
    "MRR": float(np.mean([p["rr"] for p in per])),
}
print("gemma2-q8 op-90:", json.dumps(agg, ensure_ascii=False), flush=True)

# q4f16 기존 결과 (동일 DB/쿼리)
old = json.load(open(os.path.join(B, "op90_result.json"), encoding="utf-8"))
old_agg = {k: v for k, v in old.items() if k in ("hit@1", "hit@5", "hit@10", "MRR")}
print("gemma2-q4f16 op-90 (기존):", json.dumps(old_agg, ensure_ascii=False), flush=True)

# rank별 flip 개수
old_per = [old["per_query"][str(i)] for i in range(len(per))]
flips = [i for i, (p8, p4) in enumerate(zip(per, old_per))
         if (p8["rank"] <= 1) != (p4["gemma2"] <= 1)]
print("q8 vs q4f16 rank-1 flips:", len(flips), flips[:20], flush=True)

out = {
    "drift_cos": {"mean": float(cos.mean()), "min": float(cos.min()), "max": float(cos.max())},
    "q8_op90": agg,
    "q4f16_op90": old_agg,
    "rank1_flips": flips,
    "per_query": [{"q8": p["rank"], "q4f16": old_per[i]["gemma2"]} for i, p in enumerate(per)],
}
with open(os.path.join(B, "q8_bench_result.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print("Q8 DONE")