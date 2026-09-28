# ERROR_ANALYSIS.md

- 분석 대상: 390 samples, 오분류 370 (94.9%)

## Error taxonomy (지시문 §20)

| category | count |
|---|---|
| RULE_ERROR | 59 |
| KOREAN_ENDING_ERROR | 59 |
| PRIORITY_ERROR | 1 |
| AMBIGUOUS_UTTERANCE | 47 |
| NO_STORE_BOUNDARY | 204 |

## Category별 대표 사례

### RULE_ERROR

- `검색 결과 10건이 확인되었으며 AC 호텔 바이 메리어트 베벌리 힐스는 3성급입니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `좋은 하루 보내시기 바랍니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `알겠습니다, 정말 고맙습니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `그럼 그때 뵙겠습니다, 좋은 하루 보내십시오.` — gold=NO_STORE pred=fact (conf=0.8)
- `지금은 괜찮습니다. 감사합니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `좋습니다, 고맙습니다, 지금은 이걸로 됐습니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `좋네요, 다행입니다.` — gold=NO_STORE pred=fact (conf=0.8)
- `3월 4일에 멕시코시티에서 라스베이거스로 가려고 합니다.` — gold=commitment pred=fact (conf=0.8)

### KOREAN_ENDING_ERROR

- `샌프란시스코 쪽이면 좋겠어.` — gold=preference pred=context (conf=0.55)
- `3월 1일에 뉴욕을 떠날 예정이라 버스 종류는 아무거나 괜찮습니다.` — gold=preference pred=context (conf=0.6)
- `네, 넬리 맥케이를 좋아해서 저한텐 이게 괜찮은 것 같아요.` — gold=preference pred=context (conf=0.62)
- `이번 달 1일이면 좋겠어.` — gold=preference pred=context (conf=0.55)
- `이제 그쪽에서 식당을 찾아보려고 하는데 보통 가격대에 야외 좌석이 있고 미국식을 파는 곳이면 좋겠어` — gold=preference pred=context (conf=0.66)
- `그거 마음에 드네, 이번 달 9일에 거기서 할 만한 것도 찾아보고 있는데 연극 같은 무대 공연이면 ` — gold=preference pred=context (conf=0.66)
- `다음 주 수요일 오후 2시로 예약해 주세요.` — gold=commitment pred=context (conf=0.82)
- `그 집으로 할게, 3월 10일에 돌아오는 왕복 항공권 3장도 필요하고 좌석 등급은 아무거나 괜찮아.` — gold=decision pred=context (conf=0.6)

### PRIORITY_ERROR

- `필라델피아에서 출발하려고 합니다.` — gold=context pred=fact (conf=0.8)

### AMBIGUOUS_UTTERANCE

- `예약은 완료되었습니다만 안타깝게도 채식 옵션은 제공되지 않으며 가격대는 보통입니다.` — gold=event pred=fact (conf=0.8)
- `귀하의 좌석 예약이 성공적으로 완료되었으며 해당 식당은 아시아식 요리를 제공합니다.` — gold=event pred=fact (conf=0.8)
- `3월 10일에 페탈루마에서 4명 자리 예약하려고 해요.` — gold=commitment pred=context (conf=0.3)
- `샌프란시스코에서 오후 7시에 식당 자리 하나 예약하려고 해요.` — gold=goal pred=context (conf=0.6)
- `좋아요, 참 멋지네요.` — gold=NO_STORE pred=context (conf=0.55)
- `정말 마음에 드네요.` — gold=preference pred=context (conf=0.55)
- `나 파스타밖에 안 먹어, 알지?` — gold=preference pred=context (conf=0.55)
- `워싱턴 시애틀에서 출발하고 돌아오는 건 이번 달 14일로 부탁할게.` — gold=commitment pred=context (conf=0.6)

### NO_STORE_BOUNDARY

- `이 영화에 누가 나오지?` — gold=NO_STORE pred=context (conf=0.55)
- `장르가 뭐고, 누가 출연했어?` — gold=NO_STORE pred=context (conf=0.55)
- `알렉스 켄드릭 감독이 연출하고 에린 라이트-톰슨이 출연한 드라마 영화를 찾아보고 싶어요.` — gold=NO_STORE pred=context (conf=0.3)
- `그럼 정말 좋겠어.` — gold=NO_STORE pred=context (conf=0.55)
- `좋아, 완벽하네, 이 노래가 2012년에 나온 거냐?` — gold=NO_STORE pred=context (conf=0.3)
- `심리학자와의 상담 예약을 진행하시겠습니까?` — gold=NO_STORE pred=context (conf=0.3)
- `아니요, 대신 오후 3시 30분으로 해 주세요.` — gold=NO_STORE pred=context (conf=0.82)
- `다른 요청 있으신가요?` — gold=NO_STORE pred=context (conf=0.68)

## 종결어미 의존성 (지시문 §11)

| ending | n | 오분류 | 오분류율 |
|---|---|---|---|
| ~어요 | 51 | 50 | 98% |
| ~다 | 48 | 36 | 75% |
| ~세요 | 30 | 30 | 100% |
| ~나요 | 23 | 22 | 96% |
| ~합니다 | 15 | 13 | 87% |
| ~해요 | 15 | 13 | 87% |
| ~니까 | 11 | 11 | 100% |
| ~어 | 11 | 10 | 91% |
| ~네요 | 10 | 10 | 100% |
| ~죠 | 10 | 10 | 100% |
| ~가요 | 9 | 9 | 100% |
| ~아 | 9 | 9 | 100% |
| ~야 | 8 | 8 | 100% |
| ~해 | 8 | 7 | 88% |
| ~지 | 7 | 7 | 100% |
| ~아요 | 7 | 7 | 100% |
| ~했어 | 6 | 6 | 100% |
| ~좋겠어 | 6 | 6 | 100% |
| ~줘 | 6 | 6 | 100% |
| ~까요 | 6 | 6 | 100% |

## Ambiguous utterances (gold에서 ambiguity=true, 오분류 중 47건)

- `예약은 완료되었습니다만 안타깝게도 채식 옵션은 제공되지 않으며 가격대는 보통입니다.` — gold=event pred=fact
- `귀하의 좌석 예약이 성공적으로 완료되었으며 해당 식당은 아시아식 요리를 제공합니다.` — gold=event pred=fact
- `3월 10일에 페탈루마에서 4명 자리 예약하려고 해요.` — gold=commitment pred=context
- `샌프란시스코에서 오후 7시에 식당 자리 하나 예약하려고 해요.` — gold=goal pred=context
- `좋아요, 참 멋지네요.` — gold=NO_STORE pred=context
- `정말 마음에 드네요.` — gold=preference pred=context
- `나 파스타밖에 안 먹어, 알지?` — gold=preference pred=context
- `워싱턴 시애틀에서 출발하고 돌아오는 건 이번 달 14일로 부탁할게.` — gold=commitment pred=context
- `좋아.` — gold=NO_STORE pred=context
- `확인하겠습니다, 3월 9일에 아스펜 빌리지 아파트를 방문하시고 싶으시군요.` — gold=commitment pred=context
