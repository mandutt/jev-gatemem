# P3 — pi Extension 연결 (pi-jev-mem) 구현 보고 · 2026-09-29

> 상태: **✅ P3 완료** — pi 확장 로드 + prefetch 주입 + sync_turn 저장 실측
> 기준: P2 완료 (카오스 7/7) + ACL·redaction 승인 반영 (`5b41a4c`)
> 스펙: `docs/design/multi-agent-v1_1-p0-spec.md` D9 (Core-as-Writer, pi → JevMemClient)

---

## 1. 결론

pi 코딩 에이전트(0.87.1)에서 **JEV-Mnemosyne middleware 연결 완료**:

- **prefetch**: 턴 시작 시 `jev_mem_core.client.prefetch()` → `## Mnemosyne Context` 블록을 system prompt에 주입
- **sync_turn**: 턴 종료 시 `client.turn()` → write gate(4-way) 적용 후 core DB 저장 (`source_agent=pi`)
- **core 자동기동 + 스풀**: core 다운 시 auto-start + JSONL 스풀 (손실 0)
- **Hermes 경로 무변경**: 회귀 0 (smoke/golden/redact/chaos 전체 유지)

---

## 2. 구현

### 2.1 `adapters/pi/pi-jev-mem.ts` (신규)

pi 0.87.1 ExtensionAPI (`pi.on(...)`) 기반 — hoplite-advisor 패턴(파이썬 헬퍼 spawn).

| 훅 | 동작 |
|---|---|
| `session_start` | `ctx.sessionManager.getSessionId()` 캐시 (session_key 용) |
| `before_agent_start` | prompt ≥20자 → `python -m jev_mem_core.client prefetch "<prompt>"` (2.0s 타임아웃, D7a) → systemPrompt에 블록 append |
| `turn_end` | assistant = `evt.message.content` text 블록; user = session entries 마지막 user 메시지 → `client turn --session-id <sid> --user ... --assistant ...` → 로그 |

- **spawn**: Hermes venv python + `PYTHONPATH=<repo>` (zero-dependency, `spawn`만 사용)
- **best-effort**: prefetch 실패 → 턴 무중단; turn 실패 → client가 스풀
- env 오버라이드: `JEV_MEM_REPO`, `JEV_MEM_PYTHON`

### 2.2 `~/.pi/agent/extensions/` 등록

- `pi-jev-mem.ts` 복사 + `package.json` `pi.extensions` 배열에 `./pi-jev-mem.ts` 추가
- 로드 확인: `pi --mode json` 실행 시 `[jev-mem] session_start <sid>` stderr 로그

### 2.3 `jev_mem_core/client.py` 버그 수정 (P3에서 발견)

**`_token` 메서드/속성 이름 충돌** — 401 재시도에서 `self._token = None`이 메서드를 덮어써
이후 호출에서 `TypeError: 'NoneType' object is not callable` → "core failed"로 오판·스풀.
→ `_token_cache`로 분리. (P2 카오스가 401을 유발하지 않아 미발견이었음)

---

## 3. 실측 결과

### 3.1 확장 로드
```
[jev-mem] session_start 01a0eca7-44a1-729b-8621-8e8f4f52dc18   ← 확장 로드 확인
```

### 3.2 DB 저장 (pi 세션)
```sql
[pi:pi_01a0eca9-259f-74cc-9e7d-68da8ae67822] [ASSISTANT] `ask_user_question` 도구는...
[pi:pi_p-conc-1] [ASSISTANT] pi asst 0
[pi:pi_pi-test-2] [USER] hello
```
- session_key = `pi_<pi session id>` (프로세스/채널 격리 확인)
- `source_agent=pi` 메타데이터 (provenance, D8)

### 3.3 prefetch 주입
같은 주제 실질 문장 저장 후 쿼리:
```
## Mnemosyne Context
  [2026-09-29T19:25] (importance 0.50) [USER] 프로젝트의 라우팅 모듈은 core/router.py에...
```
(126자, Hermes embedded와 동일 포맷)

### 3.4 동시 쓰기 (Hermes + pi, 10턴 병렬)
- 10/10 성공, **SQLITE_BUSY 0** (core 유일 writer 설계 실증)
- idem key 충돌: 409 `IDEMPOTENCY_CONFLICT` (same key, different payload — D5 정상)

### 3.5 회귀
smoke 7/7 · P1 golden · redact 19/19 · chaos 7/7 **전부 유지**

---

## 4. 발견된 동작 특성 (설계 의도)

- prefetch 보수 필터: ~~`[ASSISTANT]` 프리픽스 메모리는 prefetch 제외~~
  (**2026-10-05 해제** — `_PREFETCH_EXCLUDED_PREFIXES = ()`, 커밋 `ffb2ca5`.
  회귀 실측: op-90 81/90 유지·noans 오주입 0·장문 gold 1/19→8/19. 무관 assistant는
  어휘 게이트가 차단). `[USER]` 프리픽스는 회수됨.
- 한국어 쿼리는 음절 단위 토큰화라 짧은 메모리(1~2단어)는 오버랩 게이트
  (`min_distinctive=2`, `min_coverage=0.30`)에서 걸러질 수 있음 — 실질 문장 저장 후
  정상 회수 확인.
- turn_end는 assistant 턴마다 발생 (Hermes의 turn-final 1회와 다름 — pi는
  intermediate tool_calls 턴도 `turn_end` 이벤트로 받음. Hermes와 동일하게 게이트가
  판정한다는 점에서 문제 없음).

---

## 5. DoD 체크

- [x] `adapters/pi/pi-jev-mem.ts` 생성 (ExtensionAPI 기반)
- [x] `~/.pi/agent/extensions/pi-jev-mem.ts` + package.json `pi.extensions` 등록
- [x] pi 스모크: prefetch 주입 실측 (`## Mnemosyne Context` 블록)
- [x] pi 스모크: sync_turn 저장 실측 (`source_agent=pi` + `pi_<sid>` 행)
- [x] 동시 실행 충돌 테스트: Hermes+pi 10턴 → SQLITE_BUSY 0
- [x] Hermes 회귀: smoke 7/7 · golden · redact · chaos 유지
- [x] 커밋 + 문서

---

## 6. 다음 단계

- **P4 (다른 에이전트)**: Codex/opencode 확장 동일 패턴 (`JevMemClient` 재사용)
- **P5 (Hermes 전환)**: Hermes 임베디드 → core 공동 쓰기 과도기 진입 (플래그 뒤)
  - 전제: 동시성 테스트 (§16.2, 8클라이언트×200턴) 승인 게이트
- 종료 목표: 2026-10-13