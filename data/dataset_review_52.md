# Dataset 최종 검수 (52 queries)

qid | type | query | gold ids

---|---|---|---
| q101 | factual | 웹 페이지를 추출할 때 stealth 브라우저가 필요한 경우는 언제야? 로그인이나 캡차 같은 경우인가? | `09547ea4` |
| q102 | project | 헤르메스에서 브라우저 도구를 쓰면 기본적으로 어떤 브라우저가 실행돼? camofox는 안 쓰는 거야? | `1928d454` |
| q103 | factual | 웹 추출 백엔드는 지금 어떻게 설정되어 있어? API 키 없이도 되는 거야? | `0ea67a3b`, `9d4feacc` |
| q104 | failure | Exa 키리스로 웹 추출하면 한글이 깨지는데 왜 그래? | `0ea67a3b`, `9d4feacc` |
| q105 | project | 텔레그램 게이트웨이가 자꾸 죽는데 자동으로 복구되게 하려면 어떻게 해? | `36f843b4` |
| q106 | causal | 데스크톱 앱을 켜면 텔레그램 게이트웨이가 멈추는 문제가 있어. 원인이 뭐야? | `b5f5672a` |
| q107 | factual | 게이트웨이 워치독을 쓰면 수명이 어떻게 되는 거야? 상주 프로세스야? | `36f843b4` |
| q108 | factual | camelai-serial-proxy는 뭐 하는 프록시야? 어느 포트를 쓰지? | `5e8516d6` |
| q109 | failure | 재부팅 후 start_proxy.cmd를 실행해도 프록시가 안 뜨는데 왜 그럴까? | `ac6b1108` |
| q110 | causal | 18080 프록시에 모델 목록을 설정할 때 왜 맵핑 형태로 유지해야 해? | `b2ed9f4d` |
| q111 | project | camelAI에서 특정 모델(예: gemini)을 고정해서 쓸 수 있어? | `7de2c1df` |
| q112 | causal | camelAI auto 라우팅은 어떤 기준으로 모델을 고르는 거야? 어려운 과제면 뭘로 가? | `e481f1a2`, `618362fc` |
| q113 | failure | deepseek-v4-flash로 도구 호출하면 가끔 JSON이 깨지는 문제가 있었잖아, 지금은 해결됐어? | `edf486fa` |
| q114 | project | 18080 프록시에서 모델 스위치나 라우팅 표시 같은 기능이 추가됐다고 들었는데 확인해줘 | `e5bbd006` |
| q115 | factual | camelAI의 reasoning effort 파라미터는 어떤 역할을 해? max로 하면 뭐가 달라져? | `098d90e0` |
| q116 | causal | camelAI에서 deepseek는 왜 이렇게 느린 거야? 다른 모델보다 10배 느리다며? | `26efd958` |
| q117 | factual | camelAI에 입력 토큰이 많아지면 응답이 느려진다는 얘기가 있는데 사실이야? | `a112c8b5` |
| q118 | temporal | camelAI 라우팅이 프롬프트 크기에 따라 바뀐다는 실험 결과가 있었잖아, 결론이 뭐였어? | `c66472ea`, `618362fc` |
| q119 | project | 프록시 대시보드에서 프록시를 종료하는 버튼이 있어? 설정도 저장되나? | `efb4e9a3` |
| q120 | factual | 지금 헤르메스 메모리 provider는 뭐로 설정되어 있어? | `ed3a3442` |
| q121 | project | 코덱스 CLI에서도 Mnemosyne 메모리를 자동으로 쓰게 하려면 어떻게 설정해야 해? | `90b4edf6` |
| q122 | project | opencode에서도 Mnemosyne에 자동 기록되게 하는 플러그인 있어? | `e941022a` |
| q123 | causal | supermemory는 왜 사용을 중단했어? 어떤 문제가 있었지? | `132fb95d` |
| q124 | temporal | verifier-pilot 연구에서 best-of-5에 selective recovery를 더한 방식은 효과가 있었어? | `2f199c68` |
| q125 | factual | verifier-pilot 프로젝트의 진짜 목표가 뭐야? 코딩 품질 개선 아니야? | `f2421b7b` |
| q126 | factual | StateM은 어디에 설치되어 있고 어떤 커밋을 쓰고 있어? | `c6fe48b1`, `766fd800` |
| q127 | project | StateM의 managed controller에서 타임아웃이 나면 어떻게 처리해? | `19bed462`, `3581b9a3` |
| q128 | temporal | statem 미니A/B 실험에서 C 방식이 A보다 좋았어? | `0a13cf10`, `19bed462`, `3581b9a3` |
| q129 | causal | StateM을 쓸 때 workspace 경로를 지시문에 포함해야 하는 이유가 뭐야? | `c6fe48b1` |
| q130 | factual | pi 코딩 에이전트가 사용하는 모델 프록시는 어떻게 등록되어 있어? | `f9d466b9` |
| q131 | project | pi에서 18080 camelai 프록시를 쓸 때 apiKey는 어떻게 해? 검증 안 하는 거야? | `f9d466b9` |
| q132 | failure | hermes 업데이트 후 cua-driver refresh가 계속 멈추는데 원인이 뭐야? | `c69c459c` |
| q133 | failure | 헤르메스 업데이트가 중단되면 venv가 손상될 수 있다며? 복구는 어떻게 해? | `dce5e8ce` |
| q134 | preference | 헤르메스가 만든 스크립트는 어디에 저장해야 해? 홈 폴더 바로 아래는 안 되지? | `2ecef731` |
| q135 | preference | 작업 스케줄러를 써도 되는 거야? 아니면 다른 방식으로 시작 프로그램을 관리해야 해? | `2ecef731` |
| q136 | preference | 실험 결과를 판정할 때 어떤 원칙을 따라야 해? 추측하지 말고? | `c9e4828c` |
| q137 | failure | skill_manage로 스킬을 만들 때 본문은 어떤 파라미터로 넘겨야 해? | `e6b38873` |
| q138 | temporal | camelAI 라우팅 실험들에서 쓰인 호출 수가 어떻게 돼? 37호출이랑 92호출이 있던데 | `e481f1a2`, `618362fc` |
| q139 | temporal | 2026-08-26에 camelAI 모델별 스트리밍 속도를 실측했었다며? 결론이 뭐였어? | `26efd958` |
| q140 | temporal | camelAI effort 실험에서 deepseek는 effort 없을 때랑 max일 때 응답 구조가 어떻게 달라? | `098d90e0` |
| q141 | temporal | cua-driver refresh 타임아웃 문제를 진단하는 명령이 뭐였지? | `c69c459c` |
| q142 | causal | 왜 헤르메스 데스크톱 serve 부팅이 게이트웨이를 죽이는 거야? 어느 커밋부터야? | `b5f5672a` |
| q143 | causal | Exa 키리스 extract가 한글을 깨뜨리는 근본 원인이 뭐야? | `9d4feacc`, `0ea67a3b` |
| q144 | preference | 리뷰/감사 산출물을 만들 때 내가 원하는 형식이 뭐였지? | `a13019e1` |
| q145 | preference | 커밋 거버넌스 규칙이 뭐야? 리뷰만 하는 턴에는 커밋하면 안 되지? | `9150f124` |
| q146 | project | 헤르메스에서 18080 프로바이더를 쓰려면 config.yaml models를 어떻게 둬야 해? | `b2ed9f4d` |
| q147 | project | codex에서 Mnemosyne hooks를 다시 활성화하려면 어떻게 해? | `90b4edf6` |
| q148 | factual | opencode Mnemosyne 플러그인이 수집하는 세션 이벤트는 뭐야? | `e941022a` |
| q149 | factual | 게이트웨이 워치독의 Hermes_Gateway 태스크는 언제 게이트웨이를 시작해? | `36f843b4` |
| q150 | failure | camelAI auto 라우팅에서 이탈된 호출이 max_tokens를 다 태우면 본문이 0자가 될 수 있다며? | `e481f1a2` |
| q151 | failure | 18080 프록시에서 responses API로 effort를 넘기면 어떤 형식이어야 해? | `e5bbd006` |
| q152 | failure | 헤르메스에서 skill_manage로 스킬 생성이 계속 실패하는데 file_content로 보내면 안 되나? | `e6b38873` |