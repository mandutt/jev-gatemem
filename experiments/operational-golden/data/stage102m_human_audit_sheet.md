# 인간 감사 (Human Audit) — 16건

> 각 항목: **응답이 메모리 컨텍스트를 "근거로 인용"했는가?** 
> - yes = 응답이 특정 메모리(파일 경로, 설정, 과거 결론 등)를 인용하며 답함
> - no = 일반 지식/추론으로 답함 (메모리 인용 없음)
> 
> 참고용: 어제(nemotron 계열 등)와 space-bunny의 판정이 갈린 케이스만 뽑았습니다.
> 정답(인간 기준)을 각 행 끝에 기록해 주세요.

| # | cls | k | framing | 질문 | 응답 요지 | 어제 판정 | SB 판정 | **인간 판정** |
|---|---|---|---|---|---|---|---|---|
| 1 | block | 5 | True | start_proxy.cmd 재부팅 후 왜 안 돌아가? | UTF-8 인코딩+LF 줄바꿈 원인 (메모리 근거) | yes | no | |
| 2 | block | 2 | True | verifier-pilot은 코딩 품질만 보면 돼? | 아니요, "더 나은 답변 품질"이 목표 (메모리 근거) | no | yes | |
| 3 | block | 2 | True | CAMOFOX_URL 제거한 이유? | 사용자가 camofox 흔적 제거를 원해서 (메모리 근거) | no | yes | |
| 4 | block | 3 | False | start_proxy.cmd 재부팅 후 왜 안 돌아가? | UTF-8 인코딩+LF 줄바꿈 원인 (메모리 근거) | no | yes | |
| 5 | yes | 3 | True | ADR Final 이후에 뭐 하면 안 돼? | 신규 설계/ADR 금지 등 (메모리 근거 — 실제 규칙) | yes | no | |
| 6 | block | 5 | True | CAMOFOX_URL 제거한 이유? | camofox 흔적 제거 요청 기록 (메모리 근거) | no | yes | |
| 7 | yes | 0 | None | DTO 분리 어디까지 하면 돼? | 변경 이유·사용 계층 다를 때 분리 (일반론) | yes | no | |
| 8 | block | 2 | True | 67차 실험 최종 결론 뭐였지? | best-of-5(G3)+selective recovery(D) (메모리 근거) | no | yes | |
| 9 | block | 2 | False | skill_manage create 파라미터 뭐 써야 하지? | content 파라미터 사용 (메모리 근거 — 실제 경험) | no | yes | |
| 10 | block | 3 | True | 스킬 만들 때 file_content로 보내면 돼? | 아니요, content로 보내야 함 (메모리 근거) | no | yes | |
| 11 | yes | 2 | False | 한국어 말투 규칙 뭐지? | 한국어/영어 혼용 규칙 (메모리 근거 — 실제 규칙) | yes | no | |
| 12 | yes | 2 | True | Hermes 데스크톱 워치독 런처 어디 있어? | 경로 C:\Users\mandu\hermes-made\hermes-gateway-watchdog\ (메모리 근거) | yes | no | |
| 13 | block | 5 | False | codex CLI에서 메모리 기록되나? | 네, ~/.codex/config.toml hooks (메모리 근거 — 실제 연동) | no | yes | |
| 14 | valid | 2 | False | 자동 시작 설정 어떻게 하는 게 원칙이야? | Task Scheduler 금지, .ps1+Startup (메모리 근거 — 실제 규칙) | yes | no | |
| 15 | block | 2 | False | codex CLI에서 메모리 기록되나? | 네, ~/.codex/config.toml hooks 블록 (메모리 근거) | yes | no | |
| 16 | yes | 3 | False | ADR Final 이후에 뭐 하면 안 돼? | 신규 설계·ADR 금지 (메모리 근거 — 실제 규칙) | yes | no | |