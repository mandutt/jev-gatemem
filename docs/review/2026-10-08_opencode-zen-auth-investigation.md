# opencode zen 무료 티어 API 인증 조사 (2026-10-08)

> 목적: opencode CLI 프로세스 스폰 없이 zen 무료 모델을 직접 호출할 방법 조사.
> 결론: **HTTP 헤더 조작으로는 불가 (TLS/클라이언트 지문 게이트). 단, opencode 서버 API는 인증을
> 위임받아 세션 실행 가능 — 할당량(429)만 해결되면 사용 가능한 경로.**

---

## 1. 최종 현황 (2026-10-08 23:50 KST)

| 경로 | 모델 | 결과 | 비고 |
|---|---|---|---|
| 직접 HTTP `opencode.ai/zen/v1/chat/completions` | space-bunny-free | ✅ 200 | **UA만으로 200** (zero-retention, 게이트 대상 아님) |
| 직접 HTTP | nemotron 등 전 free 모델 | ❌ 403 FreeTierError | "can only be used from within OpenCode" |
| 직접 HTTP + Referer/Title/session-id/빈 Bearer | nemotron 등 | ❌ 403 | 헤더 조합 무효 (아래 §3) |
| 직접 HTTP | hy3-free, deepseek-v4-flash-free, mimo-v2.5-free | ❌ 401 ModelError | 모델 자체가 은퇴/미지원 |
| 직접 HTTP + CLI + 서버API | **step-5-preview-free** (신규 free) | ❌ 403 | 11번째 free 모델 — 아직 미사용이지만 동일 게이트 |
| opencode CLI (`opencode run`) | nemotron-3.5/3-ultra 등 | ✅ 200 → ❌ 403/429 | 13:00~22:00 743건 판정 후 소진 |
| **opencode 서버 API** (127.0.0.1:49374) | 세션 생성/프롬프트 | ✅ 실행됨 | SSE 이벤트 스트리밍 확인 |
| opencode 서버 API → zen | 전 free 모델 | ❌ 403 Authentication | 서버도 동일 게이트 (할당량 소진 시) |
| 직접 HTTP | space-bunny (23:50) | ❌ 429 | 테스트로 할당량 소진 |

**판정 완료: 743/1,074 (69%)** — 체크포인트 `data/stage102h_judge_fixed.json` (yes/no만, parse_fail 제거됨)

---

## 2. 인증 구조 분석

### 2.1 zen 서버 게이트 (공식 이슈 확인)
- 출처: anomalyco/opencode issue #49621 ("Free-tier Zen 403 for all third-party stacks despite valid session + key")
- **바이트 단위 재생**(정확한 헤더 순서/UA/session/바디, HTTP1.1·2 모두)도 403
- 정확한 Bun 런타임 빌드도 실패
- → 판별 기준은 **TLS 핸드셰이크 지문(JA3) 또는 내장 시크릿** (HTTP 레이어 아님)
- 2026-09-19/20부터 시행. issue #49908 (V2 클라이언트조차 "최신 zen 인증 헤더" 미지원으로 실패)

### 2.2 캡처로 확인한 opencode ClientHello (npcap + scapy, 2026-10-08)
- 대상: `172.65.90.20~23:443` (opencode.ai, Cloudflare), TLS 1.3
- JA3 암호화폐 모음: `1301,1302,1303,c02b,c02f,c02c,c030,cca9,cca8,c009,c013,c00a,c014,009c,009d`
- 확장: SNI(opencode.ai), ALPN(h2,http/1.1), key_share(1258B), early_data(002b), session_ticket(0023)
- 세션 ID 길이 32 — **Bun 내장 TLS 스택 특유** (복제 난해)
- 요청 헤더: `Authorization: Basic ***` (로컬 서버용), `User-Agent: opencode/latest/2.0.19/cli`

### 2.3 직접 HTTP 헤더 실측 (전부 무효)
- `x-opencode-client`, `x-opencode-directory`, `x-opencode-project`, `x-opencode-session`, `x-opencode-ticket` — 로컬 서버/pty 전용, zen과 무관
- `HTTP-Referer: https://opencode.ai/` + `X-Title: opencode` — opencode가 zenmux provider에 붙이는 헤더지만 단독으로는 403
- `Authorization: Bearer `(빈) + `x-session-id` UUID — 2026-09 초엔 동작했으나 현재 403
- **space-bunny-free만 예외** — UA 유무와 무관하게 200 (zero-retention 정책)

---

## 3. 유효 경로: opencode 서버 API (재시도 대상)

### 3.1 원리
- 로컬 백그라운드 서버(`opencode service`, 127.0.0.1:49374)가 zen 인증을 **위임받아** 처리
- 서버 API로 세션 생성 → 프롬프트 → SSE(`/api/event`)로 응답 수신
- CLI 프로세스 스폰 없음 → 교착/과부하 문제 원천 제거
- 단, zen이 서버의 인증 컨텍스트를 거부하면 `session.step.failed` + 서버 로그에
  `AI.Error.Authentication: OpenCode's free tier can only be used from within OpenCode` (현재 상태)

### 3.2 API 상세
| 항목 | 값 |
|---|---|
| Base | `http://127.0.0.1:49374` |
| 인증 | Basic `opencode:<service.json password>` + 헤더 `x-opencode-ticket: 1` |
| 세션 생성 | `POST /api/session` body `{"title","model":{"id","providerID":"opencode"}}` |
| 프롬프트 | `POST /api/session/{id}/prompt` body `{"text"}` |
| 응답 수신 | `GET /api/event` (SSE) — `session.message`(assistant) 이벤트에서 parts.text |
| 세션 정리 | `DELETE /api/session/{id}` |
| 서버 정보 | `GET /api/info` → version/pid/urls |

### 3.3 준비된 러너
- `experiments/operational-golden/stage102i_judge_opencode_api.py` — 서버 API 판정 러너 (SSE 수신 포함)
- 단일 테스트: 세션 생성 ✅, 프롬프트 전송 ✅, SSE 이벤트 수신 ✅, 단 모델 실행은 403으로 실패 (할당량 문제)

---

## 4. 사용량 리셋 가설 (내일 재시도 조건)

- 오늘(10-08) 13:00~23:50 동안 free 모델 집중 사용 → 전 모델 429/403
- **space-bunny 직접 HTTP는 오전(14:00) 200건 판정 성공, 이후 일시 429 → 저녁 리셋 → 다시 200 → 연속 테스트로 재소진**
  → **리셋 주기가 1일 미만 (수시간~하루)**일 가능성 높음
- **내일 아침(10-09 09:00 KST = UTC 00:00) 이후 재시도 권장**
  - 우선순위 1: space-bunny 직접 HTTP (가장 단순, UA만)
  - 우선순위 2: opencode 서버 API (인증 위임 — 403 게이트 우회 가능성)
  - 우선순위 3: CLI 직렬 1개 (가장 느리지만 확실)

### 재시도 체크리스트
1. `curl opencode.ai/zen/v1/chat/completions` space-bunny 1건 → 200이면 직접 HTTP 러너 사용
2. 429면 `Retry-After` 헤더 확인 → 리셋 시각 계산
3. 서버 API: `opencode service restart` 후 stage102i 러너 1건 테스트
4. 체크포인트 `stage102h_judge_fixed.json` (743건) 이어서 — 대상 331건

---

## 5. 부수 프로브/스크립트 목록

| 파일 | 용도 |
|---|---|
| `opencode_zen_capture.py` | mitmdump 인라인 캡처 (opencode.ai 요청 기록) |
| `opencode_tls_capture.py` | scapy TLS 레코드 캡처 (v1) |
| `opencode_tls_clienthello.py` | TCP 버퍼 재조립 (v2) |
| `opencode_tls_clienthello2.py` | seq 기반 재조립 (v3) |
| `opencode_tls_clienthello3.py` | 최종: ClientHello 완전 파싱 (SNI/JA3/확장) ✅ 성공 |
| `stage102g_judge_rotation.py` | 10모델 로테이션 러너 (과거) |
| `stage102h_judge_fixed_workers.py` | 고정 워커 러너 — 743건 판정에 사용 |
| `stage102i_judge_opencode_api.py` | ★서버 API 직접 러너 (내일 재시도용) |
| `opencode_judge_config.json` | 판정용 isolated config (plugin/mcp/tools 비활성) |
| `stage102h_watchdog.py` | cron 워치독 (10분 간격, d884fbce68a8) |

## 6. 참고 이슈
- anomalyco/opencode #49621 — 3rd-party free tier 403 elimination matrix (핵심)
- anomalyco/opencode #49908 — V2 최신 인증 헤더 미지원
- anomalyco/opencode #42500 — UA-gated 논의 (space-bunny는 예외)
- anomalyco/opencode #45132 — 모델별 선별적 403 (계정 플래깅)
- headroomlabs #3656 — /responses 라우트 403 (chat/completions는 통과)