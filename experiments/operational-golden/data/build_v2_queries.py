"""골든셋 2차 — 쿼리 품질 문제 수정 후 재실측

1차 실패 원인: 자동 생성 literal 쿼리가 "X 설정이나 실측 결과 기억나는 거 전부 알려줘"
템플릿에 추출된 단일 토큰을 붙이는 방식이라 (a) 선호/지침형 메모리와 어휘가 안 맞고
(b) "사용자는", "Final" 같은 의미 없는 토큰이 붙음.

수정: 각 메모리의 content를 사람이 읽고 질문을 수작업 큐레이션 수준으로 재작성.
jev 필터 관점에서 실제 Hermes 운영에서 에이전트가 던질 법한 질문 형태로.
"""
import json, sys, os, time
sys.stdout.reconfigure(encoding='utf-8')

os.chdir("C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall")

draft = json.load(open('golden_queries_draft.json', encoding='utf-8'))

# 수작업 큐레이션 (content 기반, 실사용 질문 형태) — id 매칭
CURATED = {
 '618362fc6d33e3c1': ('camelAI auto 라우팅에서 어려운 과제는 어떤 모델로 보내졌어?', '92번 호출 실험에서 라우팅 결과 어땠지?'),
 'c66472eaa13fd3dc': ('라우팅 플립 트리거 패딩 토큰 가설 맞았어?', '패딩 토큰 수가 라우팅 전환을 결정한다는 결론 나왔나?'),
 '9d4feaccfa1020b4': ('web_extract API 키 없이 쓸 수 있어?', '키리스 웹 추출 설정 어떻게 돼 있지?'),
 'a112c8b5932fbc1f': ('입력 토큰 늘어나면 응답 지연도 늘어?', 'TTFT가 입력 길이에 영향 받아?'),
 '26efd95898ed8fcb': ('디코딩 속도 제일 빠른 모델이 뭐였어?', '모델별 스트리밍 tok/s 실측 결과?'),
 '098d90e014006142': ('luna에 effort max 넣으면 에러 나?', 'max 추론 레벨 미지원 모델 어떻게 처리돼?'),
 'e481f1a2bb8f7969': ('같은 프롬프트 여러 번 보내면 라우팅 고정돼?', 'auto 라우팅이 확률적이라는 결론이었나?'),
 'b2ed9f4dc0b1efea': ('config.yaml에 18080 프록시 등록 방법?', 'custom_providers에서 Local 프록시 어떻게 설정하지?'),
 '7de2c1dfef632694': ('gemini 별칭으로 모델 호출되나?', 'upstream 404 뜨는 별칭이 어느 것들이었지?'),
 'e5bbd0063f1356f6': ('프록시에서 특정 모델 강제 지정 기능 있어?', 'model_override와 effort 주입 기능 언제 추가됐지?'),
 'ef3d9670463aea79': ('코덱스 앱이 PC 느려지게 한 원인 뭐였어?', '마우스 버벅임 원인 조사 결과?'),
 'd1c90516d9870c95': ('한국어 말투 규칙 뭐지?', '반말 써도 돼?'),
 '2ecef73164830638': ('작업 스케줄러 등록해도 돼?', '자동 시작 설정 어떻게 하는 게 원칙이야?'),
 '9f04ed2c8e14f11b': ('설계 확정 후 리팩터 제안해도 돼?', 'ADR Final 이후에 뭐 하면 안 돼?'),
 'a13019e1f438960c': ('감사 보고서는 어떤 섹션으로 써?', '리뷰 산출물 형식 규칙?'),
 '9150f1246613b092': ('리뷰 전용 턴에서 커밋해도 돼?', 'commit governance 규칙이 뭐지?'),
 '5a3ebc06a87940da': ('설계 리뷰에서 SOLID랑 일관성 중 뭐 우선?', '신규 타입 만드는 게 원칙이야?'),
 'c9e4828c93bdb0a0': ('구현됐다는 말 믿기 전에 뭘 확인해?', 'evidence 규칙 어땠지?'),
 'a68b370287d1892f': ('사용자 언어 습관이 어때?', '한국어 영어 어떻게 섞어 써?'),
 '1cef4743165b7707': ('아키텍처 설계 시 분리 원칙이 뭐였지?', 'DTO 분리 어디까지 하면 돼?'),
 'f2421b7b489858bb': ('verifier-pilot은 코딩 품질만 보면 돼?', '그 프로젝트 진짜 목표가 뭐지?'),
 'e6b3887395a2ac45': ('스킬 만들 때 file_content로 보내면 돼?', 'skill_manage create 파라미터 뭐 써야 하지?'),
 'e941022a685c2be1': ('opencode에서 메모리 자동 기록돼?', 'Mnemosyne 플러그인 repo 주소 뭐야?'),
 '498bb204de3b1d14': ('commitment FP 필터 실측 결과 어때?', 'gold50 기준선 수치가 뭐지?'),
 'c69c459c7c67c2d1': ('hermes update 후 cua-driver 왜 실패해?', '660초 타임아웃 원인 뭐였지?'),
 'ac6b11080109c3fe': ('start_proxy.cmd 재부팅 후 왜 안 돌아가?', '배치 파일 인코딩 문제였어?'),
 'efb4e9a38f6ee270': ('프록시 대시보드에 종료 버튼 있어?', 'shutdown API 어떻게 만들었지?'),
 '36f843b4b1886e39': ('Hermes 데스크톱 워치독 런처 어디 있어?', 'Hermes_With_Watchdog.cmd 위치?'),
 'b5f5672a2446d4e8': ('데스크톱 앱 띄우면 텔레그램 수신 끊겨?', 'orphan gateway reap 회귀 맞아?'),
 'd28786a095ace1ae': ('KoDialogBench 4종 검증 결과 어땠어?', 'X1 외부 데이터셋 실험에서 bekko 성능?'),
 '2f199c68ab243ff8': ('best-of-5에 recovery 얹으면 개선돼?', '67차 실험 최종 결론 뭐였지?'),
 '90b4edf612db6b2c': ('codex CLI에서 메모리 기록되나?', 'codex config.toml 훅 어떻게 설정했지?'),
 '509622f2ecaf7c06': ('bekko랑 koen 벤치 비교 결과?', 'P3b 확장 gold MRR 수치?'),
 '7a3675ebfc5a1829': ('bekko-a8m 채택 이유가 뭐야?', 'S3에서 임베딩 모델 최종 선택 근거?'),
 '2ff550d144b5ae03': ('코드 설명과 구조 라벨 언어 규칙?', '완전 번역 금지 규칙 뭐지?'),
 '1928d454e0ed168b': ('브라우저 도구 라우팅 설정 어떻게 돼?', 'CAMOFOX_URL 제거한 이유?'),
 'f9d466b9cdc3cd88': ('pi 에이전트에 등록된 프록시 목록?', 'models.json에 어떤 엔드포인트 있지?'),
 '09547ea49fc36991': ('stealth 브라우저 언제 써야 해?', 'webdriver 숨김이 필요한 경우가 뭐지?'),
 'ed3a3442d3bcbb33': ('메모리 백엔드 뭐 쓰고 있어?', 'provider가 뭐지?'),
 'dce5e8ceddf18db9': ('hermes update 중간에 꺼지면 어떻게 해?', 'venv 손상 시 복구 방법?'),
 'edf486fa0d3cd079': ('deepseek 장문 스트림에서 뭐가 문제였어?', 'S8 시나리오 실패 원인?'),
 '0ea67a3b101917e5': ('웹 추출 백엔드 뭘로 설정했지?', 'Exa 왜 안 써?'),
 '5e8516d6f91b46dd': ('18080 프록시가 뭐 하는 거야?', 'camelai-serial-proxy 기능 정리해줘'),
 '132fb95d922f9bc5': ('supermemory 왜 안 쓰는 거야?', '전환 전 어떤 문제 있었지?'),
 '3581b9a33901eba4': ('statem controller 버전 뭐였어?', 'TimeoutExpired 처리 어떻게 바뀌지?'),
}

rows = []
for d in draft:
    if d['id'] not in CURATED:
        continue
    lit, para = CURATED[d['id']]
    rows.append({'id': d['id'], 'cat': d['cat'], 'query_literal': lit, 'query_paraphrase': para})

# 무답 10개 유지
no_answer = [
    "쿠버네티스 클러스터 셋업 절차 알려줘",
    "작년 주식 투자 수익률이 어땠지?",
    "부산 여행 코스 추천해줘",
    "리액트 서버 컴포넌트 도입 계획 세워줘",
    "심장 재활 운동 프로그램 짜줘",
    "고려대 연세대 축구 경기 결과 알려줘",
    "스위스 알프스 등산 코스 알려줘",
    "전기차 배터리 재활용 기술 최신 동향 알려줘",
    "불고기 레시피 상세하게 알려줘",
    "러시아어 동사 활용 규칙 설명해줘",
]
for na in no_answer:
    rows.append({'id': None, 'cat': 'NO_ANSWER', 'query_literal': na, 'query_paraphrase': na})

json.dump(rows, open('golden_final_v2.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f"golden_final_v2.json: {len(rows)} rows (gold {len(rows)-len(no_answer)} + no-answer {len(no_answer)})")
print(f"큐레이션 매칭: {len(rows)-len(no_answer)}/{len(draft)}")