"""무답 쿼리 40+ 자동 생성 — τ 보정용 무답 세트

- 라이브 DB(1,310행)에 정답이 없는 캐주얼 대화/개인 질문
- 검증: 각 무답 쿼리가 lane pool에 gold가 없는지 나중에 확인 (스크립트는 생성만)
- 산출: experiments/operational-golden/data/golden_noanswer_queries.json
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

OUT = "experiments/operational-golden/data/golden_noanswer_queries.json"

# 라이브 메모리에서 정답이 없을 캐주얼/개인/일상 주제 (hermes 시스템 메모리와 무관)
NO_ANSWER = [
    "오늘 점심 뭐 먹을까?",
    "주말에 영화 보러 갈까?",
    "요즘 날씨가 어떤 것 같아?",
    "가을 옷은 뭐가 유행이야?",
    "서울에서 맛있는 맛집 추천해줘",
    "고양이 키우는 게 어때?",
    "제주도 여행 계획 짜줘",
    "운동 루틴 추천해줘",
    "커피 vs 차 뭐가 더 좋아?",
    "다이어트 식단 좀 짜줘",
    "인생 영화 추천해줘",
    "책 추천 받을 수 있어?",
    "노래방 인기곡 뭐야?",
    "주식 지금 사도 돼?",
    "부동산 전세 vs 월세 뭐가 나아?",
    "아이패드 vs 갤럭시 탭 뭐 살까?",
    "게임 추천 좀 해줘",
    "요리 초보인데 뭐부터 배울까?",
    "혼자 여행 다녀본 적 있어?",
    "반려견 훈련 방법 알려줘",
    "헬스 초보 루틴 알려줘",
    "필라테스 효과 있어?",
    "수면 패턴 개선 방법?",
    "명상 어플 추천해줘",
    "영어 공부 방법 추천해줘",
    "일본어 독학 가능해?",
    "코딩 배우려면 뭐부터?",
    "이력서 잘 쓰는 법?",
    "면접 준비 어떻게 해?",
    "연봉 협상 팁?",
    "퇴사 고민인데 조언해줘",
    "이직 준비 기간 얼마나 걸려?",
    "자기계발서 추천해줘",
    "시간 관리 잘하는 법?",
    "메모 앱 뭐 써?",
    "다이어리 챌린지 해볼까?",
    "친구 생일 선물 뭐가 좋아?",
    "연인 기념일 이벤트 아이디어?",
    "부모님 선물 추천해줘",
    "집들이 선물 뭐가 좋아?",
    "크리스마스 선물 아이디어?",
    "홈카페 용품 추천?",
    "캠핑 장비 추천해줘",
    "등산 코스 추천해줘",
    "자전거 구매 팁?",
    "차량 유지비 줄이는 법?",
    "보험 뭐 들어야 해?",
    "은행 이자 높은 곳?",
    "알뜰폰 vs 통신사?",
    "전기요금 절약 방법?",
]

queries = [{"qid": f"na{i+1:03d}", "query": q, "type": "NO_ANSWER",
            "gold_ids": [], "gold_excerpts": [], "auto": True}
           for i, q in enumerate(NO_ANSWER)]

json.dump(queries, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"생성: {len(queries)}건 → {OUT}")