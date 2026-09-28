# DATASET_INFO.md

Stage A 결과 — 로컬 3개 데이터셋 구조 스캔 (2026-09-28, read-only)

## KoDialogBench (seongbo/kodialogbench)

- local: `C:/code/dataset/260928testdata/kodialogbench/` (31M)
- format: JSONL, HF snapshot (test split 만 존재 — 21개 테스트셋 중 13개 파일)
- 전체 예시 수: `82,962` (README 기준), 로컬 파일 수:
  - `dialogue_comprehension\dialog_act\dailydialog\test.jsonl` — 1000 records
  - `dialogue_comprehension\emotion\dailydialog\test.jsonl` — 470 records
  - `dialogue_comprehension\emotion\empathetic_dialogues\test.jsonl` — 2000 records
  - `dialogue_comprehension\fact\empathetic_dialogues\test.jsonl` — 2394 records
  - `dialogue_comprehension\fact\personachat\test.jsonl` — 1000 records
  - `dialogue_comprehension\location\socialdial\test.jsonl` — 376 records
  - `dialogue_comprehension\relation\socialdial_distance\test.jsonl` — 524 records
  - `dialogue_comprehension\relation\socialdial_relation\test.jsonl` — 330 records
  - `dialogue_comprehension\topic\socialdial\test.jsonl` — 400 records
  - `response_selection\dailydialog\test.jsonl` — 6740 records
  - `response_selection\empathetic_dialogues\test.jsonl` — 7941 records
  - `response_selection\personachat\test.jsonl` — 7801 records
  - `response_selection\socialdial\test.jsonl` — 7237 records
- 공통 필드: dialogue(화자/발화 쌍 목록), option_description, label 계열
- 발화 추출: dialogue 내 2번째 요소 (utterance), 원문 라벨은 task별 상이 (topic/emotion/act/fact 등)

## KoSGD (AIWORKX/KoSGD)

- files: 34
- n_dialogues: 4201
- turns: 84594
- speakers: {'USER': 42297, 'SYSTEM': 42297}
- top acts: [('?', 88413)]
- top services: [('여행_1', 654), ('이벤트_3', 592), ('호텔_4', 566), ('차량렌트_3', 544), ('버스_3', 526), ('비행_4', 506), ('호텔_2', 496), ('날씨_1', 475), ('식당_2', 463), ('서비스_1', 395)]
- utt_len_min_max: (2, 149)
- schema: None
- 발화 추출: turns[].utterance, speaker USER/SYSTEM, frames[].act 원본 라벨

## KoAlpaca (Beomi/KoAlpaca)

- `ko_alpaca_data.json`: {'records': 49620, 'keys': ['instruction', 'input', 'output'], 'sample': {'instruction': '건강을 유지하기 위한 세 가지 팁을 알려주세요.', 'input': '', 'output': '세 가지 팁은 아침식사를 꼭 챙기며, 충분한 수면을 취하고, 적극적으로 운동을 하는 것입니다.'}, 'instr_len_avg': 26}
- `KoAlpaca_v1.1.jsonl`: {'records': 21155, 'keys': ['instruction', 'output', 'url'], 'sample': {'instruction': '양파는 어떤 식물 부위인가요? 그리고 고구마는 뿌리인가요?', 'output': '양파는 잎이 아닌 식물의 줄기 부분입니다. 고구마는 식물의 뿌리 부분입니다. \n\n식물의 부위의 구분에 대해 ', 'url': 'https://kin.naver.com/qna/detail.naver?d1id=11&dirId=1116&do'}}
- `alpaca_data.json`: {'records': 101622, 'keys': ['instruction', 'input', 'output'], 'sample': {'instruction': '건강을 유지하기 위한 세 가지 팁을 알려주세요.', 'input': '', 'output': '세 가지 팁은 아침식사를 꼭 챙기며, 충분한 수면을 취하고, 적극적으로 운동을 하는 것입니다.'}, 'instr_len_avg': 26}
- `seed_tasks.jsonl`: {'records': 175, 'keys': ['id', 'name', 'instruction', 'instances', 'is_classification'], 'sample': {'id': 'seed_task_0', 'name': 'breakfast_suggestion', 'instruction': "Is there anything I can eat for a breakfast that doesn't inc", 'instances': "[{'input': '', 'output': 'Yes, you can have 1 oatmeal banana", 'is_classification': 'False'}}

## Sampling notes

- KoDialogBench: 13개 파일 전부를 균등 샘플링 (파일당 N), dialogue의 모든 발화에서 추출
- KoSGD: USER 턴 우선 (목적 지향 요청), SYSTE팀 과도 포함 방지를 위해 USER 80% / SYSTEM 20%
- KoAlpaca: instruction 필드만 (output은 정답이므로 제외), 중복 instruction 제거
- deduplication: KoDialogBench/KoSGD는 대화 ID로, KoAlpaca는 instruction 텍스트 해시로 중복 제거
- 원본 파일은 수정하지 않음. 추출물만 evaluation 디렉터리에 저장.