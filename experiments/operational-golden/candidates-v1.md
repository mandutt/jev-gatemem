# Hermes 운영 평가셋 (Golden Set) — 쿼리 작성용 후보 목록 v1
# 2026-10-01 / 라이브 DB working_memory에서 추출, 중복 제거 후 60건
# 사용자 검토 후 쿼리를 작성할 수 있게 상세 내용 포함

## 사용법
각 항목에 대해 아래 형식으로 쿼리를 작성해주세요:
- query: 사용자가 실제로 묻는 자연어 질문 (의역 변형 포함 가능)
- primary: 반드시 회수되어야 할 Primary 메모리 id (또는 content 일부)
- acceptable: 그 외 허용 가능한 메모리 id (다중 정답)
- failure_axis: 의역(paraphrase) / 갱신(contradiction) / 무답(no-answer) / 일반(factual)
- notes: 특이사항

---

## A. 환경/설정 팩트 (10건)

### A1. camelAI auto 라우팅 (id=618362fc6d33e3c1)
**내용**: 92호출 실측 — 어려운 과제→gemini-3.7-flash 17/18(94%), 사소한 마무리→me... (전문 golden_deduped.json)
**예시 쿼리**: "camelAI auto 모드에서 어려운 과제는 어떤 모델로 라우팅돼?"

### A2. camelAI auto 라우팅 플립 트리거 기각 (id=c66472eaa13fd3dc)
**내용**: 08-25 패딩 토큰 전환 관측 → 08-26 92호출 미재현으로 부분 기각
**예시 쿼리**: "라우팅이 패딩 토큰 수에 따라 바뀐다는 결론 나왔었나?"

### A3. web_extract 키리스 (id=9d4feaccfa1020b4)
**내용**: v0.20.4+ plugins/web/keyless_mcp.py, web.keyless_fallback=true
**예시 쿼리**: "web_extract를 API 키 없이 쓰려면?"

### A4. camelAI 입력토큰 지연 (id=a112c8b5932fbc1f)
**예시 쿼리**: "입력 토큰 늘면 TTFT 얼마나 늘어?"

### A5. camelAI 스트리밍 속도 (id=26efd95898ed8fcb)
**예시 쿼리**: "가장 빠른 디코딩 모델이 뭐였지?"

### A6. camelAI effort=max (id=098d90e014006142)
**예시 쿼리**: "luna에 effort max 넣으면 어떻게 되지?"

### A7. camelAI auto 라우팅 확률성 (id=e481f1a2bb8f7969)
**예시 쿼리**: "같은 프롬프트 반복하면 라우팅 고정돼?"

### A8. Hermes 18080 프로바이더 설정 (id=b2ed9f4dc0b1efea)
**예시 쿼리**: "config.yaml에서 18080 프록시 어떻게 등록해?"

### A9. camelAI 별칭 오류 (id=7de2c1dfef632694)
**예시 쿼리**: "gemini-3.7-flash 별칭으로 호출하면 되나?"

### A10. camelai-serial-proxy 모델 스위치 (id=e5bbd0063f1356f6)
**예시 쿼리**: "프록시에서 모델 강제 스위치 기능 있어?"

---

## B. 디버깅/인과 (4건)

### B1. 코덱스 성능 저하 원인 (id=ef3d9670463aea79)
**예시 쿼리**: "코덱스 앱이 PC 느려지게 만든 원인 뭐였어?"

### B2-B4. codex 세션 반복 (id=0192afce46680d1c, 502789473c8a32c5, 28743a98aac79817)
**내용**: testproject Technical Lead 지시, test-a/worker-a 세션 (반복 기록이라 골든셋 부적합할 수 있음)

---

## C. 선호/지침 (18건)

### C1. 존댓말 통일 (id=d1c90516d9870c95)
**예시 쿼리**: "한국어 말투 규칙이 뭐지?"

### C2. 작업 스케줄러 금지 (id=2ecef73164830638)
**예시 쿼리**: "작업 스케줄러 건드려도 돼?"

### C3. ADR Final 후 금지 (id=9f04ed2c8e14f11b)
**예시 쿼리**: "설계 확정 후에 리팩터 해도 되나?"

### C4. 감사 산출물 형식 (id=a13019e1f438960c)
**예시 쿼리**: "감사 보고서 어떤 형식으로?"

### C5. Commit governance (id=9150f1246613b092)
**예시 쿼리**: "리뷰 전용 턴에서 커밋해도 돼?"

### C6. 설계 리뷰 우선순위 (id=5a3ebc06a87940da)
**예시 쿼리**: "SOLID vs 일관성 뭐 우선?"

### C7. Evidence-based (id=c9e4828c93bdb0a0)
**예시 쿼리**: "구현됐다고 믿기 전에 뭘 확인해야 해?"

### C8. 한영 혼용 (id=a68b370287d1892f)
**예시 쿼리**: "사용자 언어 습관?"

### C9. 아키텍처 선호 (id=1cef4743165b7707)
**예시 쿼리**: "영속성과 비즈니스 로직 분리해?"

### C10. verifier-pilot 목표 (id=f2421b7b489858bb)
**예시 쿼리**: "verifier-pilot 프로젝트 진짜 목표가 뭐지?"

### C11. skill_manage content 파라미터 (id=e6b3887395a2ac45)
**예시 쿼리**: "스킬 만들 때 content 넣어야 해?"

### C12. opencode Mnemosyne 플러그인 (id=e941022a685c2be1)
**예시 쿼리**: "opencode에서 메모리 자동 기록되나?"

### C13. commitment FP 필터 (id=498bb204de3b1d14)
**예시 쿼리**: "commitment-fp-v4 필터 관측 결과?"

### C14. cua-driver 660s 타임아웃 (id=c69c459c7c67c2d1)
**예시 쿼리**: "hermes update 후 cua-driver 왜 실패해?"

### C15. start_proxy.cmd 인코딩 (id=ac6b11080109c3fe)
**예시 쿼리**: "start_proxy.cmd 재부팅 후 왜 안 돌아가?"

### C16. camelai-serial-proxy 대시보드 (id=efb4e9a38f6ee270)
**예시 쿼리**: "프록시 대시보드 종료 버튼 있어?"

### C17. 게이트웨이 워치독 (id=36f843b4b1886e39)
**예시 쿼리**: "Hermes 데스크톱 워치독 런처 위치?"

### C18. serve 백엔드 회귀 (id=b5f5672a2446d4e8)
**예시 쿼리**: "데스크톱 앱 띄우면 텔레그램 수신 왜 끊겨?"

---

## D. 한-영 교차 (9건)

### D1. KoDialogBench X1 검증 (id=d28786a095ace1ae)
**예시 쿼리**: "KodialogBench response selection 결과 어땠어?"

### D2-D9. codex 세션/대화 로그 — 반복·대화형이라 골든셋 부적합 가능

---

## E. 지식 팩트 (19건)

### E1. verifier-pilot 67차 (id=2f199c68ab243ff8)
**예시 쿼리**: "best-of-5에 selective recovery 얹으면 개선돼?"

### E2. Codex CLI↔Mnemosyne 연동 (id=90b4edf612db6b2c)
**예시 쿼리**: "codex에서 메모리 기록 되나?"

### E3. 임베딩 벤치 P3b (id=509622f2ecaf7c06)
**예시 쿼리**: "bekko vs koen 벤치 결과?"

### E4. 임베딩 벤치 S3 (id=7a3675ebfc5a1829)
**예시 쿼리**: "S3에서 bekko-a8m 채택 이유?"

### E5. 언어 규칙 builtin (id=2ff550d144b5ae03)
**예시 쿼리**: "code와 structural 답변 언어?"

### E6. browser 라우팅 설정 (id=1928d454e0ed168b)
**예시 쿼리**: "CAMOFOX_URL 왜 제거했지?"

### E7. pi coding agent models.json (id=f9d466b9cdc3cd88)
**예시 쿼리**: "pi에 등록된 프록시 목록?"

### E8. 브라우저 stealth 판단 기준 (id=09547ea49fc36991)
**예시 쿼리**: "stealth 브라우저 언제 써야 해?"

### E9. 메모리 provider (id=ed3a3442d3bcbb33)
**예시 쿼리**: "메모리 백엔드 뭐 쓰고 있지?"

### E10. hermes update 중단 복구 (id=dce5e8ceddf18db9)
**예시 쿼리**: "hermes update 중간에 꺼지면?"

### E11. 18080 S8 장문 (id=edf486fa0d3cd079)
**예시 쿼리**: "deepseek 장문 스트림에서 뭐가 문제였지?"

### E12-E15. StateM 반복 (4건, id=3581b9a33901eba4 / 19bed46211f6ffcb / 0a13cf1002bffc4c / 766fd80090690684)
**예시 쿼리**: "statem controller 버전 뭐였어?"

### E16. 웹 수집 tavily (id=0ea67a3b101917e5)
**예시 쿼리**: "웹 추출 백엔드 뭘로 설정했지?"

### E17. camelai-serial-proxy 개요 (id=5e8516d6f91b46dd)
**예시 쿼리**: "18080 프록시가 뭐하는 거야?"

### E18. supermemory 전환 사유 (id=132fb95d922f9bc5)
**예시 쿼리**: "supermemory 왜 안 써?"

---

## 다음 단계
사용자가 각 항목에 쿼리를 확정하면 (또는 자동 생성 + 사용자 승인) `golden_queries.json`으로 저장하고
평가 스크립트를 실행합니다.