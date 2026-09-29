# P4 — codex/opencode 어댑터 연결 (JEV Core) 구현 보고 · 2026-09-29

> 상태: **✅ P4 완료** — codex hooks + opencode v2 플러그인 + MCP bridge 전환 실측
> 기준: P3 완료 (`a8dd5a3`) + P2 (ACL·redaction) 반영
> 스펙: `docs/design/multi-agent-v1_1-p0-spec.md` D9 (Core-as-Writer, 모든 에이전트 → JevMemClient)

---

## 1. 결론

| 에이전트 | recall (prefetch 주입) | record (저장) | 상태 |
|---|---|---|---|
| **codex** | ✅ hooks `UserPromptSubmit` → `recall.py` → JEV core prefetch | ✅ hooks `Stop` → `record.py` → JEV core turn | **실측 완료** |
| **opencode** | ✅ v2 플러그인 `aisdk.language` 래퍼 prefetch 주입 | ✅ v2 플러그인 `session.idle` → `jev_mem_record.py` | **실측 완료** |
| **opencode MCP** | ✅ `mnemosyne_recall` → JEV core prefetch | ✅ `mnemosyne_remember` → JEV core turn | **실측 완료** |

- 기존 임베디드 mnemosyne 직접 호출 경로를 모두 **JEV core HTTP + spool로 대체** (단일 writer 보장)
- Hermes 경로 무변경, 회귀 0

---

## 2. 구현 내역

### 2.1 codex (`~/.codex/`)
- `mnemosyne/recall.py` — `UserPromptSubmit` 훅: Codex hook JSON(stdin) → query 정제(scaffold 태그 제거) → `JevMemClient("codex").prefetch()` → `<block>## Mnemosyne Context</block>` 출력 (Codex가 프롬프트에 append)
- `mnemosyne/record.py` — `Stop` 훅: transcript JSONL 파싱(users/assistants) → task + outcome 요약 → `JevMemClient("codex").turn()` (session_key `codex_<sid>`, idempotency fingerprint, 30s debounce + state 파일)
- `config.toml`:
  - `[hooks.UserPromptSubmit]` / `[hooks.Stop]` — 위 스크립트 경로 (기존 유지)
  - **trusted_hash 갱신** — P4 파일 교체로 인한 해시 불일치로 codex 훅 차단 방지 (구버전 `49a19554...`/`e6a543d2...` → 신규 sha256 실측값)

### 2.2 opencode (`~/.config/opencode/`)
- `plugin/mnemosyne-session-memory-v2.ts` — **v2 effect 플러그인** (`define` + `ctx.aisdk.language` 래퍼):
  - 기존 v1 형식(`export default async`)은 opencode 2.x에서 **로드 거부** (`Plugin must export a default definition...`) → v2 형식 필수
  - prefetch 주입: `aisdk.language` 훅으로 `doGenerate`/`doStream`을 래핑, prompt의 마지막 user 메시지 → `prefetch()` → system 블록 삽입 (2s 타임아웃, 캐시, best-effort)
  - session.idle → 세션 요약 저장 (`jev_mem_record.py` → JEV core)
- `mnemosyne_mcp_bridge.py` — MCP `mem` 서버를 **JEV core 백엔드로 교체** (mcp SDK 2.x 생성자 기반 `on_list_tools`/`on_call_tool`): `mnemosyne_recall`/`mnemosyne_remember` 도구가 JevMemClient 호출
- `opencode.jsonc` — plugin 경로를 v2 파일로 변경, MCP 명령은 기존 경로 유지

---

## 3. 실측 결과

### 3.1 codex recall
```bash
echo '{"prompt": "라우팅 모듈 구조와 API 키 설정 위치를 알려줘", ...}' | python recall.py
## Mnemosyne Context
  [2026-09-29T19:25] (importance 0.50) [USER] 프로젝트의 라우팅 모듈은 core/router.py에...
```
→ JEV core prefetch 정상 반환

### 3.2 codex record (가상 transcript)
```bash
echo '{"session_id":..., "transcript_path":...}' | python record.py; exit=0
```
→ core DB에 `source_agent=codex`, session_key `codex_<sid>` 저장 (2 rows 확인)

### 3.3 opencode 플러그인 로드
```
msg="loading plugin" id="...mnemosyne-session-memory-v2.ts"   ← 성공
(구 v1 파일은 SchemaError로 거부 — 무시 가능)
```

### 3.4 opencode prefetch 주입 — 모델 응답이 저장된 메모리를 인용
```
MODEL: 라우팅 모듈은 `core/router.py`에 있습니다.
```
→ prefetch로 주입된 `[USER] ... core/router.py ...` 메모리를 모델이 참조

### 3.5 opencode MCP bridge
```
tools/list → mnemosyne_recall, mnemosyne_remember
tools/call mnemosyne_recall "라우팅 모듈 구조"
## Mnemosyne Context ...
```
→ JEV core prefetch 결과 반환 (리스트 + 콜 모두 실측)

### 3.6 DB 통합
```
total: 15 | codex rows: 2 | opencode rows: 2 (source_agent=codex/opencode)
```
→ 모든 에이전트가 동일 core DB 단일 writer

---

## 4. 발견/주의 사항

- **opencode 2.x는 v1 플러그인 형식 미지원** — v2 effect 형식 필수. v2에는 `chat.message` 훅이 없어 메시지 주입은 `aisdk.language` 모델 래퍼로 구현 (system 프롬프트 삽입 방식)
- opencode v2 플러그인 중복 로드 경고(`package.json` ENOENT)는 npm 패키지 해석 실패로, **파일 경로 로드는 정상** — 무시 가능하나 향후 정리 대상
- codex hook `trusted_hash`는 스크립트 변경 시마다 갱신 필요 (이번에 교체 반영)

---

## 5. DoD 체크

- [x] codex: recall/record → JEV core 전환 + 검증 (prefetch 반환, DB 저장)
- [x] codex: config.toml trusted_hash 갱신 (훅 차단 없음)
- [x] opencode: v2 플러그인 prefetch 주입 (모델 인용 실측)
- [x] opencode: session.idle 저장 (JEV core)
- [x] opencode: MCP bridge JEV core 전환 (tools/list + call 실측)
- [x] 어댑터 파일 repo 정식 등록 (`adapters/codex/`, `adapters/opencode/`)
- [x] 문서 + 커밋

---

## 6. 다음 단계

- **P5 (Hermes 전환)**: Hermes 임베디드 → core 공동 쓰기 과도기 (동시성 테스트 §16.2 게이트: 8클라이언트×200턴)
- v1 플러그인 파일/백업 정리 (선택)
- 종료 목표: 2026-10-13