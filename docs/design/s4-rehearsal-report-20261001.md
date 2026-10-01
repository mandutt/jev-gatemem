# S4 리허설 결과 보고 (2026-10-01, run-20261001-s4)

> 대상: `s4-embedding-migration-plan.md` v4 리허설 게이트. 복제 스냅샷(라이브 2026-10-01 15:35, `sha256 40087425…`)에서 실행. 라이브 DB 무접촉(assert로 경로 분리 검증).

## 종합 판정: 리허설 전체 게이트 PASS — live cutover 승인 요청 가능 상태

| 리허설 항목 | 결과 | 실측치 |
|---|---|---|
| R1 preflight (orphan ID + planned 카운트) | ✅ | orphan **7 ID 확정** / planned **working 1,146 + episodic 113 = 1,259행** |
| R2 배치 불변성 (20행 × 배치 1/4/16) | ✅ | min_cos = **1.0** (S2 실측 재현) |
| R3 전량 reindex 벽시계 | ✅ | **33.8s / 24.8s** (2회 실측, batch 4 + clamp 512) |
| R3 completeness | ✅ | working 1,146/1,146, episodic 113/113, integrity ok |
| R4 failure injection → 부분 상태 → 백업 복원 원복 | ✅ | vec_working 1,146→**12**, vec_episodes **0** (부분 상태 실증) → 복원 후 해시까지 **완전 원복** |
| R5 동일 데이터 MiniLM vs a8m (200행, paired bootstrap 10k) | ✅ | a8m MRR **0.811** vs MiniLM **0.582** — Δ **+0.229**, 95% CI **[0.176, 0.283]** |
| R6 L1 completeness validator | ✅ | 전 항목 통과 (아래 게이트 기준 수정 1건) |
| R6 L2 S3 벡터 일치 | ✅ | 동일 텍스트 코사인 **1.0** (fp32 JSON 저장소) |

## 리허설이 확정한 설계 사실

1. **창 시간 재확정**: 리허설 24.8~33.8s — S3의 278.9s보다 훨씬 빠름(웜 캐시·무부하 환경). **live 창은 보수적으로 리허설 실측 ×여유계수(예: ×4) + 백업/검증 시간으로 5~8분 유지** — 환경 차이(데몬 정지 직후 콜드 캐시, 동시 부하)를 감안해도 넉넉. "40초~2분" 가정은 실제로 근접했으나, 이는 우연이 아니라 실측으로만 성립.
2. **P0-B 확정**: `reindex_vectors()` 실패 시 부분 상태 잔존을 실측으로 증명(vec0 테이블 12/0행). **백업 복원 = 유일한 recovery boundary** — R4에서 1커맨드 복원 + 해시 일치 원복 확인.
3. **P0-C 확정**: reindex 후에도 orphan 7건 잔존 실측 → live cutover 절차의 명시 삭제 단계 필수 확인.
4. **P0-D 확정**: dry-run planned 카운트(1,259)가 문서 가정(1,251)과 달랐고, R6 validator가 이 차이를 정확히 잡음 — 외부 validator 필수 설계 검증.
5. **P1-F 확정**: 배치 불변성(1/4/16 min_cos 1.0) — 배치 4 재인덱스와 라이브 배치 1 쓰기의 공간 일치.

## 리허설에서 발견한 설계 수정 필요 (v4에 반영 완료해야 함)

- **[게이트 기준 수정] int8 표본 대조 코사인 게이트**: 기존 "코사인 ≥ 0.999"는 fp32 비교 기준. `vec_quantize_int8('unit')` roundtrip의 노이즈 바닥값이 **실측 ≈0.9958**이므로, int8 저장소(vec_working/vec_episodes) 표본 대조 게이트는 **≥ 0.995**로. fp32 JSON(`memory_embeddings.embedding_json`) 대조는 ≥ 0.999 유지. → v4 §7 기동 가드 ④에 반영.
- **[절차 주의] 백업 복원 시 연결 해제**: Windows에서 `mnemosyne.core.memory`와 `mnemosyne.core.beam`이 **각각** thread-local conn을 홀드 — 복원 전 두 모듈의 conn을 모두 close해야 `-wal` 삭제 가능(WinError 32 실측). `rollback_s4.py`에 반영.
- **[절차 주의] R4류 복원은 "리허설 내 이전 상태"를 덮는다** — failure injection 테스트는 반드시 프리스틴 스냅샷에서 시작할 것(부분 상태 잔류 시 가짜 PASS 위험. 실제로 1차 실행에서 이 함정을 걸림).

## 산출물

- `run-20261001-s4/`: `r1_preflight.json` / `r2_batch_invariance.json` / `r3_reindex_result.json` / `r4_rollback_result.json` / `r5_same_data_comparison.json` / `r6_gates_result.json` + 각 로그
- 라이브 DB 무변경 확인: 스냅샷 후 라이브 미접촉
