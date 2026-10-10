# stage102o 중단 보관 기록 (2026-10-10 15:50)

## 상황
- 목적: 1,074건(소비자 QA 응답) 판정 — "사용자 특정 정보 인용 여부" 기준
- 모델: **qwen3.8-flash-next-uncensored** (Experlabs OpenAI 호환 API)
- 방식: 배치 5건/콜, 1워커, 키1↔키2 전환, 429/503 재시도
- 체크포인트: **180/1,074건 완료** (yes 163, no 17) → `data/stage102o_judge_qwen.json`

## 핵심 실측
1. **단독/소규모 호출은 정상** (13~73초, content 정상 JSON 반환, finish=stop)
2. **배치 5건(실제 데이터)도 성공했음** (72.8초, JSON 배열 정상)
3. 그러나 러너 연속 실행 시 **429(capacity) + 503(provider 헤더 지연)** 반복 → 실질적 진전 없음
4. **503 "provider did not send response headers in time"** = Experlabs ↔ 상위 모델 공급자 간 지연 (클라이언트 문제 아님)
5. max_tokens **지정 시** reasoning이 한도까지 늘어나 느려짐(110s↑) / **생략 시** 필요한 만큼만 생성(13.7s) — 생략이 정답
6. 4워커/3워커 병렬은 429만 악화 → 1워커 확정

## 코드 상태
- `stage102o_batch_judge_qwen.py`: 배치 5, WORKERS=1, MAX_TOKENS=None(생략), 키2 우선 + 429 시 키 전환
- 로그: `stage102o_run*.log` (run1~12)

## 재개 방법
```
cd experiments/operational-golden
"$LOCALAPPDATA/jev-mem/venv/Scripts/python.exe" stage102o_batch_judge_qwen.py
```
→ 체크포인트(180건)에서 자동 이어서 판정

## 다른 모델 후보 (실험 필요)
- Experlabs의 다른 모델 (qwen3.8-flash? → 429 model_requires_purchase 확인됨)
- space-bunny (opencode zen — 403/FreeTierError 이슈 있었음)
- JEV(SystemOne): 메모리 경로 전용 (판정에는 미사용 원칙)