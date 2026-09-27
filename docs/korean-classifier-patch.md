# 한국어 어미 분류 패치 — Mnemosyne typed_memory

> **목적**: Mnemosyne `classify_memory()`가 한국어 메모리를 의미에 맞게 분류하도록 패치.
> **배경**: 원본 분류기는 영어 정규식뿐이라, 한국어는 전부 폴백(`default_short` → 단어<5 → **FACT**)에 걸려 "좋아 진행해줘" 같은 지시문이 fact로 오분류됨 (2026-09-27 발견).
> **버전**: mnemosyne 3.15.1 (Hermes 런타임 venv와 middleware .venv 동일)

---

## 설치 위치 (2026-09-27 기준)

```
C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\
  environments\746564964b1042b79add42260378503b\
    venv\Lib\site-packages\mnemosyne\core\typed_memory.py
```

**참고**: 동일 파일이 middleware `.venv\Lib\site-packages\mnemosyne\core\typed_memory.py`에도 있으나 **패치 전 원본** — 라이브는 Hermes 설치 venv만 패치됨. (둘 다 3.15.1, diff 원본 기준 동일)

---

## 패치 내용

### 1) 종성 클래스 (28종성 전부, 복합 포함)
```python
_KO_CLASS = {jong: ''.join(chr(0xAC00 + i*588 + m*28 + jong)
                           for i in range(19) for m in range(21))
             for jong in range(28)}
```
- 한글 음절은 유한: 19초성 × 21중성 × 28종성 = 11,172 → 종성별 399개 문자 클래스
- **종성 인덱스 (유니코드 순서, U+AC00 검증)**:
  `0:없음 1:ㄱ 2:ㄲ 3:ㄳ 4:ㄴ 5:ㄵ 6:ㄶ 7:ㄷ 8:ㄹ 9:ㄺ 10:ㄻ 11:ㄼ 12:ㄽ 13:ㄾ 14:ㄿ 15:ㅀ 16:ㅁ 17:ㅂ 18:ㅄ 19:ㅅ 20:ㅆ 21:ㅇ 22:ㅈ 23:ㅊ 24:ㅋ 25:ㅌ 26:ㅍ 27:ㅎ`
- ⚠️ **주의**: 종성 ㅆ은 **20** (7이 아님!), ㅄ은 18, ㄵ은 5. 헷갈리면 `chr(0xAC00+i)` 직접 검증할 것.

### 2) 한국어 어미 패턴 (24개: QUESTION 6 + REQUEST 5 + STATEMENT 10 + DEFAULT 2 → 총 21? 아니, 6+5+10+2=23 + ~이다 포함 = 24)

| 패턴 | 예 | Type | conf |
|---|---|---|---|
| `[ㄴ]지` | 맞는지/되는지 | CONTEXT | 0.72 |
| `[ㄹ]까` | 할까 | CONTEXT | 0.72 |
| `[ㄴ]가` | 맞는가 | CONTEXT | 0.68 |
| `[종성없음]나` | 뭐냐 | CONTEXT | 0.60 |
| `[ㄴ]데` | 없는데 | CONTEXT | 0.66 |
| `[ㄹ]게` | 앉을게 | CONTEXT | 0.60 |
| `[종성없음]줘` | 해줘 | CONTEXT | 0.80 |
| `[종성없음]자` | 가자 | CONTEXT | 0.78 |
| `[종성없음]게` | 보게 | CONTEXT | 0.62 |
| `[종성없음]세요` | 하세요 | CONTEXT | 0.82 |
| `[ㅅ]세요` | 했세요 | CONTEXT | 0.80 |
| `[ㅆ]다` | 먹었다/했다 | FACT | 0.74 |
| `[ㅄ]다` | 없다 | FACT | 0.78 |
| `[ㄵ]다` | 앉다 | FACT | 0.78 |
| `[ㄴ]다` | 간다 | FACT | 0.70 |
| `[ㄹ]다` | 살다 | FACT | 0.70 |
| `[ㅎ]다` | 좋다 | FACT | 0.70 |
| `[ㅂ]다` | 쉽다 | FACT | 0.72 |
| `[ㅁ]니다` | 남니다 | FACT | 0.76 |
| `[ㅂ]니다` | 합니다/있습니다 | FACT | 0.80 |
| `[ㅇ]니다` | 공입니다 | FACT | 0.72 |
| `한글+(이다|ㄴ다)$` | 사실이다/간다 | FACT | 0.68 |
| `한글+$` | 그래/알겠어 (마지막 수단) | CONTEXT | 0.30 |
| `한글+(어|아|지|죠|네요|군요|야|이야)$` | 발견했어/문제야 | CONTEXT | 0.55 |

### 3) 스코어 공식 주의
```python
score = confidence * (1.0 + 0.1 * list(MemoryType).index(mem_type))
```
- CONTEXT는 인덱스 8 → **conf 0.45면 0.81** (FACT 0.78보다 높아 항상 이김!)
- 그래서 **DEFAULT는 conf 0.30** (→ 0.54) — 실제 어미 매치가 항상 이기게
- 이 공식 때문에 "낮은 conf DEFAULT"가 필수. 동일 함정 주의.

### 4) 영어 패턴 `\b` → ASCII 경계 변환 (②번 수정, 2026-09-27)
```python
# 변경 전: \berror\b  (Python \b = 유니코드 \w 기준, 한글 포함)
# 변경 후: (?<![A-Za-z0-9_])error(?![A-Za-z0-9_])
```
- **문제**: Python 3 `\b`는 유니코드 `\w`([a-zA-Z0-9_] + 한글 포함) 기준. 그래서 `error가`에서 `r`과 `가` 사이가 경계가 아니어서 **`\berror\b` 매치 실패** → 한글 조사가 붙은 영어 키워드가 전부 미분류.
- **해결**: ASCII 문자([A-Za-z0-9_]) 기준 경계로 교체. `error가`는 `error`(ASCII) 뒤 `가`(비-ASCII) → 경계 성립.
- **변환 규칙**: `\b(` → `(?<![A-Za-z0-9_])(`, `)\b` → `)(?![A-Za-z0-9_])`, 나머지 단독 `\b`는 양쪽 경계로.
- **부분일치 방지 유지**: `xerror`, `errors`, `some_error_value`는 여전히 매치 안 됨 (검증 완료).

### 5) 관계 패턴 동사 정밀화 (②번 보완, 2026-09-27)
ASCII 경계 변환 후 "Technical Lead**이자**"의 **Lead**(직책명사)가 관계 패턴
`(manages?|reports?\s+to|supervises?|leads?)`에 매치되어 **relationship 오분류 36건** 발생
(라이브 DB 818건 재분류에서 확인). 동사형만 매치하도록 엄격화:
```python
# 변경 전
(manages?|reports?\s+to|supervises?|leads?)
# 변경 후
(manages?\s+(the|a|an|this|that|project|team|group|repo|department|company|org)
|reports?\s+to
|supervises?\s+(the|a|an|this|that|project|team|group|department)
|leads?\s+(the|a|an|this|that|project|team|group|repo|department|company|org)
|led\s+(the|a|an|this|that|project|team|group|repo|department|company|org))
```
- `leads the project` → relationship, `Technical Lead` → relationship 아님 (직책명사).
- **다른 영어 단어도 한글 인접 시 명사로 오인될 수 있음** (예: `manage` vs `manager`) — 새 패턴 추가 시 동사형 제한 원칙 적용할 것.

---

## 검증 (2026-09-27)

- 한국어 케이스: **39/39 PASS** (의문/지시/단정/격식/겹받침/짧은 한국어 전체)
- 영어 회귀: **13/13 유지** (기존 패턴 불변)
- 한-영 혼용 (②번 추가): **3/3 PASS** (`파일 error가 났어`→error, `error가`→error, `이 버그는 middleware 버그야`→context)
- 라이브 DB 24h 36건 재분류: 잘못된 fact 3건(좋아 진행해줘) → context 수정, 의미 일치 확인
- 라이브 vs 재적용 스크립트: **40/40 일치**, 패턴 수 99 동일
- J1 lane/fallback/runtime: 영향 없음 (memory_type 미사용)

### ②번 수정 후 라이브 DB 전체 재분류 회귀 (818건, 2026-09-27)
| 항목 | 결과 |
|---|---|
| 관계 패턴 정밀화 전 | 44건 변경 (relationship 오분류 36건 포함) |
| 관계 패턴 정밀화 후 | **8건만 변경, 전부 설계 의도대로** |
| 남은 8건 | `timeout`→error, `failure`→error, `objective failure`→error, `patch`→error, `verify`→instruction, `README`→artifact ×3 |
| 관계 패턴 정밀화 효과 | relationship 오분류 36건 → **0건** |

---

## ①③번 실험 결과 (2026-09-27) — 적용 보류

### 실험 내용
- **①번**: 한글 어휘 패턴 추가 (`오류|에러|버그|실패|장애`→ERROR 0.75, `파일|폴더|디렉토리|경로`→ARTIFACT 0.70)
- **③번**: score 공식 `conf × (1+0.1×index)` → **`conf`** (B안) + 동률 tie-break `_TYPE_TIE_ORDER`

### 결과 (라이브 DB 821건 재분류)
**①③ 동시 적용 시 179건(21.8%) 변경 — 대규모 회귀.**

| 변경 | 건수 | 원인 |
|---|---|---|
| context → fact | 97 | **score=conf에서 FACT 어미(0.70~0.80)가 CONTEXT 어미(0.55~0.72)를 광범위하게 이김** — "~했어/~낫겠어/~맞아?" 같은 구어체가 fact로 몰림 |
| relationship → fact | 35 | 기술직함 "Technical Lead이자" 등이 relationship(동사형 제한 후 매치 안 됨) → FACT 어미에 밀림 |
| context → error | 17 | ①번 "오류/버그" 어휘가 일반 대화에 과매치 |
| error → fact | 11 | ①③ 결합으로 error 어휘가 FACT 어미에 밀림 |
| 기타 | 19 | instruction/goal/artifact 등 |

### 결론
- **③번 B안(score=conf)은 기존 conf 값들과 충돌**: 현재 conf들은 "enum 가중치와 함께 동작"하도록 설계됨 (FACT는 index 0으로 불리, CONTEXT는 8로 유리 → 이 균형이 어미 타입 분포를 유지). B안 적용 시 **한국어 어미 conf 전면 재조정**이 선행되어야 함.
- **①번 단독**은 일부 개선(한글 어휘 분류)이 있으나, ③번과 결합 시 회귀가 압도적.
- **적용 여부: 보류** (②번만 유지). 추후 ①번만 단독 재검토 가능.

### 복원 상태
- `typed_memory.py` = `bak-relfix`(②번 적용본)로 복원됨 — **라이브는 ②번만 적용**
- 스크립트 `reapply_korean_classifier.py`에 ①③ 코드(`_KO_LEXICON`, `_SCORE_OLD/NEW`, `_TIE_ORDER_BLOCK`)는 **탑레벨 정의로 남겼으나 apply_patch에서 미사용** — NOTE 주석으로 보류 표시

---

## "어미 conf 재조정 + ①③" 이득 분석 (2026-09-27) — 부정적

### 질문
B안(score=conf) 회귀를 한국어 어미 conf 재조정으로 상쇄하면 이득이 있는가?

### 실측 근거

**1. 현재(②번) 한국어 어미 오분류: 0건**
- `~했어/~줘/~자/~세요` 끝 → FACT로 분류된 것: **0건**
- `~다/~습니다/~니다` 끝 → CONTEXT로 분류된 것: 18건이지만 **전부 `[codex session] task:` 프리픽스가 있는 지시문** — 어미 문제가 아니라 프리픽스 분류 우선 (고칠 대상 아님)

**2. B안 회귀 132건의 실제 원인 (패턴 분석)**
| 원인 | 건수 | conf 재조정으로 해결? |
|---|---|---|
| 문장 중간 `했다/있다` (ㅆ+다, conf 0.74) 매치 "호출했**다가**" | ~46 | ❌ 앵커 문제 (문장 끝 `$` 부재) |
| `[task:]` 지시문 중간 `~습니다`(0.80) 매치 | ~13 | ❌ 앵커/문맥 문제 |
| `version\|v \d+`(0.9) 경로 숫자 매치 | ~25 | ❌ 영어 패턴 — 어미와 무관 |
| 기타 (ㄴ다/ㅄ다/ㅎ다/ㅂ다) | ~15 | ⚠️ 일부만 |

**3. 재조정 최선안(문장 끝 앵커 + CONTEXT conf 0.80) 시뮬레이션**
- 변경: **71건** (ctx→fact 28, error→context 11, error→fact 8, fact→context 7, relationship 5...)
- **error 20건 유실** (CTX 0.80이 ERROR 어휘 0.75를 이김)
- 남은 ctx→fact 28건도 전부 `[codex session] task:` 지시문 — 재조정으로 해결 불가

### 결론
- **손익: 예상 개선 0건 vs 예상 회귀 71건 → 순손실**
- 고칠 실제 오분류가 없는데 회귀 리스크만 추가됨
- B안 회귀는 conf 숫자가 아니라 **패턴 구조(문장 끝 앵커 부재, 영어 패턴 과매치, 지시문 프리픽스)** 문제 — 별개 수정(④안: FACT 어미에 `$` 앵커 + version 패턴 경로 제외)이 선행되어야 의미가 있음
- **권고: ①③+어미 재조정 모두 보류.** ④안(구조 수정)을 원하면 별도 설계 후 실험 가능

---

## ④번 (F1/F2 구조 수정) — 2026-09-27 **적용 완료**

### 내용 (conf 변경 없음, 패턴 구조만 수정)

**F1 — 한국어 종결형 FACT 어미 10개에 `(?![가-힣])` 후방차단**
- 대상: `f"[{_KO_FIN_SS}]다"` 등 `_KO_STATEMENT`의 10개 패턴 (ㅆ/ㅄ/ㄵ/ㄴ/ㄹ/ㅎ/ㅂ+다, ㅁ/ㅂ/ㅇ+니다)
- 배경: 종결형인데 `$` 앵커가 없어 "했**다가**", "있**다면**", "합니다**만**" 같은 **문장 중간에도 매치** → 사실(FACT)로 오분류
- 효과: "했다." / "했다\"" / 문장 끝은 **유지**, "했다가" 등 한글 연속은 **차단**
- (`[가-힣]+(이다|ㄴ다)$` 패턴은 이미 `$` 앵커가 있어서 제외)

**F2 — `(version|v)\s*\d+\.?\d*`에 `(?![A-Za-z0-9_-])` 후방차단**
- 배경: "deepseek-**v4**-flash" 같은 **모델명의 v4**가 version 패턴(FACT 0.9)에 매치 → 실험 메모 전체가 fact로 오분류. 실제 823건 중 4건이 이 원인.
- 효과: "버전 v2.1", "v2 API" 등 정상 표기는 **유지** (뒤가 공백/문장 끝), "v4-flash"는 **차단**

### 라이브 검증 결과 (823건 A/B)
**변경 7건 — 전부 fact→context, 회귀 0건**

| 변경 | 건수 | 내용 |
|---|---|---|
| fact → context | 7 | 의문/제안 3건 ("호출돼?", "어떻게 해결해야 해?", llm-as-a-verifier URL) + **v4 모델명 오매치 4건** (pi 0.84.2·camelAI 실험 등) |

기여도 분리: **F1 단독 3건, F2 단독 4건** (겹침 없음).

목표 케이스 스모크: "했다가"→context ✅, "했습니다만"→context ✅, "버전 v2.1"→fact 유지 ✅, "했다."→fact 유지 ✅, 한국어/영어/혼용 스모크 15/15 ✅

### 재적용 통합
- `reapply_korean_classifier.py` **step 2.7**로 ④번 통합 (f4_patch.py import)
- `scripts/f4_patch.py` — F1/F2 적용 함수 (라인 단위 처리, 멱등성: 이미 적용 시 0/0, 미적용 시 10/1)
- 업데이트로 덮어써지면 스크립트 재실행으로 ②+④ 복원 가능

---

## 업데이트 대비 — 재적용 방법

Mnemosyne 업데이트가 `typed_memory.py`를 덮어쓰면:

```bash
cd C:\Users\mandu\hermes-made\jev-memory-middleware
.venv\Scripts\python.exe scripts\reapply_korean_classifier.py
# Hermes 설치 venv 자동 탐색 → 패치 + 스모크 검증
# 이미 적용됨 → 검증만 실행
```

- **자동 백업**: `typed_memory.py.bak-ko-classifier`
- **검증 실패 시**: 백업 복원 + 수동 점검
- **동작**: 원본의 `TYPE_PATTERNS = [` → `_EN_PATTERNS = [` 이름 변경 + KO 블록 주입 + `TYPE_PATTERNS = _EN_PATTERNS + KO` 병합
- ⚠️ 업데이트로 파일 구조가 바뀌면(앵커 `CONFIDENCE_BOOSTERS: Dict...` 또는 `TYPE_PATTERNS: List... = [` 사라짐) 스크립트가 명시적 에러를 내고 중단 — 그때 이 문서를 보고 수동 대응.

---

## 파일 목록

| 파일 | 역할 |
|---|---|
| `scripts/reapply_korean_classifier.py` | 패치 재적용 + 검증 (업데이트 대비) |
| `docs/korean-classifier-patch.md` | 이 문서 |
| (라이브) `.../venv/Lib/site-packages/mnemosyne/core/typed_memory.py` | 패치 적용됨 |

## 스킬

`mnemosyne-korean-classifier` 스킬로 등록됨 — 업데이트 시 재적용 절차 참조.