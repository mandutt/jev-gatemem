# STAGE97 — trace 일별 로테이션 (2026-10-07, b-ai F#4)

## 요약

**JEV trace(512KB 링버퍼 → 일별 파일 로테이션 + 30일 보관) 적용. 데몬 재시작 완료.**

## 배경

- b-ai v6 F#4: "trace를 일별 파일로 회전하고 보관 기간을 늘리세요. canary와 별개로 필요합니다."
- 문제: `gateway/trace.py`가 512KB 링버퍼 — 꽉 차면 **오래된 로그가 영구 소실** (10-06 데이터가 이미 소실, 시계열 분석 구조적 불가)

## 구현 (gateway/trace.py)

1. **일별 로테이션**: `jev_trace.log` → **`jev_trace_YYYYMMDD.log`** (미들웨어가 쓰는 파일만 — Hermes 코어 무수정)
2. **보관 정리**: `JEV_TRACE_RETENTION_DAYS` (기본 30일) 초과 파일 자동 삭제 — trim 발생 시 1회 실행
3. **`JEV_TRACE_PATH` 환경변수 우선** 유지 (기존 커스텀 경로 호환)
4. **디렉토리 자동 생성** 추가 (부재 시 trace 조용히 실패하던 문제)

## 마이그레이션

- 기존 `jev_trace.log` (508KB, 10-07 데이터) → `jev_trace_20261007.log`로 append 병합

## 검증

- [x] 단위 테스트: 날짜 경로 resolve · 기록 · cap 초과 trim · 오래된 파일 cleanup (전부 통과)
- [x] 실데이터: 데몬 재시작(30296/30504) 후 smoke 이벤트가 새 파일에 기록 확인 (20:53:00)
- [x] 옛 `jev_trace.log` 재생성 없음 — 새 경로 적용 확정

## 주의

- **데몬 재시작 필요** (trace.py를 이미 import한 프로세스는 새 경로를 못 봄) — 2026-10-07 재시작 완료
- 기존 분석 스크립트/스킬의 `jev_trace.log` 경로 하드코딩은 날짜 파일로 수정 필요 (e.g. stage96 파서)
- 512KB 링버퍼 자체는 유지 (일별 파일 안에서 cap 발동 시 head trim) — 하루치가 512KB를 넘는 일은 드묾

## 파일

- 수정: `gateway/trace.py`
- 로그: `%LOCALAPPDATA%/hermes/logs/jev_trace_YYYYMMDD.log`