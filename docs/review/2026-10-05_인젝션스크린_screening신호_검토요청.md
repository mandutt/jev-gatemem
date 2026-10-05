# 한글 인젝션 스크린 + unvetted screening 신호 — 검토 요청 (외부 AI)

- **작성일**: 2026-10-05
- **작성자**: jev-mem (Hermes 데스크톱 세션)
- **검토 대상**: jev-memory-middleware (JEV 기반 메모리 게이트웨이, 이하 **jev-mem**)의 **읽기 경로 프롬프트 인젝션 방어** 도입 여부
- **검토 의뢰 사유**: 저장소 `hermes-jev-skills`(TypeSafe Jev 에코시스템, MIT)의 memory 메커니즘을 대조하다가, 우리 시스템에 **읽기 경로 인젝션 스크린**이 없음을 발견. 0콜 실측 6종으로 타당성을 검증했으니, **채택 여부와 설계 결함**을 외부 관점에서 검토받고자 함. **당장 채택하지 않고, 이 문서 + 실측 산출물을 근거로 재판정 예정.**
- **중요 전제**: 여기서 다루는 `jev-mem`은 arXiv 2609.23986의 학술 프로젝트 "Jev-Mem"과 **이름만 유사한 별개 프로젝트**입니다. 혼동하지 말 것.

---

## 1. 한 문단 요약

jev-mem은 쓰기 게이트(G-qual/G-AS, Jev 1~2콜)와 읽기 rerank(Jev choice 1콜)로 Jev를 쓰는 Hermes용 메모리 미들웨어다. 지금까지 **인젝션 방어는 없다**: 읽기 시 passage가 컨텍스트로 들어갈 때 "이 passage가 AI를 조종하는 지시를 담고 있는가"를 검사하는 층이 없다. 외부에서 살펴본 `hermes-jev-skills`는 **국소 정규식 스크린(`local_screen`) + Jev 판정 + screening 신호**의 3겹을 쓴다. 우리 DB를 실측하니, **전체 메모리의 21%가 외부 제어 텍스트(@file/@url 첨부·백그라운드 프로세스 출력·다른 에이전트 자동주입)**라 "우리가 넣은 기억뿐"이라는 전제가 성립하지 않는다. 이에 ① 한글 인젝션 스크린(결정적 규칙)을 **30/30 catch · FP 0/1796**으로 검증했고, ② fail-open 시 **"Jev 미검증(unvetted) passage가 통째로 컨텍스트에 실리는" 비대칭**을 실측했다. 채택을 당장 하지 않고, 이 문서로 검토받아 재판정하려 한다.

## 2. 시스템 개요 (jev-mem)

- 메모리 저장: SQLite 행 단위 (working_memory 1,683 + episodic_memory 113 = **1,796행**), 행당 content + 임베딩(bekko-a8m 384d) + FTS5.
- **쓰기 경로**: 발화마다 Jev 게이트.
  - G-qual (user): `store==NO_STORE && type==NO_STORE && store_conf>=0.6` → SKIP, else KEEP.
  - G-AS (assistant): `store==NO_STORE | (store==STORE && type==context)` → SKIP, else KEEP. (`sync_roles` 옵트인).
  - 실패/KILL → **KEEP (데이터 유실 금지)**, fail_open 태깅 + 사후 재판정(96건 적용).
- **읽기 경로** (쿼리당):
  1. lane pool: FTS(60)+vec(60)+importance+graph → RRF 병합 → 풀(≤60)
  2. 어휘 게이트: min_distinctive=2, min_coverage=0.30 (vec rank≤2 예외)
  3. **Jev choice 1콜**: 1위 lift, abstain 라벨(무답 거부). **fail-open 시 풀 그대로 컨텍스트 전달**
- 한국어 어미 분류 패치는 **Mnemosyne 쓰기 분류기**(저장 타입 결정)이며 인젝션 방어와 계층이 다름.
- 규모·실측 방법: 전부 **0콜** (JEV API 호출 없음), DB read-only 또는 스크래치.

## 3. 발견 — "메모리는 우리가 넣은 기억뿐"이 아니다 (출처 실측)

사용자 반문: "애초에 인젝션 위험을 거르기 위한 스크린인데, 메모리 읽기 단계에서 인젝션이 있을 상황이 있어? 어차피 메모리에는 우리가 넣은 기억밖에 없지 않아?"

라이브 DB 1,796행 출처 전수 분류:

| 출처 | 행 | 비율 |
|---|---|---|
| 사용자 발화(plain `[USER]`) | 816 | 45.4% |
| AI 응답(plain `[ASSISTANT]`) | 455 | 25.3% |
| **다른 에이전트 세션 자동주입** (`[opencode session]`/`[codex session]`) | 201 | 11.2% |
| **백그라운드 프로세스 출력** (`[IMPORTANT: Background process ...]`) | 107 | 6.0% |
| 대화 요약/압축 (`[conversation]`) | 75 | 4.2% |
| **외부 첨부 포함** (`@file:`/`@url:` — 웹 문서·다운로드 파일) | 70 | 3.9% |
| 기타(선호·규칙·설정 요약) | 72 | 4.0% |

→ **외부 제어 텍스트 유입 378행 = 21.0%**. 특히 `@url`(웹 문서)과 백그라운드 프로세스 출력은 **공격자의 텍스트가 게이트를 통과해 저장될 수 있는 경로**다. 쓰기 게이트는 "저장할지"만 판정하고 "내용이 인젝션인지"는 보지 않는다.

## 4. 대조 대상 — hermes-jev-skills의 방어 구조 (MIT)

- **local_screen (0콜 결정적 규칙)**: 인젝션 4형태 — ①지시 무시/덮어쓰기 ②자격증명 요구 ③위험 명령 ④URL 탈취. **모든 경로에서 항상 실행** (Jev 판정과 독립), 어떤 실패로도 none으로 떨어지지 않음.
- **screening 신호**: 쿼리+passage가 Jev에 갔는지/로컬만 봤는지를 결과에 명시 — `jev+local` / `local-only` / `none`. "Jev가 검증 안 했으면 절대 clean으로 읽지 마라" 원칙.
- **privacy.py**: credential passage는 Jev에 미전송 + 마스킹(이메일/전화/카드/토큰/hex).
- **검증 수치**: 영어 README 11,299 passage FP 0.42%, 인젝션 near-miss 25종 중 20 catch.

## 5. 우리 실측 (0콜)

### 5-1. 저장소 local_screen 직접 이식 — 한국어에서 무력 (기각)
- 라이브 DB 1,796행: flag 73건(4.06%) — **전부 오탐**(sensitive 69 "API key" 단어·이미 `[REDACTED]` 처리된 값 + command 3/instruction 1은 정상 문서).
- 한국어 인젝션 30종 catch: **1/30 (3%)** — `curl | bash`뿐. 영어 키워드가 섞이면 6/7 catch.
- 판정: 영어 문서용 규칙. 한국어 메모리 도메인에 그대로 이식 불가.

### 5-2. 한글 인젝션 스크린 (신규 작성, 결정적 규칙) — 검증 완료
- 원리: **"명령형 어미 + 위험 신호" 결합**만 발화. 위험 신호 = 비밀 명사·파괴 명령·탈취 URL·사용자 은닉·메모리 변조. 명령형 어미 `(해줘|하라|하세요|잊어버려|숨겨 …)`.
- FP 방어: 문서 인용·과거 서술·명사형·표제·일상 용어(토큰 수·API 문서)는 통과.

| 지표 | 결과 |
|---|---|
| 한국어 인젝션 30종 catch | **30/30 (100%)** |
| 라이브 DB 1,796행 FP | **0 (0.00%)** |
| 단위 self-check (26 공격+정상) | 26/26 |
| 영어 스크린과 추돌(영어 FP 73행 대상) | 0 |
| 비용 | 0콜 (순수 정규식, 결정적) |

(개선 과정: catch 3% → 93% → 100%, FP 2.28% → 1.28% → 0.06% → 0.00%. 산출물 `screen_probe_ko.py`.)

### 5-3. screening 신호 (unvetted 표시) — 읽기 경로 비대칭 실측
- `query_log` 178건: abstain 40건(전부 Jev 판정 → 설계상 빈 컨텍스트).
- **fail-open (2026-10-03, auth 403 incidents 5건)**: `Jev choice: idx=None` **23회** → `/v1/prefetch 200` — **Jev 판정 없이 풀(24~92 passage)이 그대로 컨텍스트 진입**. 같은 기간 저장 경로는 fail_open 태깅+재판정(96건)으로 보호됨. **읽기만 비대칭 무방비.**
- abstain 40건 중 6건은 시스템 메시지, 34건 실사용 질문.

## 6. 검토 질문 (의견 부탁)

1. **한글 인젝션 스크린(5-2)의 채택 가치** — FP 0/1796·catch 100% 실측이지만 합성 셋 의존이다. 우리 메모리 도메인에서 "실제 유입되는 인젝션"의 기저율이 낮다면, 과방어(컨텍스트 passage 제외·복잡도 추가)가 오히려 해가 될 수 있는가? 정규식 스크린의 근본 한계(우회·문맥 오판)는 어떻게 보완/수용할 것인가?
2. **적용 위치** — ① fail-open 시에만(2a) ② 모든 recall에 항상(2b) 중 어느 쪽이 우리 구조에 맞는가? 항상 동작이면 Jev choice와 중복 검사가 되어 비용/지연은 0콜·수 ms지만, "항상 스크린"이 가져오는 부작용(예: 정상 지시문 저장 행이 제외될 리스크)이 있는가?
3. **screening 신호(5-3)의 가치** — "이 recall은 Jev 미검증(로컬 패턴만)" 주석을 fail-open 컨텍스트에 붙이는 최소 패치. Hermes가 이 주석을 보고 신중해질 실제 효과가 있는가, 아니면 장식인가? fail-open 자체가 드물면(월 1~2회) 우선순위는?
4. **한국어 어미 분류와의 충돌** — 우리 쓰기 분류기(`typed_memory.py` 한국어 어미 패치)와 인젝션 스크린이 같은 "어미/명령형"을 본다. 둘의 상호작용에서 놓친 위험이 있는가? (예: 스크린이 "명령형 어미"를 쓰다가 게이트가 저장한 정상 지시문을 오탐 → recall에서 영구 제외.)
5. **원칙 충돌** — 실측에서 "조기 결정의 위험(불완전한 어휘 패턴)"을 본 프로젝트다. **결정적 규칙 기반 방어선**을 추가하는 것이, "정확한 기억 회수"를 해치지 않으면서 "인젝션 방어"를 얻는 올바른 트레이드오프인가? 아니면 다른 접근(저비용 로컬 분류기·Jev 실패 시에만 스크린·출처 기반 신뢰도)이 더 낫나?

## 7. 산출물 (모두 커밋·푸시됨, mandutt/jev-gatemem @ main)

| 파일 | 내용 |
|---|---|
| `experiments/operational-golden/screen_probe_vendor.py` | hermes-jev-skills local_screen+privacy vendored (MIT, 단독 실행) |
| `experiments/operational-golden/screen_probe_a_db.py` | ① DB 스크린 probe (1796행) |
| `experiments/operational-golden/screen_probe_b_korean.py` | ① 한국어 합성 30+30 probe |
| `experiments/operational-golden/screen_probe_ko.py` | ★ 검증 완료 한글 스크린 (self-check 26/26) |
| `experiments/operational-golden/screen_probe_ko_db.py` | 한글 스크린 FP DB probe (1796행) |
| `experiments/operational-golden/data/screen_probeA_raw.jsonl` | ① raw 1796행 |
| `experiments/operational-golden/data/screen_probeKO_raw.jsonl` | 한글 스크린 raw 1796행 |
| `experiments/operational-golden/data/screen_probe_raw_ledger.json` | 전체 raw ledger |
| `experiments/operational-golden/SCREEN_PROBE_REPORT.md` | 종합 리포트 |

## 8. 검토 시 주의/제한

- **전부 0콜 실측** — JEV API 호출 없음. 라이브 DB는 read-only. 합성 인젝션 셋은 우리가 작성한 30종 고정.
- **한글 스크린은 신규 규칙** — "명령형 어미+위험 신호" 결합이라, 한국어 비문법·우회(조사 생략, 어미 변형, 영어 섞기)에 강건하지 않을 수 있음. 이 한계의 수용 가능성도 검토 대상.
- **채택 전제**: 이 문서 + 산출물 검토 후, 별도 재판정(사용자 + 외부 AI)으로 확정 예정. **현재 production 코드는 미변경.**