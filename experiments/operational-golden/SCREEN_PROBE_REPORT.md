# Screen probe: hermes-jev-skills memory 메커니즘 실측 (2026-10-05)

비교 대상: `kerpopule/hermes-jev-skills` @ 0.22.1 — `jevkit/rerank.py`의 `local_screen` + `jevkit/privacy.py` (MIT). 우리 jev-mem과 학술 Jev-Mem(arXiv 2609.23986)은 별개 프로젝트임을 전제로, **저장소의 '읽기 경로 인젝션 스크린'과 'screening 신호'** 두 메커니즘을 우리 시스템에 적용할 가치가 있는지 0콜 오프라인 실측했다.

## 요약

| 메커니즘 | 판정 | 근거 |
|---|---|---|
| ① local_screen 직접 이식 | **기각** | 한국어 인젝션 catch **3%**(30종 중 1), 라이브 DB FP 4.06% 중 94%가 오탐 |
| ①' 한글 강화 스크린 | **검증 통과 → 채택** | 한국어 인젝션 **30/30 catch(100%)**, 라이브 DB FP **0/1796(0.00%)**, 단위 26/26 — FP<1% 목표 충족 |
| ② screening 신호 (unvetted 표시) | **채택 권고** | fail-open 23회에서 **미검증 passage가 풀째로 컨텍스트 진입** 실측 — 현재 무방비 |

## 실험 1 — DB 스크린 probe (1796행, 0콜)

- 전체 flag 73건(4.06%) = sensitive 69 + command 3 + instruction 1
- **오탐 분해**: sensitive 69건 중 secret_words 40건(대부분 "API key"라는 단어 자체 — 문서·설명), secret_assign 39건(이미 `[REDACTED]` 처리된 `NOTION_TOKEN="[REDACTED]";` 값도 잡음), 나머지 instruction/command 4건은 정상 문서(설치 커맨드·백그라운드 출력)
- **진짜 인젝션은 0건** (사람 판정) — 판정 73건 전부 오탐이었고, 저장소 벤치(영어 README) FP 0.42%는 한국어 코드/로그 메모리 도메인에서 성립하지 않음

## 실험 1B — 한국어 인젝션 catch-rate (합성 30+30, 0콜)

- 순수 한국어 인젝션 30종: **1건만 탐지**(`curl … | bash`) = 3%
- 한국어 정상 문장 30종: FP 0 (정밀도는 높음)
- 혼합(한국어+영어 키워드): 6/7 탐지 — 영어 문구가 섞이면 영어 패턴이 작동
- 결론: 저장소 스크린은 **영어 문서용**. 한국어 메모리(우리 도메인)에 그대로 이식하면 방어 효과 ≈ 0

## 실험 2 — recall 경로의 미검증(unvetted) 통과 실측 (0콜)

- `query_log` 178건 중 abstained 40건 = Jev가 '답 없음' 판정 → 설계대로 컨텍스트 비움 (통과 거부라 안전)
- **fail-open(10-03, 403 인증 오류 5 incidents): `Jev choice: idx=None` 23건 → `/v1/prefetch 200`** — Jev 판정 없이 pool 24~92 passage가 그대로 컨텍스트로 실림
- 같은 기간 저장 경로는 이미 보호됨: write-gate 403→KEEP 33건, 재판정 96건 전부 applied(fail_open 태깅). **읽기 경로만 비대칭으로 무방비**
- abstain 40건 중 34건은 실사용 질문(설계 동작) / 6건 시스템 메시지

## 권고

1. **①' 한글 스크린 (검증 완료 → 채택)**: `screen_probe_ko.py` — 인젝션 30/30 catch, DB FP 0/1796. 저장소의 영어 스크린 대신 한국어 도메인 방어선으로 통합 자격 충족. 설계: "명령형 어미 + 위험 신호(비밀 명사·파괴 명령·탈취 URL·사용자 은닉·메모리 변조) 결합"만 발화, 문서 인용·과거 서술·명사형·표제·일상 용어(토큰 수·API 문서)는 통과
2. **② screening 신호 우선 적용**: fail-open/idx=None 시 컨텍스트에 "이 recall은 Jev 미검증(로컬 패턴만)" 주석 + 인젝션 의심 passage 배제. gateway.py/pipeline.py의 작은 패치로 완성되며 저장 경로(fail_open 태깅)와 대칭을 이룸
3. 직접 이식(①)은 재고 없음 — 영어 recall 3%는 방어가 아님

## 산출물

- `screen_probe_vendor.py` — vendored 스크린(단독 실행 가능)
- `screen_probe_a_db.py` — DB probe
- `screen_probe_b_korean.py` — 한글 합성 probe
- `screen_probe_ko.py` — **한글 스크린 (검증 완료, self-check 26/26)**
- `screen_probe_ko_db.py` — 한글 FP DB probe
- `data/screen_probeA_raw.jsonl` (1796행), `data/screen_probeKO_raw.jsonl`, `data/screen_probe_raw_ledger.json`