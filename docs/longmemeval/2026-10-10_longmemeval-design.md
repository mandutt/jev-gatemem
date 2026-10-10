# LongMemEval-S on jev-mem — 설계안 (승인 대기)

> 작성: 2026-10-10 · 상태: **설계안 — 구현 전 사용자 승인 필요**
> 메모리 솔루션 벤치 마이그레이션: MemConflict(비현실적: 14만 콜/12일) → LongMemEval-S(500문항, JEV read-path 1콜/문항)

## 1. 배경 (사용자 요구)

MemConflict 벤치(`hermes-memconflict`)는 30 personas · 142,093 대화 턴 · 3,750 질문이고, write gate까지 JEV 적용 시 턴당 1콜 = **142,093콜 ≈ 570M 토큰**으로 무료 한도(일일 47.6M 토큰×키) 대비 불가능. read-path만 해도 3,750콜. GPU(vLLM 2대) 요구까지 겹쳐 **비현실적 판정**.

사용자 승인으로 LongMemEval-S(ICLR 2025, mem0/Zep/Letta 등 공식 사용)로 전환.

## 2. 데이터 실측 (longmemeval_s_cleaned.json, 2026-10-10 다운로드)

| 지표 | 실측값 |
|---|---|
| 문항 수 | 500 |
| question_type 분포 | single-session-user 70 / multi-session 133 / single-session-preference 30 / temporal-reasoning 133 / knowledge-update 78 / single-session-assistant 56 |
| abstention(_abs) | **30문항** |
| haystack sessions/instance | median 48 (min 38, max 62) |
| 대화 턴/instance | median 491 (max 616) |
| 텍스트(문자)/instance | median ~490K chars |
| evidence sessions/instance | median 2 (max 6) |
| **전체 ingest 턴 (500문항 합계)** | **246,750** |

- oracle 파일(`longmemeval_oracle.json`): evidence 세션만 포함 (median 2 세션) — **상한/레버 확인용**
- 공식 평가: `evaluate_qa.py` = LLM judge가 yes/no 1콜/문항 (OpenAI API 호환 → `deepcombo`/로컬 엔드포인트로 대체 가능)

## 3. Scope (이번 구현이 하는 것)

1. **JEV read-path 어댑터** `bench/longmemeval/stage110_lmev_adapter.py`:
   - 문항별 haystack 세션 전부를 JEV 메모리 DB에 ingest (0콜)
   - 문항 질문마다 `run_choice` JEV 판정 1콜 → 상위 K개 메모리 top-k 노출
   - 응답 생성은 소비 LLM(deepcombo, 로컬 무료) 1콜
2. **공정성**: 어댑터는 벤치 데이터만 쓰고, 원본 파일 수정 없음
3. **채점**: `evaluate_qa.py` prompt 방식 동일하되 judge LLM을 로컬 deepcombo로 교체 (OPENAI_BASE_URL 환경변수 방식 유지)
4. **결과 artifact**: Results JSONL + 요약 (전체/타입별/abstention 정확도)

**범위 밖 (하지 않는 것)**: write gate 적용, 데몬/프로덕션 코드 변경, Docker/vLLM.

## 3-1. 데이터 격리 보장 (라이브 데몬 무영향 — 코드 검증 2026-10-10)

| 경로 | 러너 동작 |
|---|---|
| `%LOCALAPPDATA%\jev-mem\mnemosyne.db` (라이브) | **읽지도 쓰지도 않음** — 접근 코드 없음 |
| 임시 DB (문항별) | `tempfile.mkdtemp()` 새 파일 생성 → ingest → 종료 시 폐기 |
| 데몬 프로세스 (`jev_mem_core --serve`) | kill/restart 없음 |
| `core.json`·`config.yaml`·HKCU 키·환경변수 | 수정 없음 |
| JEV API | HTTP POST 만 (외부 요청, 로컬 상태 무변경) |
| 라이브 무료 할당 | 500콜 ≈ 일일 한도 2% — 데몬 운영에 영향 없음 |

## 4. JEV 콜 예산 (reader = 로컬 무료, JEV만 과금)

<details><summary>키 정책 (2026-10-10 사용자 지시 — Typesafe 제외, EXPLABS 2키)</summary>

- **`TYPESAFE_API_KEY`(apikey_)는 절대 사용 금지** — 무료 경로가 아님 (과금 대상).
- **`EXPLABS_API_KEY`(xpl_...c1b3) + `EXPLABS_API_KEY2`(xpl_...0b12)** 2키만 사용 — `jev_mem_core/keyring.py::SmartRotator`로 로드 (레지스트리 HKCU\Environment가 소스), 429 시 자동 키 전환.
- 러너 시작부에서 활성 키 로드 후 `assert keys` + 401 분기(키 무효화 감지 시 중단) 포함.
- 데몬 프로세스 kill/재시작 없이 러너 프로세스 내부에서만 키 사용.

</details>

- **JEV 콜: 500문항 × 1콜 = 500콜**
- JEV 토큰: 실측 k60 평균 4,021 tokens/콜 → **~2.0M 토큰 (500콜)** = EXPLABS 2키 일일 무료 한도(95.2M 토큰)의 **~2.1%**
- 시간당 한도: 2키 = 480콜/시간 → 연속 실행 시 ~**1.5~2시간**
- reader(deepcombo)/judge: 로컬 무료 → JEV 토큰만 소진

## 5. DoD (완료 정의)

- [ ] 500문항 JEV read-path 완주 (결과 JSONL 존재: 500행)
- [ ] question_type별 + abstention(30) + 전체 정확도 보고
- [ ] JEV 콜 사용량(토큰) ledger
- [ ] 결과 요약 텔레그램 전송 (사용자 관례)
- [ ] raw JSON + 러너 + 문서 repo 커밋·푸시 (jev-memory-middleware)

## 6. Public API (제안)

```
python stage110_lmev_adapter.py \
  --ref data/longmemeval_s_cleaned.json \
  --out results/stage110_lmev_results.jsonl \
  --jev-k 5 --top-k 5 \
  [--limit N]  # 스모크용 부분 실행
```

후속 (별도 승인): oracle 상한 측정, MemoryAgentBench/기타 벤치 전환.

## 7. 리스크 & 대응

| 리스크 | 대응 |
|---|---|
| 500문항 × 246,750턴 ingest 시간 | 1문항 당 평균 491턴 — SQLite WAL+fast pragma, 병렬 4~8 프로세스 |
| judge LLM 품질 (deepcombo) | 공식 prompt 유지, temperature 0, 3회 재실행 판정 (비결정성 대응) |
| JEV 시간당 한도 (480/시간 2키) | 500콜이므로 키 2개로 소화 가능, 스모크로 latency 사전 확인 |
| abstention 30문항 | JEV abstain 신호와 별개로 채점은 응답 기준 — 회귀 지표로 활용 |

## 8. 실행 순서 (승인 후)

1. 스모크: 3문항(타입 대표) ingest+JEV+reader → JEV 키 확인
2. 전체 500문항 (병렬, 배치)
3. judge 채점 (deepcombo, 500콜)
4. 요약·커밋·푸시·텔레그램 요약