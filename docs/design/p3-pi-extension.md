# P3 설계 — pi Extension 연결 (jev-mem-pi)

> 상태: **설계 대기 (승인 전 코드 작성 금지)** · 2026-09-29
> 기준: v0.1.0 릴리즈 + P1(core 분리) 완료 (`140fa46`)

---

## 1. 목적

Hermes에서 검증된 JEV-Mnemosyne middleware(\(J1 rerank + G-qual/G-AS write gate\))를
**pi 코딩 에이전트(0.87.1)**에서도 동일하게 동작하게 연결.

- 연결 범위 = **Hermes와 동일**: prefetch(컨텍스트 주입) + sync_turn(write gate 적용 저장)
- Hermes 경로는 **변경하지 않음** (v0.1.0 릴리즈 동작 유지, 회귀 0)

---

## 2. 프로세스 모델 (사용자 우려 반영)

### 2.1 중복 방지 원칙

| 우려 | 해결 |
|---|---|
| **프로세스 중복** (pi가 요청마다 spawn) | **장수 헬퍼 프로세스 1개** — pi 확장이 세션 시작 시 1회 spawn, stdio JSON-RPC로 재사용. Hermes(임베디드) + pi 헬퍼 = **총 2개** 상주. 요청별 spawn 없음 |
| **임베딩 모델 중복 로드** (fastembed, RAM 민감) | 장수 프로세스가 **1회만 로드** (요청별 spawn이면 매번 재로드 → RAM/지연 폭증) |
| **DB 동시 쓰기 충돌** (Hermes·pi 동시 sync_turn) | `mnemosyne.db`는 **SQLite WAL + busy_timeout(30s)** — 동시 쓰기는 잠금 대기로 직렬화. 손상 없음 |
| **레코드 중복/섞임** | 세션 ID 접두사 격리: Hermes `hermes_<sid>` / pi `pi_<sid>` — 같은 DB에 쌓여도 세션으로 분리, 중복 저장 없음 |
| **JEV API 동시 호출** | Hermes prefetch와 pi prefetch가 동시에 Jev 호출 가능하나 짧음(실측 275ms) — 재시도(1회)로 흡수 |

### 2.2 구조

```
pi process (TS extension)
  │  stdio JSON-RPC (지속 연결)
  ▼
hev-mw-pi helper (Python 장수 프로세스, 1개)
  ├─ prefetch  → core.j1_engine.run(beam, query, pipeline=gateway.j1_pipeline)
  ├─ sync_turn → gateway.write_gate.evaluate / evaluate_assistant (4-way 분기)
  └─ Mnemosyne BeamMemory(db_path=...) ←── 같은 mnemosyne.db (WAL, busy_timeout)
                                               ▲
Hermes 프로세스 (기존 임베디드, 변경 없음) ──────┘
```

- **Hermes는 그대로 임베디드** (플러그인 변경 없음 — 안정성 최우선)
- **pi 헬퍼는 core 재사용** — 파이프라인 불일치 0, 코드 중복 0

---

## 3. Public API (pi 헬퍼 — CLI + JSON-RPC)

```bash
# 장수 모드 (JSON-RPC over stdio)
jev_mw_pi --serve

# 요청 (stdin 한 줄 JSON):
{"cmd": "prefetch", "query": "...", "session_id": "..."}
{"cmd": "sync_turn", "user": "...", "assistant": "...", "session_id": "...", "messages": [...]}

# 응답 (stdout 한 줄 JSON):
{"ok": true, "block": "## Mnemosyne Context\n..."}
{"ok": true, "user_skipped": false, "asst_skipped": true}
```

- 헬퍼는 Hermes 무관 (core + gateway만 import, standalone — 섀도잉 없음)
- 장수 프로세스는 pi 확장이 종료 시 kill (확장 해제 시 정리)

---

## 4. DoD (Definition of Done)

- [ ] `adapters/pi/jev_mw_pi.py` 생성 — JSON-RPC serve + prefetch/sync_turn 핸들러
- [ ] `~/.pi/agent/extensions/pi-jev-mem.ts` 생성 — ExtensionAPI로 헬퍼 spawn + before_agent_start(주입) / turn_end(저장) 연결
- [ ] extensions package.json `pi.extensions`에 등록 (hoplite·codegraph와 함께)
- [ ] pi 스모크: prefetch 주입 실측 (로그 probe로 시스템 프롬프트에 블록 등장)
- [ ] pi 스모크: sync_turn 저장 실측 (DB에 `pi_<sid>` 세션 [ASSISTANT]/[USER] 레코드)
- [ ] **동시 실행 충돌 테스트**: Hermes(라이브) + pi 동시 sync_turn → SQLITE_BUSY 없음, 손상 없음
- [ ] Hermes 회귀 확인: smoke_write_gate 7/7 유지
- [ ] 커밋 + 문서

---

## 5. 구현 순서

1. `adapters/pi/jev_mw_pi.py` — JSON-RPC 헬퍼 (core/gateway import, WAL+busy_timeout 설정)
2. `adapters/pi/test_jev_mw_pi.py` — 헬퍼 단독 스모크 (prefetch/sync_turn/충돌)
3. `pi-jev-mem.ts` — 확장 (spawn 관리, before_agent_start/turn_end 훅)
4. `pi.extensions` 등록 + pi 로드 확인
5. 동시 실행 충돌 테스트 + Hermes 회귀 확인
6. 커밋 + docs/design 갱신

---

## 6. 리스크 / 롤백

| 리스크 | 대응 |
|---|---|
| 장수 프로세스 관리 실패 (좀비) | 확장 해제 시 kill + stderr 로그. 비정상 종료 시 pi 확장이 재spawn |
| Hermes와 동시 쓰기 시 busy | busy_timeout 30s + WAL. 그래도 실패 시 "저장 스킵+로그" (데이터 손실 없음 — Hermes 경로는 무관) |
| pi 확장 로드 실패 | `pi.extensions` 배열 등록 누락이 원인일 수 있음 — 등록 확인 |
| fastembed 로드 실패 (헬퍼 최초 기동) | vec lane만 fallback (pool은 fts/imp/graph로 구성) — Hermes와 동일 fallback 계약 |

**롤백**: pi 확장 파일 삭제 + package.json 배열 항목 제거. Hermes 경로는 무관.

---

## 7. 승인 필요

- [ ] **프로세스 모델** — 장수 헬퍼 1개 (stdio JSON-RPC) 방식 OK?
- [ ] **충돌 대응** — WAL+busy_timeout + 세션 접두사(pi_) OK?
- [ ] **Scope** — Hermes 경로 변경 없음 (어댑터만 추가) OK?