# A choice 주입 건 3분류 수동 판정 (43건)

> 생성: 2026-10-04 · 대상: LGO 37건 + fresh noans 6건 (exp7b2/exp7d에서 A choice가 선택한 건)
> b AI 프로토콜: 조건(exp7b2/exp7d)을 가린 채 판정. 3분류:
> - **VALID** = 대체 증거로 유효 (gold 행 제거 후에도 실제 답을 담는 다른 메모리)
> - **PLAUS** = 그럴듯하지만 틀림 (해로운 오주입)
> - **IRREL** = 무관 (주제도 다른 엉뚱한 메모리)
>
> **판정 방법**: 아래 각 항목의 [질문]과 [선택된 메모리]만 보고, 옆에 `VALID` / `PLAUS` / `IRREL` 중 하나를 기록
> **해로운 오주입률** = PLAUS / 전체. LGO와 noans를 따로 산출.

---

### 1. [LGO] 618362fc6d33e3c1
- **질문**: camelAI auto 라우팅에서 어려운 과제는 어떤 모델로 보내졌어?
- **선택된 메모리**: [2026-08-26 재검증으로 부분 기각] camelAI auto 라우팅 플립 트리거(08-25, 24호출): 당일엔 패딩 ~242~296토큰
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 2. [LGO] 9d4feaccfa1020b4
- **질문**: web_extract API 키 없이 쓸 수 있어?
- **선택된 메모리**: 웹 수집·추출: web.extract_backend=tavily(키리스, v0.20.4+, 2026-08-21 설정) — ddgs 검색+키 없이
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 3. [LGO] 9d4feaccfa1020b4
- **질문**: 키리스 웹 추출 설정 어떻게 돼 있지?
- **선택된 메모리**: 웹 수집·추출: web.extract_backend=tavily(키리스, v0.20.4+, 2026-08-21 설정) — ddgs 검색+키 없이
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 4. [LGO] a112c8b5932fbc1f
- **질문**: 입력 토큰 늘어나면 응답 지연도 늘어?
- **선택된 메모리**: [USER] 커뮤니티에서 인풋토큰이 많을 때 지연이 꽤 늘어난다는 이야기를 들었어. 그리고 high, xhigh, max별로도 다르다는 이야기를
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 5. [LGO] a112c8b5932fbc1f
- **질문**: TTFT가 입력 길이에 영향 받아?
- **선택된 메모리**: [USER] 커뮤니티에서 인풋토큰이 많을 때 지연이 꽤 늘어난다는 이야기를 들었어. 그리고 high, xhigh, max별로도 다르다는 이야기를
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 6. [LGO] 098d90e014006142
- **질문**: max 추론 레벨 미지원 모델 어떻게 처리돼?
- **선택된 메모리**: [USER] deepcombo의 ox alpha 모델은 추론레벨 low high max가 가능한걸로 알고 있는데, pi에선 max레벨이 설정 불
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 7. [LGO] e481f1a2bb8f7969
- **질문**: 같은 프롬프트 여러 번 보내면 라우팅 고정돼?
- **선택된 메모리**: [2026-08-26 재검증으로 부분 기각] camelAI auto 라우팅 플립 트리거(08-25, 24호출): 당일엔 패딩 ~242~296토큰
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 8. [LGO] e481f1a2bb8f7969
- **질문**: auto 라우팅이 확률적이라는 결론이었나?
- **선택된 메모리**: [USER] auto 모델 세팅에서 여러번 호출해서 모델이 변동되는지 확인해보고 싶은데 가능할까? 짧은 응답과 긴 추론별로도 응답 모델이 달라지
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 9. [LGO] e5bbd0063f1356f6
- **질문**: 프록시에서 특정 모델 강제 지정 기능 있어?
- **선택된 메모리**: [USER] 프록시 model_override로 제미나이를 고정하는 게 가능해? 안 되지 않아?
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 10. [LGO] d1c90516d9870c95
- **질문**: 한국어 말투 규칙 뭐지?
- **선택된 메모리**: 언어: 한국어/영어 혼용. Structural/metadata(분류·상태·step label)는 한국어, code/기술 설명은 영어. 완전 번역
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 11. [LGO] d1c90516d9870c95
- **질문**: 반말 써도 돼?
- **선택된 메모리**: [USER] 지금 네 한국어 말투가 반말과 존댓말이 섞여서 조금 이상해. 존댓말로 통일해 줘. 헤르메스 메모리도 이 부분을 기억하는 게 좋을 것
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 12. [LGO] 2ecef73164830638
- **질문**: 자동 시작 설정 어떻게 하는 게 원칙이야?
- **선택된 메모리**: [USER] 자동 시작 방식은 이 프록시를 시작프로그램에 등록하는 형태로 하는 건 어떨까? 그리고 카멜 ai api의 큐 헤더가 이 프록시의 작
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 13. [LGO] 9f04ed2c8e14f11b
- **질문**: 설계 확정 후 리팩터 제안해도 돼?
- **선택된 메모리**: 설계 리뷰: SRP/YAGNI/순수함수 원칙 기반 구체 검토, 코드 근거 필수. 일관성(기존 관례)을 SOLID보다 최우선 — 신규 타입 생성은
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 14. [LGO] a68b370287d1892f
- **질문**: 사용자 언어 습관이 어때?
- **선택된 메모리**: default 프로필에서만: 사용자는 Hermes가 한국어로 대화할 때 존댓말(합니다체)로 말투를 통일하기를 원함. 반말과 존댓말이 섞인 혼용은
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 15. [LGO] a68b370287d1892f
- **질문**: 한국어 영어 어떻게 섞어 써?
- **선택된 메모리**: 언어: 한국어/영어 혼용. Structural/metadata(분류·상태·step label)는 한국어, code/기술 설명은 영어. 완전 번역
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 16. [LGO] 1cef4743165b7707
- **질문**: 아키텍처 설계 시 분리 원칙이 뭐였지?
- **선택된 메모리**: 설계 리뷰: SRP/YAGNI/순수함수 원칙 기반 구체 검토, 코드 근거 필수. 일관성(기존 관례)을 SOLID보다 최우선 — 신규 타입 생성은
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 17. [LGO] f2421b7b489858bb
- **질문**: verifier-pilot은 코딩 품질만 보면 돼?
- **선택된 메모리**: [USER] 지적하고 싶은 게 있어. 내 목표는 "코딩 품질" 향상이 아니라, "더 나은 답변 품질"이야. 코딩에 한정되지 않아. 따라서 코딩에
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 18. [LGO] e941022a685c2be1
- **질문**: opencode에서 메모리 자동 기록돼?
- **선택된 메모리**: [opencode session] task: 현재 므네모슈네 메모리 플러그인에 자동으로 저장하는 게 정상적으로 작동 중인지 확인해줘 projec
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 19. [LGO] c69c459c7c67c2d1
- **질문**: hermes update 후 cua-driver 왜 실패해?
- **선택된 메모리**: [USER] 헤르메스 업데이트가 끝나고 나면 cua driver를 refresh 하는데, 문제는 자꾸 그 과정에서 타임아웃이 걸려. 이번이 두
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 20. [LGO] ac6b11080109c3fe
- **질문**: start_proxy.cmd 재부팅 후 왜 안 돌아가?
- **선택된 메모리**: [USER] 재부팅 후에 8780 프록시가 또 작동하지 않아. start_proxy.cmd 실행해도 반응이 없는데 왜 이러지? 확실하게 원인을
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 21. [LGO] efb4e9a38f6ee270
- **질문**: 프록시 대시보드에 종료 버튼 있어?
- **선택된 메모리**: [USER] 수정할 사항이 있어. 1. 대시보드 안에 프록시 종료버튼 만들기 2. 기존의 설정 기억하는 기능 만들기 (현재는 재부팅 때마다 설정
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 22. [LGO] b5f5672a2446d4e8
- **질문**: 데스크톱 앱 띄우면 텔레그램 수신 끊겨?
- **선택된 메모리**: [USER] 정확히는 헤르메스 '데스크탑'을 실행하면 헤르메스 게이트웨이도 실행이 되는 걸로 알고 있는데, 텔레그램을 수신하려면 hermes g
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 23. [LGO] d28786a095ace1ae
- **질문**: X1 외부 데이터셋 실험에서 bekko 성능?
- **선택된 메모리**: 임베딩 벤치 S3 최종(2026-10-01): bekko-a8m 조건부 채택 권고 — vec-only gold MRR 0.780>R@1 0.75
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 24. [LGO] 2f199c68ab243ff8
- **질문**: best-of-5에 recovery 얹으면 개선돼?
- **선택된 메모리**: [USER] 원본이 best-of-n을 거쳐 최선의 결과를 얻어내는 방식이라면, 우리는 recovery routing을 하는데, 여기서 뭘 얻을
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 25. [LGO] 7a3675ebfc5a1829
- **질문**: S3에서 임베딩 모델 최종 선택 근거?
- **선택된 메모리**: 임베딩 벤치 P3b 보강 완료(2026-10-01): gold 50 확장 결과 bekko vec-only MRR 0.772>R@1 0.72 1위
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 26. [LGO] 1928d454e0ed168b
- **질문**: CAMOFOX_URL 제거한 이유?
- **선택된 메모리**: [USER] camofox 관련 흔적은 제거하고, agent browser를 chrome으로 하고, nodriver로 스텔스를 챙길 수 있도록
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 27. [LGO] f9d466b9cdc3cd88
- **질문**: pi 에이전트에 등록된 프록시 목록?
- **선택된 메모리**: [USER] 나는 pi coding agent를 설치했어. 여기에 20128과 18080 프록시를 프로바이더로 추가하고 싶어
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 28. [LGO] 09547ea49fc36991
- **질문**: webdriver 숨김이 필요한 경우가 뭐지?
- **선택된 메모리**: [USER] camofox 관련 흔적은 제거하고, agent browser를 chrome으로 하고, nodriver로 스텔스를 챙길 수 있도록
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 29. [LGO] ed3a3442d3bcbb33
- **질문**: 메모리 백엔드 뭐 쓰고 있어?
- **선택된 메모리**: [USER] 내가 이 JEV + 경량 sqlite 방식 메모리를 택한 이유는 메모리 사용량이 적고, 별개의 llm 호출이 없기 때문이야 (JEV
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 30. [LGO] dce5e8ceddf18db9
- **질문**: hermes update 중간에 꺼지면 어떻게 해?
- **선택된 메모리**: [USER] 방금 터미널에서 헤르메스를 업데이트했는데, 중간에 경고가 뜨면서 몇몇 패키지가 설치되지 않은 것 같아. 어떤 문제인지 한번 봐 줘.
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 31. [LGO] edf486fa0d3cd079
- **질문**: deepseek 장문 스트림에서 뭐가 문제였어?
- **선택된 메모리**: [USER] 이 플러그인과 관계가 있는 문제인지는 잘 모르겠는데, 지금 이렇게 길게 세션을 이어갈 때 네 답변이 헤르메스 데스크탑 세션창에서 두
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 32. [LGO] 3581b9a33901eba4
- **질문**: statem controller 버전 뭐였어?
- **선택된 메모리**: StateM: statem-skill/statem-bench, pin 8c3309a(PyPI동명X). hardened(08-21): contro
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 33. [LGO] 3581b9a33901eba4
- **질문**: TimeoutExpired 처리 어떻게 바뀌지?
- **선택된 메모리**: [USER] 한 가지 의문점이 더 있어. 이렇게 프록시에서 강제로 직렬화를 해서 동시호출을 하지 않고 줄세운다 쳐도, 에이전트의 타임아웃이 바뀌
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 34. [LGO] 0ea67a3b101917e5
- **질문**: 웹 추출 백엔드 뭘로 설정했지?
- **선택된 메모리**: [USER] 지금 이 세션에서 브라우저 기반 웹 추출 실험을 진행해줘.  ## 배경 - Hermes config에 'browser'라는 M
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 35. [LGO] 5e8516d6f91b46dd
- **질문**: 18080 프록시가 뭐 하는 거야?
- **선택된 메모리**: 18080 camelai-serial-proxy에 모델 스위치(model_override)·라우팅 표시(routed_model)·추론레벨 주입(
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 36. [LGO] 5e8516d6f91b46dd
- **질문**: camelai-serial-proxy 기능 정리해줘
- **선택된 메모리**: 18080 camelai-serial-proxy에 모델 스위치(model_override)·라우팅 표시(routed_model)·추론레벨 주입(
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 37. [LGO] 132fb95d922f9bc5
- **질문**: 전환 전 어떤 문제 있었지?
- **선택된 메모리**: [USER] 이 세션은 8780 프록시에 연결되어 있었는데, 8780 프록시가 제대로 재시작되지 않으면서 연결이 끊겼어. 그래서 내가 프록시를
- **Winner Gate 판정**: YES (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 38. [NOANS] nans2_001
- **질문**: web_extract의 백엔드로 ddgs를 쓰고 있었던 기간이 언제야?
- **선택된 메모리**: 웹 수집·추출: web.extract_backend=tavily(키리스, v0.20.4+, 2026-08-21 설정) — ddgs 검색+키 없이
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 39. [NOANS] nans2_005
- **질문**: Hermes config.yaml에서 browser.backend를 camofox로 설정한 적이 있어?
- **선택된 메모리**: Hermes 내장 browser_* 도구 라우팅 설정 완료(2026-08-08): .env의 CAMOFOX_URL 활성 라인 제거(주석만 남음)
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 40. [NOANS] nans2_008
- **질문**: JEV_API_URL이 experientiallabs가 아니라 다른 URL이던 적이 있어?
- **선택된 메모리**: [USER] 좋아 이제 1~3단계에 착수해도 될 것 같아. 다만, 실측 테스트에 jev 호출이 필요하다면 기존의 typesafe api key
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 41. [NOANS] nans2_009
- **질문**: Free tier 한도가 $0.75/hour였던 시절이 있었어?
- **선택된 메모리**: [USER] experlabs 엔드포인트는 유료 크레딧 모델을 실행시켜도 무료 한도가 있으면 무료를 우선으로 쓰는 것 같아. experlabs의
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 42. [NOANS] nans2_011
- **질문**: exa 검색이 키리스로 작동하던 기간이 언제야?
- **선택된 메모리**: web_extract 키리스 해결 (2026-08-21): v0.20.4부터 plugins/web/keyless_mcp.py 키리스 티어 존재
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)

### 43. [NOANS] nans2_038
- **질문**: 메모리 저장을 승인 없이 자동으로 하던 규칙이 있었어?
- **선택된 메모리**: [USER] 나는 대부분의 경우 한국어 출력이 필요해. 하지만 그렇다고 매 턴마다 1500토큰이 증가하는 메모리 저장 방식은 쓰기 싫어. 어떻게
- **Winner Gate 판정**: NO (참고용 — 판정에 영향 주지 마세요)
- **수동 판정**: ___ (VALID / PLAUS / IRREL)
