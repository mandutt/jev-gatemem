# OptMem (VictorTaelin/OptMem) 검토 — 2026-10-09 (0콜, 코드 미변경)

> ⚠️ 이름 유사 주의: 이 문서의 'jev-mem'은 **본 프로젝트(hermes-made/jev-memory-middleware)**이며, 학술 'Jev-Mem'(arXiv 2609.23986)·npm 'jevmem'(Avinash-jetwani)·kerpopule/hermes-jev-skills와는 무관한 별개 프로젝트다.

## 대상

- 저장소: `github.com/VictorTaelin/OptMem` (1.7k★, 42 commits, 검토일 기준)
- 구현: Python 3 단일 파일 `memo` (859줄, 의존성 0, fcntl/msvcrt) + `install.sh` + `test.py` (614줄)
- 아이디어: "Permanent memory for AI agents. A 426-token prompt, a script, plug and play."
- 검토 방법: 전체 소스 read (clone @ 1fb164c), 실측 0건 (표본·콜 없음)

## 구조 요약

- **저장**: `~/.optmem/memory/LOG.txt` — append-only. 레코드 **고정 폭 320B**(`#<id> YYYY-MM-DD <text>`) → "position IS identity": 메모리 i는 i*320 오프셋, 블록은 TREE/REC 단위로 **seek 1회 조회**. `fsync` + 클래스 잠금(flock, Windows는 msvcrt 스핀) + 크래시 시 미완성 꼬리 레코드 절단(repair). 파편화·인덱스 파일 없음.
- **회수 — 본질 = 이진 병합 요약 트리 (LLM 비용 0)**:
  - `note`로 새 메모리 추가 → 병합 트리(`TREE/<size>` 레벨 파일)에 요약 블록이 **에이전트의 `nap` 응답으로** 채워진다. 블록 [lo,hi)의 요약 1줄 = 두 반쪽 요약의 압축. 프롬프트: "Compress memories #a-b into one line… Keep what has lasting effect, drop what does not. **Invent nothing.**"
  - `wake` = 읽기 예산(기본 96줄 ≈ 8k 토큰) 안에서 **최근 메모리는 원문, 오래된 것은 요약 블록**으로 노출 — "detail decays with age" (α-틸링: 블록 크기 ≤ α×나이).
  - LLM을 호출하는 코드는 **사용자/에이전트뿐** — 툴 자체는 API 콜 0.
  - `forget <lo-hi>` = 잘못된 요약+그 위 전부 폐기(로그 불변) → 다음 nap가 재건. `recall <regex>` = 전체 로그 1-pass 스캔(최신 N개만, 출력 캡 준수). `zoom` = 트리 노드 반쪽 열기.
- **통합**: 설치기가 426-token 시스템 프롬프트 블록을 출력 → AGENTS.md 상단에 붙임. "At startup: `memo wake` (mandatory) / While working: `memo note` (mandatory) / 서브에이전트는 memo 금지".

## 우리 (jev-mem) 대비 축

| 축 | OptMem | jev-mem (현행) | 판정 |
|---|---|---|---|
| 저장 내구성 | append-only, 고정 폭, fsync+잠금+repair | SQLite WAL + FTS, fail-open 게이트 | 우리 우월 (SQLite 상위 호환) |
| 회수 | 요약 트리 (에이전트 nap) | FTS+vec+imp lane 합집합 pool 60 → JEV choice 1콜 | **다른 축** (read-time 판정 vs 세대 압축) |
| 요약 비용 | 0 (콜 없음) | JEV choice 턴당 1콜 (기본) | OptMem 유리하나 우리 구조와 이식 불가 |
| 삭제 | 불가 (append-only, forget은 캐시만) | 저장 게이트 SKIP (저장 전 차단) | 우리와 방향 다름 — write-time vs post-hoc |
| 검색 | regex 전체 스캔 (단어 단위) | FTS+벡터+RRF | 우리 우월 |
| 재현성 | 요약 = 로그에서 재건 가능한 캐시 | 스냅샷/raw 고정 평가 | **철학 동일** |

## 신규 아이디어 (아직 우리가 실측 안 한 축) — 보류: "세대별 노출 밀도 (age-aware exposure)"

- OptMem의 `wake`는 **읽기 예산을 시간 세대로 배분**(최근=원문·과거=요약)한다. 우리의 노출 `_render` rows[:5]는 순위 상위 고정이고, hippo decay는 '순위 가중치' 축(기각, Run R)이며, **'노출 구성에 시간 밀도'는 별개 축으로 아직 실측하지 않았다.**
- 채택 전제는 다음 두 실측이 함께 통과해야 한다:
  1. **구조 변경은 전체 재현 회귀 3-run만으로 판정** (파일럿 기각 규칙).
  2. **production-exact에서 rank>20 gold 존재 (stage85) — 과거 메모리 요약화는 그 정답을 구조적으로 유실**시킨다. 요약 대상·압축률을 정밀 조정해도 '과거 정답 원문 노출' 가능성 자체가 사라지는 설계는 이 실측과 정면 충돌.
  3. 코퍼스 규모: mnemosyne.db 1,584행(전체가 예산 안) — 요약이 필요한 규모가 아님. **현재는 시기상조.**
- 판정: **보류 목록 등록** — 코퍼스가 수만 행 이상으로 커져 '읽기 예산 초과'가 실재가 되는 시점에 재검토. (do not re-run 아님 — 아직 실험을 안 한 축이므로.)

## 기각

1. **고정 폭 레코드·O(1) seek·자체 잠금·repair** — SQLite WAL/FTS/벡터가 상위 호환. 이식 무의미.
2. **'에이전트가 nap으로 요약' 구조 직접 이식** — 우리는 백그라운드 데몬(사용자 개입 없는 환경)이라 '에이전트가 프롬프트를 받아 요약을 답하는' 수동 루프가 성립하지 않는다. (요약 생성에 별도 LLM을 붙이는 변형은 우리가 이미 턴당 1콜 JEV 외 추가 콜을 허용하지 않는 원칙과 충돌.)
3. **regex recall** — FTS+벡터+RRF 대비 열위. 벤치 불필요.
4. **wake 강제·note 필수·서브에이전트 금지 등 '프롬프트 규율'** — Hermes는 시스템 프롬프트·memory 정책으로 동일 효과를 이미 가짐. 서브에이전트 금지도 Hermes 자녀 에이전트는 memory 툴이 없어 자연 실현.
5. **paginate·import 부트스트랩·per-memory config** — 우리 구조에 해당 없음.

## 재현 경로

- 원본 코드: `C:/Users/mandu/AppData/Local/Temp/OptMem/memo` (clone @ 1fb164c, 검토일 임시)
- 본 문서를 기반으로 재검토 시 원격 저장소 직접 확인 (URL: https://github.com/VictorTaelin/OptMem)

## 결론

직접 이식할 코드 없음. 유일한 신규 후보 = **세대별 노출 밀도(age-aware exposure)** — 미실측 축이지만 현재 코퍼스 규모에서 시기상조 → 보류 등록. 철학적 정합(append-only·무삭제·재건 가능 캐시)은 우리 fail-open 원칙과 이미 일치.