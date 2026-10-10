# -*- coding: utf-8 -*-
"""stage110_embed_probe.py — ingest 병목 분리 프로브 (2026-10-10)

목적: 왜 4워커 전체 실행에서 ingest가 125~150s로 늘었나 (스모크 단독 24.6s)?
가설:
  H1: fastembed 모델 로드가 워커마다 1회 (수십 초) — 첫 문항만 느림?
  H2: remember() 1턴마다 임베딩 1회 — CPU에서 550턴 × 임베딩 = ?
  H3: 4워커 동시 = CPU 12코어 중 임베딩이 4개 경합 → 선형 스케일링

측정:
  - 단독 프로세스로 문항 1건 ingest 시간 분해: 총 시간 / 임베딩 호출 수 / sqlite 시간
  - mnemosyne 내부 embed 호출을 패치해서 카운트 + 시간
"""
import os, sys, json, time, tempfile
REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"

# --- 임베딩 호출 패치 (mnemosyne.core.embeddings.embed) ---
import mnemosyne.core.embeddings as emb_mod
_orig_embed = emb_mod.embed
_stats = {"calls": 0, "total_s": 0.0, "total_chars": 0}

def _patched_embed(texts, *a, **kw):
    t0 = time.time()
    r = _orig_embed(texts, *a, **kw)
    dt = time.time() - t0
    if isinstance(texts, str):
        n = 1
        ch = len(texts)
    else:
        n = len(texts)
        ch = sum(len(t) for t in texts)
    _stats["calls"] += n
    _stats["total_s"] += dt
    _stats["total_chars"] += ch
    return r

emb_mod.embed = _patched_embed

from mnemosyne import Mnemosyne
print("device 확인: fastembed onnxruntime threads?")

# --- 문항 1건: 첫 remember (모델 로드 포함) vs 이후 ---
x = json.load(open(DATA, encoding="utf-8"))[0]
tmp = tempfile.mkdtemp(prefix="lmev_probe_")
db = os.path.join(tmp, "probe.db")
mem = Mnemosyne(session_id="probe", db_path=db)

sess0 = x["haystack_sessions"][0]
t0 = time.time()
n0 = 0
for turn in sess0:
    c = turn.get("content", "")
    if c:
        mem.remember(f"{turn.get('role','user')}: {c}", source="conversation", importance=0.5, extract=False)
        n0 += 1
t_first = time.time() - t0
print(f"[1] 첫 세션 {n0}턴: {t_first:.1f}s (모델 로드 포함)  embed_calls={_stats['calls']} embed_s={_stats['total_s']:.1f}")

t00 = time.time(); c0 = _stats["calls"]; s0 = _stats["total_s"]
# 이후 100턴
rest_turns = []
for sess in x["haystack_sessions"][1:]:
    for turn in sess:
        c = turn.get("content", "")
        if c:
            rest_turns.append((turn.get("role","user"), c))
t1 = time.time()
for role, c in rest_turns[:100]:
    mem.remember(f"{role}: {c}", source="conversation", importance=0.5, extract=False)
t_mid = time.time() - t1
c_mid = _stats["calls"] - c0
s_mid = _stats["total_s"] - s0
print(f"[2] 다음 100턴: {t_mid:.1f}s  embed_calls={c_mid} embed_s={s_mid:.1f} → 임베딩 비율 {s_mid/max(t_mid,1e-9)*100:.0f}%")

print(f"[3] 총 임베딩 상태: calls={_stats['calls']} total_s={_stats['total_s']:.1f} chars={_stats['total_chars']}")
print(f"[4] 4워커 추정: 550턴 × (임베딩 s/턴) × 경합계수")

# 참고: 실제 4워커에서 125s였던 것과 비교
print("probe 완료")