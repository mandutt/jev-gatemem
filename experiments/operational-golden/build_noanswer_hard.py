"""fresh noans 50건 생성 — 코퍼스 이웃 주제 (B 비판 #5 대응) (2026-10-04)

기존 noans 50건은 '일상 잡담'(점심/영화/날씨) — max_score mean 0.161로 쉬운 세트였음.
B: "실제 위험은 주제는 코퍼스와 이웃한데 답만 없는 질의(근접 오답 유도)."
→ 코퍼스에 존재하는 주제(설정/디버깅/규칙/도구/실험)와 이웃하되 실제 금지된 주제·존재하지 않는
   세부사항을 묻는 쿼리 50건. 실제 코퍼스 내용과 어휘가 겹치도록 작성 (레이블: noans-hard).

주의: 이 쿼리들은 Jev가 'gold가 존재하지 않음'을 제대로 abstain하는지 측정하는 하드 세트다.
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "experiments/operational-golden/data")

# 코퍼스 이웃 주제 쿼리 (실제 기억 내용과 어휘 겹침, 그러나 답은 없음)
# 실제 기억 주제: web_extract/tavily, bekko-a8m 임베딩, sqlite-vec, 18080 프록시, deepseek,
#   텔레그램 게이트웨이, Windows 진단, Hermes 설정, 커밋 규칙, Mnemosyne DB, RRF pool, Jev gateway
fresh = [
    # --- 설정/환경 이웃 (실제 설정은 다르게 존재) ---
    "web_extract의 백엔드로 ddgs를 쓰고 있었던 기간이 언제야?",
    "tavily API key가 환경변수에 설정된 날짜가 언제야?",
    "임베딩 모델을 bekko-a8m으로 바꾸기 전에 쓰던 모델의 정확한 버전이 뭐야?",
    "sqlite-vec 확장의 정확한 설치 경로가 어디야?",
    "Hermes config.yaml에서 browser.backend를 camofox로 설정한 적이 있어?",
    "Mnemosyne DB 파일의 WAL 모드가 꺼져 있던 시기가 언제야?",
    "텔레그램 게이트웨이의 chat_id가 1234567890이던 때가 있었어?",
    "JEV_API_URL이 experientiallabs가 아니라 다른 URL이던 적이 있어?",
    "Free tier 한도가 $0.75/hour였던 시절이 있었어?",
    "RRF pool 크기가 60이던 시점의 성능이 어땠어?",
    "exa 검색이 키리스로 작동하던 기간이 언제야?",
    "BrokenPipeError가 처음 발생한 날짜가 언제야?",
    "Windows 진단 스크립트가 ps1이 아니라 cmd로 작성되던 때가 있었어?",
    "Hermes v0.19.x 시절 browser.backend 설정값이 뭐였어?",
    "pip install uv를 처음 실행한 날짜가 언제야?",

    # --- 디버깅/원인 이웃 (실제 원인과 다른 가상 원인) ---
    "임베딩 OOM이 GPU 메모리 부족 때문에 발생했던 적이 있어?",
    "camelai 프록시 429가 API 키 만료 때문이었던 적이 있어?",
    "벤치마크 실패 원인이 네트워크 지연이었던 경우가 있었어?",
    "state.db 손상이 디스크 용량 부족 때문에 발생했어?",
    "텔레그램 수신 끊김이 인터넷 연결 문제 때문이던 적이 있어?",
    "deepseek 스트림 오류가 프롬프트 길이 초과 때문이었던 적 있어?",
    "임베딩 모델 교체 후 성능이 하락했던 적이 있어?",
    "skip_shadow 테이블이 처음엔 없어서 누락됐던 적이 있어?",
    "Jev 호출 타임아웃이 30초였던 시절이 있었어?",
    "Mnemosyne consolidation이 중복 메모리를 생성했던 버그가 있었어?",
    "pipeline.py에 json import가 없어서 실패했던 게 언제야?",
    "레이트 리밋 429가 hourly limit 때문이었던 적이 있어?",
    "golden 쿼리의 pool_rank가 항상 1이었던 적이 있어?",
    "choice criteria 64개 초과로 500 에러가 났던 적이 있어?",
    "diag6 스크립트가 API 호출 없이 오프라인으로 돌았던 적이 있어?",

    # --- 규칙/선호 이웃 (반대 규칙 존재) ---
    "커밋 메시지를 한국어로만 쓰는 규칙이 있었어?",
    "모든 실험을 Docker로 돌리는 규칙이 있었어?",
    "브라우저 자동화를 항상 창 모드로 하던 규칙이 있었어?",
    "HEAD 브랜치에 직접 실험 커밋을 올리던 규칙이 있었어?",
    "API 키를 코드에 하드코딩하던 규칙이 있었어?",
    "실험 보고서를 파일로 남기지 않고 채팅으로만 정리하던 규칙이 있었어?",
    "주석을 영어로만 쓰는 규칙이 있었어?",
    "메모리 저장을 승인 없이 자동으로 하던 규칙이 있었어?",
    "모든 검색을 Exa로 통일하던 규칙이 있었어?",
    "릴리스마다 버전을 0.1씩 올리던 규칙이 있었어?",
    "테스트를 실행하지 않고 커밋하던 규칙이 있었어?",
    "Tailscale 대신 ngrok을 쓰던 규칙이 있었어?",
    "pip 대신 항상 conda를 쓰던 규칙이 있었어?",
    "로그를 한국어로 남기던 규칙이 있었어?",
    "매주 일요일에 메모리를 백업하던 규칙이 있었어?",

    # --- 도구/동작 이웃 (실존하지 않는 옵션) ---
    "web_extract가 JS 렌더링을 기본으로 켜는 옵션이 있어?",
    "keyring.py가 3개 이상의 API 키를 지원하는 옵션이 있어?",
    "run_ablation이 GPU를 사용하는 모드가 있어?",
    "golden_eval_v2에 영어 쿼리가 포함된 적이 있어?",
    "diag63이 pointwise 대신 choice를 쓰는 옵션이 있어?",
    "analyze_ablation이 McNemar 검정을 자동으로 하는 옵션이 있어?",
    "mnemosyne.db에 graph_edges 테이블이 별도로 있던 적이 있어?",
    "beam search에 BM25 랭커가 포함되던 적이 있어?",
    "j1_pipeline에 cross-encoder reranker가 있었던 적이 있어?",
    "Jev gateway가 배치별로 다른 모델을 쓰던 적이 있어?",
    "워치독이 매시간 헬스체크하던 설정이 있었어?",
    "telegram 게이트웨이가 여러 개의 채널을 동시에 서빙하던 설정이 있었어?",
    "exp7a가 choice를 병렬 5로 돌리던 설정이 있었어?",
    "임베딩 캐시 디렉터리가 C드라이브가 아니던 적이 있어?",
    "core_state.db가 mnemosyne.db와 같은 파일이던 적이 있어?",

    # --- 실험/데이터 이웃 (존재하지 않는 수치) ---
    "2x2 ablation에서 B 조건의 hit@3가 50%였던 적이 있어?",
    "τ=0.8에서 noans 오주입이 0건이던 적이 있어?",
    "new gold 44건 중 20건이 0.5를 넘었던 적이 있어?",
    "합성 180건에서 C가 A를 20pp 앞섰던 적이 있어?",
    "op 90건의 pool이 전부 20개 이하였던 적이 있어?",
    "leave-gold-out에서 abstain이 90%였던 조건이 있었어?",
    "diag6의 choice 호출이 200콜이던 적이 있어?",
    "corpus_n이 1000이던 시절의 벤치 결과가 있어?",
    "golden_noanswer_queries가 100건이던 적이 있어?",
    "ablation raw가 900레코드였던 적이 있어?",
    "hit@3 목표가 80%였던 적이 있어?",
    "noans A/B 분모가 30건이던 적이 있어?",
    "τ 풀 재보정이 pool 80으로 돌았던 적이 있어?",
    "Wilson 신뢰구간이 99%로 계산되던 적이 있어?",
    "McNemar p값이 0.05 미만이었던 적이 있어?",
]

# 50개로 조정
fresh = fresh[:50]
print(f"생성: {len(fresh)}건")

out = []
for i, q in enumerate(fresh):
    out.append({"qid": f"nans2_{i+1:03d}", "query": q, "type": "NO_ANSWER",
                "gold_ids": [], "gold_excerpts": [], "auto": "hard-neighbor"})

with open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

print("저장: golden_noanswer_hard_queries.json")
# 어휘 겹침 스팟체크: 코퍼스에서 나온 단어가 쿼리에 있는지
import sqlite3, os
db = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rows = conn.execute("SELECT content FROM working_memory WHERE valid_until IS NULL AND content IS NOT NULL LIMIT 200").fetchall()
conn.close()
corp_text = " ".join(r[0] for r in rows)
sample_words = ["web_extract", "tavily", "bekko", "sqlite", "deepseek", "telegram", "golden", "τ", "hidden"]
for w in ["tavily", "bekko", "sqlite-vec", "deepseek", "telegram", "gateway", "abstain", "choice"]:
    print(f"  코퍼스에 '{w}': {'있음' if w in corp_text else '없음'} | fresh 쿼리 사용: {'있음' if any(w in q for q in fresh) else '없음'}")