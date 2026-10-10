# STAGE106 — jev-mem 데몬 부재 사고 + 복구 (2026-10-10)

## 사고 개요
- **기간**: 2026-10-09 12:05 ~ 2026-10-10 17:46 — 표면상 30시간
  - **★정밀 실측 (2026-10-10, v8 3-AI 검토 대응)**: trace 파일 대조로 실제 부재 구간은
    **10-09 11:47(마지막 trace) ~ 10-10 00:51(첫 trace) = 약 13시간**.
    10-10 00:51부터는 데몬이 동작(LongMemEval 실행이 trace에 남음) — "30h 전체 다운"은 과대였고
    **13h 다운 + 17h 부분 동작(게이트웨이 tools python 상태로 rerank만 부재)**으로 정정
- **영향**: JEV rerank 없는 운영 (메모리 검색은 게이트 통과 순서 fallback), query_log·shadow_log 기록 중단
- **발견 경로**: shadow 배치 점검 (STAGE105) 중 shadow_log가 10-09 11:47 이후 안 쌓임 → 원인 추적

## 사고 원인 (근본)
1. **10-09 12:05:30** — Hermes 설치/업데이트 프로세스가 `Hermes_Gateway.cmd`/`.vbs`를 **tools python(3.14.7) 경로로 재생성**
2. tools python엔 `mnemosyne_hermes` 미설치 → jev-mem 플러그인(`plugins/jev-mem/__init__.py` → `harnesses/hermes_j1.py`)의
   `from mnemosyne_hermes import MnemosyneMemoryProvider` **ImportError**
3. → "Memory provider 'jev-mem' loaded but no provider instance found" (agent.log 반복)
4. → provider 인스턴스 미생성 → **JevMemClient auto_start 발동 기회 자체가 없음**
5. 10-09 12:07 PC 종료(데몬 사망) + 10-10 10:14 재부팅 후에도 게이트웨이가 tools python으로 떠서 동일 상태 지속

## 설계 의도와의 관계
- 설계 방향: "Hermes에 의존하지 않고 **플러그인 레벨에서 데몬 auto-start**" (`JevMemClient("hermes", auto_start=True, spool=True)`) — 올바르게 구현돼 있었고, **provider가 로드만 되면** 17.1초 내 자동 기동 실측 성공
- 깨진 것은 auto_start가 아니라 **provider 로드 환경** (게이트웨이 python)

## 수정 (1+3 병행)
### 3번: 플러그인 보강 (영구 방어선) — `harnesses/hermes_j1.py`
- `_ensure_mnemosyne_hermes()` 추가: mnemosyne_hermes import 실패 시
  `%LOCALAPPDATA%/hermes/installs/*/environments/*/venv/Lib/site-packages`를 glob로 탐색,
  mnemosyne_hermes 있는 venv를 sys.path에 추가 후 재import
- venv hash가 업데이트로 바뀌어도 **최신 venv 자동 추적**
- 검증: tools python 3.14.7에서 `hermes_j1` 로드 OK → `JevRpcProvider` 생성 OK → auto_start=True

### 1번: 게이트웨이 실행 파일 수정 (즉시 복구) — `Hermes_Gateway.cmd`/`.vbs`
- python 경로: tools python → **Hermes 정식 venv** (`installs/315db7b763fb0d0a/environments/099e00aba7aa4e9494cf6ab86490e67a/venv`)
- VIRTUAL_ENV도 동일 venv로
- 백업: `Hermes_Gateway.cmd.bak-20261010` / `Hermes_Gateway.vbs.bak-20261010`
- ⚠️ Hermes 업데이트가 이 파일을 다시 덮어쓸 수 있음 → 그 경우 3번 폴백이 커버

## 검증 (실증)
| 시각 | 증거 |
|---|---|
| 18:19 | 게이트웨이 재기동 — **venv python** (PID 17228) |
| 18:31:47 | `Memory provider 'jev-mem' activated` (agent.log) |
| 18:31:49 | 이 대화 "확인했어?"가 **query_log 643건으로 기록** → 데몬 경유 동작 확인 |
| 18:3x | 데몬 LISTENING(47821), health 응답 |

## 쓰기 경로 유실 확인 (2026-10-10, v8 3-AI(b) 지적 대응)
- **질문**: 데몬 부재 동안(10-09 12:05 ~ 10-10 00:51) 메모리 쓰기(sync_turn)가 유실됐는가?
- **실측** (mnemosyne.db working_memory timestamp 대조):
  - 부재 구간(10-09 12:05 ~ 10-10 00:51): **11건 기록** — 데몬 부재 중에도 일부 경유로 저장됨
  - 재기동~복구 사이(10-10 00:51 ~ 17:46): **0건** — 이 구간은 게이트웨이 tools python 상태로 provider 미생성 → 쓰기 없음
  - 복구 후(10-10 17:46 ~): 36건 — 정상
- **결론**: 전체 30h 중 첫 13h(부재)는 11건 저장, 이후 17h(부분 동작)는 0건 — **단기 세션 대화가 일부 유실됐을 수 있으나 대량 유실 아님**. 백필은 불필요로 판정 (지난 세션 대화는 Hermes 채팅에 원문 보존)
- **교훈**: provider 미생성 상태에서는 쓰기·읽기 모두 무해하게 실패(fail-open) — "JEV rerank 없는 운영"은 실제로 "메모리 경로 전체 부재"였음

## 후속
- shadow 배치 존속 여부는 별도 판단 (STAGE105 결론: enforcement 불필요, gate 정상 → shadow_log 축적 가치 소진 검토 중)
- canary drift(10-09/10 L1 abstain 12건)는 별개 이슈로 추적 중