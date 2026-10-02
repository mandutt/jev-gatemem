"""JEV 배치 예산 산정기 — 실행 전 질문 수·HTTP requests·입력 토큰·비용 추정.

사용법:
    # choice 경로 (운영 파이프라인 rerank / gate 계열) — 후보 풀 JSON
    python estimate_jev_budget.py --pool pool.json --query "질문 텍스트"

    # relevance 전체 스캔 경로 (jev_recall._rank / PR식) — 후보 목록 JSON
    python estimate_jev_budget.py --corpus corpus.json

    # 라이브 DB 전체 스캔 추정 (visible memories: working + episodic content)
    python estimate_jev_budget.py --corpus-db "%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db"

    # 예산 상한 지정 — 예상 비용이 초과하면 exit 2 (게이트로 사용)
    python estimate_jev_budget.py --corpus-db <db> --budget 1.0
    # 게이트 판정은 실측 중간 기준(Q/26); 상한(질문 수)은 보고용 보수치.

실측 앵커 (2026-10-01, TypeSafe 대시보드/result json 역산 검증):
  - 대시보드 requests = HTTP 요청 수 = fanout 배치 수 (질문 수가 아님)
    21,892 requests × 11.7K tokens ≈ 256.19M — 1:1 역산으로 확정.
  - 배치 1개 ≈ 11.7K input tokens
  - 질문 수 Q ≈ Σ ceil(후보 utf8 bytes / 8,000)
  - HTTP requests ≈ Q/26(한글 120자 라벨 실측, Run L 1,234질문→48콜) ~ Q(극단 상한)
  - 전체 스캔 토큰 하한 ≈ 코퍼스 총 바이트 × ~0.27(영문) ~ 0.45(한글) tokens/byte
  - choice 풀 40 ≈ 쿼리당 1 요청 ≈ 12~14K tokens
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys

PRICE_PER_TOKEN = 0.042e-6  # USD (input 전용, output 무료)


def _ascii_json_widths() -> tuple[int, ...]:
    """mnemosyne.core.jev._ASCII_JSON_WIDTHS와 동일: JSON 직렬화 폭 - 2."""
    return tuple(len(json.dumps(chr(c), ensure_ascii=False)) - 2 for c in range(128))


_ASCII_W = _ascii_json_widths()


def char_width(ch: str) -> int:
    """jev.chunks()와 동일한 문자 폭: ASCII는 JSON 폭, 그 외는 utf-8 바이트 수."""
    o = ord(ch)
    return _ASCII_W[o] if o < 128 else len(ch.encode("utf-8"))


def chunks_count(text: str, size: int = 8000) -> int:
    """jev.chunks() 규칙 그대로의 질문 분할 수 (빈 텍스트 = 1)."""
    if not text:
        return 1
    n, part, length = 0, False, 0
    for ch in text:
        w = char_width(ch)
        if length + w > size and part:
            n += 1
            part, length = False, 0
        part = True
        length += w
    return n + 1


def load_texts(path: str) -> list[str]:
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("candidates", "items", "rows", "memories", "pool", "spans"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = list(data.values())
    texts: list[str] = []
    for it in data:
        if isinstance(it, str):
            texts.append(it)
        elif isinstance(it, dict):
            c = it.get("content") or it.get("text") or it.get("label")
            if c:
                texts.append(c)
            elif it.get("candidates"):
                texts += [x for x in it["candidates"] if isinstance(x, str)]
    return texts


def visible_memories(db_path: str) -> list[str]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    texts: list[str] = []
    try:
        for table in ("working_memory", "episodic_memory"):
            try:
                rows = con.execute(f"SELECT content FROM {table}").fetchall()
            except sqlite3.OperationalError:
                continue
            texts += [r[0] for r in rows if r[0]]
    finally:
        con.close()
    return texts


def main() -> int:
    ap = argparse.ArgumentParser(
        description="JEV 배치 실행 전 예산 산정 (질문 수 → HTTP requests → 입력 토큰 → 비용)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pool", help="choice 경로: 후보 풀 JSON (content 문자열/객체 리스트)")
    src.add_argument("--corpus", help="relevance 전체 스캔: 후보 목록 JSON")
    src.add_argument("--corpus-db", help="relevance 전체 스캔: SQLite DB (working+episodic content, 읽기 전용)")
    ap.add_argument("--query", default="", help="쿼리 텍스트 (state 오버헤드 산정용, choice 경로)")
    ap.add_argument("--excerpt", type=int, default=120,
                    help="choice 경로 라벨 절단 길이 (기본 120 = JEV_EXCERPT_LIMIT)")
    ap.add_argument("--budget", type=float, default=0.0,
                    help="예산 상한 USD (0 = 미적용). 예상 비용(실측 중간 기준) 초과 시 exit 2")
    args = ap.parse_args()

    if args.pool:
        texts = [t[: args.excerpt] for t in load_texts(args.pool)]
        mode = f"choice (운영 rerank, pool {len(texts)}, excerpt {args.excerpt})"
        scan = False
    else:
        texts = load_texts(args.corpus) if args.corpus else visible_memories(args.corpus_db)
        mode = f"relevance 전체 스캔 (코퍼스 {len(texts)} 스팬)"
        scan = True

    if not texts:
        print("ERROR: 후보 없음 — 입력 파일/DB를 확인하세요")
        return 2

    labels = [t[: args.excerpt] for t in texts]  # choice 라벨 절단 (운영 경로 동일)
    total_bytes = sum(len(t.encode("utf-8")) for t in texts)
    label_bytes = sum(len(t.encode("utf-8")) for t in labels)
    questions = sum(chunks_count(t) for t in texts)

    print(f"모드      : {mode}")
    print(f"후보      : {len(texts):,}개 | 총 utf8 {total_bytes:,} bytes | 질문(8KB chunk) {questions:,}개")

    if scan:
        # fanout 배치 실측: 요청 수 ≈ 질문 수/26(한글 120자 라벨, Run L 1,234질문→48콜)
        # ~ 질문 수(극단 상한). 토큰: 1 요청 ≈ 11.7K (21,892×11.7K=256M 역산).
        requests_mid = max(1, math.ceil(questions / 26))
        requests_hi = questions
        tok_lo = total_bytes * 0.27   # 영문 4 chars/token (하한)
        tok_mid = requests_mid * 11700
        tok_hi = requests_hi * 11700
        print(f"HTTP req  : ~{requests_mid:,}(실측 Q/26) ~ {requests_hi:,}(상한=질문 수)")
        print(f"입력 토큰 : {tok_lo/1e6:.1f}M(바이트 하한) ~ {tok_mid/1e6:.1f}M(중간) ~ {tok_hi/1e6:.1f}M(상한)")
        costs = (tok_lo * PRICE_PER_TOKEN, tok_mid * PRICE_PER_TOKEN, tok_hi * PRICE_PER_TOKEN)
        print(f"비용      : ${costs[0]:.2f} ~ ${costs[1]:.2f} ~ ${costs[2]:.2f} @ $0.042/1M input (게이트=중간, 상한은 보고용)")
        worst = max(costs)
        ref = costs[1]
    else:
        # choice: state + 질문(라벨) 전량이 입력. 쿼리/인스트럭션 오버헤드 ~600 chars.
        # 실측: 풀 40 ≈ 1 배치 ≈ 12~14K tokens → 배치 수 기준이 byte 환산보다 정확.
        state_chars = len(args.query) + 600
        n_batch = max(1, math.ceil((label_bytes + state_chars) / 48000))
        tok_lo = (label_bytes + state_chars) * 0.27
        tok_hi = n_batch * 13000
        print(f"HTTP req  : ~{n_batch} (48KB 배치, 풀 40 ≈ 1)")
        print(f"입력 토큰 : {tok_lo/1e6:.2f}M(바이트 하한) ~ {tok_hi/1e6:.2f}M(배치×13K 상한)")
        costs = (tok_lo * PRICE_PER_TOKEN, tok_hi * PRICE_PER_TOKEN)
        print(f"비용      : ${costs[0]:.3f} ~ ${costs[1]:.3f} @ $0.042/1M input (게이트는 상한 기준)")
        worst = max(costs)
        ref = costs[1]

    if args.budget > 0 and ref > args.budget:
        print(f"\nBUDGET VIOLATION: 예산 ${args.budget:.2f} < 예상 비용 ${ref:.2f} — 실행 전 사용자 승인 또는 예산 상향 필요 (exit 2)")
        return 2
    print("\n산정은 추정치입니다 — 크레딧 잔액과 대조 후 실행하세요 (스모크 1콜 200 확인 선행).")
    return 0


if __name__ == "__main__":
    sys.exit(main())