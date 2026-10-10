# stage102p 중단 보관 기록 (2026-10-10 16:10)

## 상황
- 목적: 1,074건(소비자 QA 응답) 판정 — "사용자 특정 정보 인용 여부" 기준
- 모델: **tokenharbor/deepseek-v4.1-flash:free** (9router localhost:20128)
- 방식: 배치 5건/콜, **워커 2**, temperature 0.2
- 체크포인트: **135/1,074건 완료** (yes 116, no 19) → `data/stage102p_judge_deepseek.json`
- 로그: `stage102p_run.log`

## 실측
1. **tkh/deepseek-v4.1-flash:free → 404 "No active credentials for provider: tkh"** (사용 불가)
2. **tokenharbor/deepseek-v4.1-flash:free → 정상** (배치 5건, ~57초/콜 — tkh 대비 느리지만 안정적)
3. 25배치=135건/3.3분 = **~40건/분** → 전체 예상 ~27분
4. 판정 품질 우수: 사용자 고유 수치(10~25% 이탈률, 17/18, gemini-3.7-flash 등)를 정확히 근거로 인용
5. **파싱 주의**: 9router 응답에 `,"reasoning_content":"..."` + trailing `data: [DONE]` 붙음
   → `rfind('}')`로 잘라 json.loads 후 `choices[0].message.content` 접근 (stage102p 코드에 반영됨)
6. qwen3.8(Experlabs) 대비 503/429 없음 — 로컬 9router 경로가 안정적

## 재개 방법
```
cd experiments/operational-golden
"$LOCALAPPDATA/jev-mem/venv/Scripts/python.exe" stage102p_batch_judge_deepseek.py
```
→ 체크포인트(135건)에서 자동 이어서 판정

## 참고: qwen 체크포인트 (별개)
- `data/stage102o_judge_qwen.json` — 180건 (yes 163, no 17) — 503/429로 중단, 보류
- 상세: `data/STAGE102O_PAUSED.md`