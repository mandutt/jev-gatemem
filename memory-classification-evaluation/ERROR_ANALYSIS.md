# ERROR_ANALYSIS.md

- 분석 대상: 1500 samples, 오분류 1415 (94.3%)

## Error taxonomy (지시문 §20)

| category | count |
|---|---|
| RULE_ERROR | 345 |
| KOREAN_ENDING_ERROR | 185 |
| PRIORITY_ERROR | 5 |
| AMBIGUOUS_UTTERANCE | 7 |
| NO_STORE_BOUNDARY | 873 |

## Category별 대표 사례

### RULE_ERROR

- `영화 잘 보시기 바랍니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `아니요, 지금은 그걸로 됐습니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `예약이 성공적으로 완료되었으며 총 금액은 1,800달러입니다.` — gold=event pred=fact (conf=0.8)
- `예약이 성공적으로 완료되었음을 알려드립니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `모든 것 정말 감사합니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `차량 예약이 정상적으로 완료되었습니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `해당 버스는 다운타운 역에 도착합니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `알겠습니다만 적합한 호텔 10곳을 찾았으며 그중에는 바이아 리조트 호텔이라는 3성급 호텔이 있습니다` — gold=NO_STORE pred=fact (conf=0.8)

### KOREAN_ENDING_ERROR

- `좋아, 스테이지 도어 좋네.` — gold=preference pred=context (conf=0.3)
- `저는 필라델피아에서 워싱턴으로 가려고 해요.` — gold=goal pred=context (conf=0.3)
- `저는 필라델피아 근처에서 하는 연극을 더 선호해요.` — gold=preference pred=context (conf=0.3)
- `아, 방금 생각났는데 스베틀라나에게 결제 요청해야 해요.` — gold=commitment pred=context (conf=0.66)
- `침실 하나, 욕실 하나인 집을 구매하려고 해요.` — gold=goal pred=context (conf=0.6)
- `가족 상담사한테 상담받고 싶어요.` — gold=goal pred=context (conf=0.3)
- `다음 목요일로 예약해 주세요.` — gold=commitment pred=context (conf=0.82)
- `3월 12일에 필요해요.` — gold=commitment pred=context (conf=0.3)

### PRIORITY_ERROR

- `식당 예약이 완료되었으며 테이블은 확보되어 있습니다.` — gold=context pred=fact (conf=0.8)
- `위치가 공유된 상태입니다.` — gold=context pred=fact (conf=0.8)
- `알람 한 개가 바쁨이라는 이름으로 오후 4시 30분에 설정되어 있습니다.` — gold=context pred=fact (conf=0.8)
- `스모어드 레시피를 만듭니다.` — gold=context pred=fact (conf=0.8)
- `사용자의 주문을 추적하기 위한 데이터베이스 스키마를 설계합니다.` — gold=context pred=fact (conf=0.8)

### AMBIGUOUS_UTTERANCE

- `서커스야.` — gold=NO_STORE pred=context (conf=0.55)
- `$ 60 .` — gold=NO_STORE pred=fact (conf=0.3)
- `확실히 육` — gold=NO_STORE pred=context (conf=0.3)
- `고객의 주문을 처리하는 시스템을 설계하십시오.` — gold=NO_STORE pred=context (conf=0.3)
- `어리석은 동물을 묘사합니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `알았어요. 나는 모두를 돌봐` — gold=NO_STORE pred=context (conf=0.3)
- `다른 과일과 토마토 소스.` — gold=NO_STORE pred=context (conf=0.3)

### NO_STORE_BOUNDARY

- `출연 배우가 누구인가요?` — gold=NO_STORE pred=context (conf=0.68)
- `다른 도와드릴 사항이 있으신가요?` — gold=NO_STORE pred=context (conf=0.68)
- `치초레를 스페인어 자막으로 시청하시겠습니까?` — gold=NO_STORE pred=context (conf=0.3)
- `검색하실 영화 장르가 무엇인지 알려주시겠습니까?` — gold=NO_STORE pred=context (conf=0.72)
- `확인했으니 진행해 주세요.` — gold=NO_STORE pred=context (conf=0.82)
- `천만에요, 안녕히 가십시오.` — gold=NO_STORE pred=context (conf=0.3)
- `알겠습니다. 전화번호를 알려 주실 수 있을까요?` — gold=NO_STORE pred=context (conf=0.72)
- `제가 여행 가는 곳이 뉴욕시니까 그쪽으로 검색해 주세요.` — gold=NO_STORE pred=context (conf=0.82)

## 종결어미 의존성 (지시문 §11)

| ending | n | 오분류 | 오분류율 |
|---|---|---|---|
| ~다 | 211 | 168 | 80% |
| ~세요 | 205 | 204 | 100% |
| ~어요 | 152 | 144 | 95% |
| ~니까 | 119 | 119 | 100% |
| ~합니다 | 102 | 87 | 85% |
| ~나요 | 88 | 87 | 99% |
| ~해요 | 72 | 69 | 96% |
| ~시오 | 71 | 71 | 100% |
| ~까요 | 63 | 63 | 100% |
| ~가요 | 38 | 38 | 100% |
| ~아요 | 36 | 35 | 97% |
| ~예요 | 30 | 28 | 93% |
| ~죠 | 25 | 25 | 100% |
| ~어 | 23 | 23 | 100% |
| ~네요 | 21 | 21 | 100% |
| ~야 | 18 | 18 | 100% |
| ~에요 | 15 | 12 | 80% |
| ~래요 | 14 | 14 | 100% |
| ~해 | 14 | 13 | 93% |
| ~게요 | 13 | 13 | 100% |

## Ambiguous utterances (gold에서 ambiguity=true, 오분류 중 7건)

- `서커스야.` — gold=NO_STORE pred=context
- `$ 60 .` — gold=NO_STORE pred=fact
- `확실히 육` — gold=NO_STORE pred=context
- `고객의 주문을 처리하는 시스템을 설계하십시오.` — gold=NO_STORE pred=context
- `어리석은 동물을 묘사합니다.` — gold=NO_STORE pred=fact
- `알았어요. 나는 모두를 돌봐` — gold=NO_STORE pred=context
- `다른 과일과 토마토 소스.` — gold=NO_STORE pred=context
