# PerfectRecall vs 내 구현 — 격리 A/B 비교

2026-10-01 실측. 상세: `docs/design/embed-benchmark-final-report.md` §8c.

## 결과 요약 (코퍼스 419 스팬, 쿼리 180)

| 지표 | 내 구현 (lane+rerank) | PerfectRecall (full-scan) |
|---|---|---|
| Acc@1 | 0.489 | **0.806** |
| MRR | 0.556 | **0.849** |
| 지연/쿼리 | **0.23 s** | 0.38 s |
| Jev 요청/180쿼리 | **179** | 1,800 |
| 프로세스 메모리 | a8m 615 MB | **12 MB** |

핵심: lane pool 정답 커버 145/180(80.6%) = PR Acc와 일치 → 내 정확도 하드캡은 lane pool 누락(19.4%) + `_filter_and_rank` 한국어 단답 탈락.

## 재현 절차

1. **스크래치 DB 생성 (PR venv)** — `pr-venv/Scripts/python.exe build_scratch_db.py scratch_eval.db`
   (코퍼스 419: kodialogbench 60×5 + koalpaca 40 + kosgd 40 + 기계독해 40)
2. **벡터 백필 (내 venv, 필수!)** — PR venv로 만든 DB는 임베딩 0건
   `jev-mem/venv/Scripts/python.exe backfill_embeddings.py` (a8m으로 memory_embeddings + vec_working 채움)
3. **PR 평가** — `pr-venv/Scripts/python.exe eval_pr.py scratch_eval.db 180`
4. **내 구현 평가** — `jev-mem/venv/Scripts/python.exe eval_mine.py scratch_eval.db 180`
   (cwd를 스크래치 루트로: perfectrecall/ 아래에서 실행하면 PR 클론 mnemosyne가 잡힘)
5. 메모리: `measure_pr_mem.py` (PR 12MB), 내 구현은 라이브 데몬 기측정 615MB(a8m)

## 격리 주의

- PR 클론의 `mnemosyne/` 디렉토리가 같은 cwd에 있으면 import가 PR 것을 잡음 → **스크립트를 scratch 루트에서 실행**
- 내 venv(jev-mem)로 PR venv 생성 DB를 열 때 vec0 모듈 로드 필요 (내 venv는 지원)
- 실 DB/config/데몬 무접촉 — 전부 스크래치 전용 DB·env