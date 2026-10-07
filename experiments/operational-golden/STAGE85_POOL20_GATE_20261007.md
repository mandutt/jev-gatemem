# STAGE85 — production-exact pool20 게이트 (2026-10-07, 400콜, err 0, 301s)

> C AI 최종 게이트 — 시간 필터 제거(production-exact) + live60 paired 3-run + op90 rank>20 체크.

## 결과

### 0콜 체크: op90 gold rank (production-exact pool)
- **rank>20: 2건** — `#80 deepseek 장문` rank 41, `#87 camelai-serial-proxy` rank 36
- **MISS 4건**: 리뷰 전용 턴 / 구현됐다는 말 / provider / 전환 전 (pool 60 밖)

### live60 paired 3-run (360콜)

| 조건 | block abstain | valid+yes 오차단 |
|---|---|---|
| k60 | 0/38 (0·0·0) | 0/22 |
| k20 | 0/38 (0·0·0) | 0/22 |

### noans FP (50, 1-run)

| 조건 | FP |
|---|---|
| k60 | 22 |
| k20 | **15** (-7, 32%) |

## 판정 — C AI 게이트 미통과 → pool20 전면 채택 금지

- **answer-support rank>20 = 2건** → C AI 롤백 규칙 발동: **pool20(및 30/40) 단독 채택 금지**
- k20은 noans FP -7 이득 + 라이브 방어 동일(0)이나, **rank 41·36의 정답 2건을 영구 유실** —
  트레이드오프가 h(해로움) 기준으로도 정당화 불가 (정답 2건 ≫ 하드 noans FP 7건의 실질 해로움)
- **결론: pool 60 유지 확정** — 남은 방향은 **candidate diversification** (60 유지 + 규칙/사실 슬롯)

## raw

- `data/stage85_pool20_gate.json`
- 러너: `stage85_pool20_gate.py` — production-exact pool (시간 필터 없음)