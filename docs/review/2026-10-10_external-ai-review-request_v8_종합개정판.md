# 외부 AI 검토 요청서 v8 — 종합 개정판 (2026-10-10)

> **이력**: v1(10-06) → v2(abstain 무력) → v3(사안 1~5) → 3-AI 검토 → v4(10-07 개정) → v5(보완) → v6(사안별 배경 전면 명시) → **v7(10-07, 보류 6건 + 후속 실측)** → **v8(본 문서, v7 이후 신규 사안 7건 + 전 사안 최신 상태)**
> **성격**: v7 전송 이후 (10-08~10-10) 발생한 신규 실측·사고·판정을 모두 수집. 각 사안에 대해 ① 어떤 AI가 ② 무엇을 제안했고 ③ 어떤 실측을 거쳐 ④ 현재 어떤 상태인지를 자족적으로 서술. **추가 정보 없이 답변 가능**하도록 구성.
> **작성일**: 2026-10-10 (토)

---

## 0. 시스템 요약 (v8 기준)

| 항목 | 값 |
|---|---|
| 저장소 | SQLite `mnemosyne.db` (스냅샷 1,721+113행, 10-06 동결) |
| 임베딩 | bekko-a8m 384d (운영) |
| 검색 | 4-lane RRF(FTS5+vec+importance+graph) → 어휘 게이트 (1,0.0) → **pool 60** |
| rerank | JEV choice 1콜 — "최고 증거 1개 선택" + abstain 라벨 cN |
| excerpt | 쿼리 인지 300자 윈도우 → 150자 절단 (win-300, 10-06 채택) |
| soft gate | abstain_p > 0.3 → 빈 컨텍스트 (10-06 도입, 10-07 부분 발동 확인) |
| 노출 | `rows[:5]` Top-5 (사안 A 대상) — **운영은 k=5 유지 중** |
| 평가 | op-90 (gold 회수) / noans-50 (hard) / live-60 (사람 라벨) — 스냅샷 고정 |
| 소비 모델 | deepcombo (9router 로컬, Hermes 메인) |
| 판정 모델 | **tokenharbor/claude-haiku-5.5:free** (10-10 표준 확정 — 사안 L) |
| 실험 원칙 | 같은 세션 paired 3-run + production-exact pool + **소량 검증 → 전체 실행** |

### v7 이후 주요 변동 (10-08 ~ 10-10)

| 날짜 | 사건 | 비고 |
|---|---|---|
| 10-08 | 점수 융합(α) 보류 확정 | stage100/101 |
| 10-08 | 한국어 지시문 A/B — 무차이 | stage102 |
| 10-08 | opencode zen 인증 조사 | FreeTierError |
| 10-09 | AnchorMind·agentmemory·Honcho·mem0·OptMem 검토 | 전부 직접 반영 없음 |
| **10-09 12:05~12:07** | **데몬 30h 부재 사고 시작** (gateway python 변경 + PC 종료) | 사안 G |
| 10-10 | tigerless·MemPalace·sift·synix 검토 + 서베이 | 사안 M |
| **10-10** | **LongMemEval-S 500문항 실행** — Full 24.1% | 사안 H |
| **10-10** | **stage104 프레이밍 페어드** — fF 유지 확정 (p=0.0078) | 사안 C |
| **10-10** | **stage107/108 k=3 3-run** — 보류 (flip 59%) | 사안 A |
| **10-10** | **shadow enforcement 판정** — gate 정상 | 사안 I |
| **10-10 17:46** | **데몬 재기동 + 플러그인 폴백 적용** | 사안 G |

---

## 사안 A: 노출 k (v7 보류 → **k=3 재실측 → 방법론 한계 노출**)

### 출처
- **A AI** (v3): "실노출 `rows[:5]`→`rows[:2~3]` 축소" 제안
- **B AI** (v4): "hit@k k=2=k=5 — 노출 축소 실측 지지" + "FP 감소는 미보장" 경고
- **B AI** (v6): "k=2/k=3 소비 QA 재론" 예측

### 실측 과정 (v7까지)
1. **stage57 (0콜)**: op-90 base choice lift 후 hit@1 79 / hit@2 80 / hit@3 80 → k=2로 줄여도 hit@2=80 (손실 0). 무관 노출 190행→76행 (-60%)
2. **stage87 (200콜, JEV)**: k=2/k=5 비교 — op hit@1 78=78, hit@3 79=79, noans FP 21/50 동일, block 노출 190→76 (-60%)
3. **stage93/94 (소비 2×2, 2026-10-07)**: **k=2 정답 활용 65.9% vs k=5 86.4% (−16pp)** → k=2 보류

### v8 추가 실측: stage107/108 — k=3 정답 활용 3-run (2026-10-10)
- **설계**: stage93과 동일 조건 (deepcombo 생성, claude-haiku 판정, JEV rows 재사용, framing OFF), 3회 반복
  | Run | 정답 활용 (yes/valid 22건) | block 인용 |
  |---|---|---|
  | run1 (stage107) | **86.4%** (19/22) | 23.7% (9/38) |
  | run2 (stage108) | **50.0%** (11/22) | 34.2% (13/38) |
  | run3 (stage108) | **77.3%** (17/22) | 39.5% (15/38) |
  | **3-run 평균** | **71.2%** | 32.4% |
- **flip 분석**: 3-run 모두 일치 9/22 (41%), flip 13/22 (59%) — yes→no→yes 7건, yes→yes→no 2건 등
- **원인**: deepcombo temperature 0.2 재생성 비결정성 + 판정 기준(정답 활용 여부)의 경계 모호

### 현재 상태
- **k=3 채택 보류** — 3-run 편차 ±18pp로 단정 불가
- **방법론 한계 노출**: k=2 vs k=5의 16pp 차이(65.9↔86.4)도 **1회 측정이었으므로 노이즈 범위일 수 있음**
- 현행 **k=5 유지** (변경 없음), 문서: `STAGE107_108_K3_ANSWER_UTIL_20261010.md`

### 판단 요청
1. **소비 QA 정답 활용률의 신뢰할 측정 방법** — 3회 생성 다수결(콜 3배)? 판정 기준 변경(응답-메모리 교차)? 온도?
2. k=2/k=5 기존 16pp 차이가 노이즈라면, **노출 축소(190→76행)의 가치를 정량화할 다른 지표**는?
3. **k=3 실험이 "재실측 가치 없음"인지** — 아니면 다수결 방법으로 재실측할 가치가 있는지?

---

## 사안 C: 소비 측 프레이밍 (v7 채택 후보 → **stage104 인용 저해 발견 → 보류 유지**)

### 출처
- **B AI** (v3) + **A AI** (v4): "블록 헤더 '참고용 메모리 — 직접 답이 아니면 무시'"
- **C AI** (v4): "소비 측 프레이밍은 메모리 경로 밖이라 원칙 충돌 없음"
- **3-AI v6**: 3/3 채택 방향 (2×2 실측 선행)

### 실측 과정 (v7까지)
- **stage93/94 (2×2 QA)**: framing ON 환각 **−44%** (23.7→13.2%), k=5 정답 활용 **+9.1pp** (77.3→86.4%) — 채택 후보
- **stage98 인간 감사**: 20% 합의율 100%
- **stage99 홀드아웃**: abstain 13건 동결 (framing 검증용)

### v8 추가 실측: stage104 — 프레이밍 페어드 (haiku 통일, 2026-10-10)
- **배경**: stage103(deepcombo 생성)이 ERR 19.4% 오염 → **생성·판정 모두 claude-haiku로 통일** (180쌍, ERR 0)
- **결과**: fF(무프레이밍) no 2.2% (4/180) vs fT(프레이밍) 6.7% (12/180)
  - **McNemar p=0.0078** — fF better 8 / fF worse 0 (8건 전부 fF 우세)
  - 모든 cls에서 fF 우세: yes −3.9pp, block −3.5pp, valid −13.3pp
- **해석**: "[직접 답이 없다면 무시하라]" 헤더가 모델의 메모리 활용을 억제 — **인용(활용) 측면에서 fT는 해로움**

### 현재 상태
- **운영 반영 보류 유지** — stage93/94(환각 −44%)와 stage104(인용 저해)는 **다른 지표**의 트레이드오프
- 환각 방어 vs 메모리 활용 — 사용자 결정 대기, 문서: `STAGE104_RESULT.md`

### 판단 요청
1. **환각 −44% vs 인용 저해(p=0.0078) — 운영 반영 가치 판단** (실사용 관점: 무답에서 덜 말하는 것 vs 답 있는 질문에서 덜 쓰는 것)
2. **헤더 문구 완화**(예: "직접 답이 없다면" 삭제 → "참고용")하면 인용 저해가 줄어드는가? — 실측 가치?
3. stage104의 k=2+fF 인용 97.8%는 **k=2 논쟁(사안 A)에 어떤 시사점**인가?

---

## 사안 D: 일일 canary (v7 활성 → **drift 감지 + 원인 미규명**)

### 출처
- **B AI** (v4): "고정 쿼리 30~40개 매일 실행 → abstain율·pick 분포 변화 감지"
- **3-AI v6**: "즉시 활성화 + 보강 4건" (L2_YES 센서·timeout 5s·abstain_p 카운트·pick drift)

### 구축 내역 (v7까지)
- cron `723c06e97a84` 매일 09:00, L1 일반지식 12콜 + L2 라벨 20콜 (무답 10 + 정답 10)
- 기준선 (10-07 INIT): L1 abstain 12/12 (일반지식 — 내 DB 부재라 상대 비교), L2 무답 0/10·정답 0/10 abstain

### v8 실행 결과 (10-08 ~ 10-10)
| 날짜 | 결과 | 비고 |
|---|---|---|
| 10-08 09:00 | 실행 실패 (rc=1, ReadTimeout) | 데몬 부재 전이라 JEV 타임아웃? |
| **10-09 09:25** | ⚠️ **L1 abstain_p>0.3: 0 → 12건** drift | 데몬 부재(12:07) **전** — 데몬과 무관 |
| **10-10 10:16** | ⚠️ 동일 drift 반복 (12건) | 데몬 부재 중 |

- **쟁점**: L1 쿼리는 "내 DB와 무관한 일반지식"이라 **abstain 12/12가 기본값**인데, abstain_p>0.3이 12건이 된 것은 **모델이 "답 없음"을 강하게 확신**하는 상태 변화
- 10-06~07의 abstain_p 상향 추세(stage88)와 연결 가능성

### 현재 상태
- drift 지속, **원인 미규명** — 모델 변경? L1 쿼리 특성? 기준선 미확립?

### 판단 요청
1. **L1 abstain_p>0.3 12/12 drift의 의미** — 모델 판정 경향 변화로 봐야 하나? 아니면 L1이 원래 abstain_p가 높은 쿼리 구성인가?
2. **canary drift에 대한 대응** — 이 drift를 어떻게 활용(경고 유지 / 임계 조정 / 쿼리 교체)?
3. 10-08 실행 실패(타임아웃)는 데몬 부재와의 연관이 있는가?

---

## 사안 F: abstain_p 상향 추세 (v7 보류 → **shadow 분석 추가 → τ 유지**)

### 출처
- **B AI** (v4): "라이브 데몬 trace 시계열 비교" → stage88에서 발견
- **3-AI v6**: 3/3 "τ 유지 + 실측 선행"

### 실측 과정 (v7까지)
- stage88: abstain_p 중앙 0.00→0.11, >0.3 7/38 (18%)
- stage95 (0콜): 정답군 (valid/yes) 132건 abstain_p>0.3 = **0건** (max 0.160) — τ=0.3 유지 근거
- stage96 라벨링: 발동 10건 = 과다거부 3·작업지시 6·정직거부 0 — **τ로 해결 불가 (모델 판정 문제)**

### v8 추가 실측: shadow_log 전수 분석 (10-10)
- shadow_log 770건 (10-04~10-09) 날짜별 gate 분포
  | 날짜 | query_log YES | NO | 해석 |
  |---|---|---|---|
  | 10-05 | 24% | 48% | 실험 밀집 (작업지시) |
  | 10-06 | 16% | 55% | stage20~48 실험 |
  | 10-07 | 7% | 58% | 실험 최대 밀집 |
  | 10-08 | 49% | 27% | 실험 종료 후 정상화 |
- **op-snapshot (gold 90건)**: YES 81/90 (90%), NO 4건 (4%) — **답 있는 질문은 96% 통과**
- hermes 대화 쿼리 NO 56% (284/508) — 대부분 작업지시 ("좋아 진행해줘", "1번부터 진행해보자")
- → **gate NO 41.7%는 "과다거부"가 아니라 "작업지시/대화의 정상 거부"** 로 판정

### 현재 상태
- **τ=0.3 유지** (과다거부는 τ 조정으로 구제 불가 — stage96)
- 일일 요약 경고 2건(gate NO율 30%+, R2 abstain 30%+)은 **오경보 판정** (위 근거)

### 판단 요청
1. shadow 분석의 "NO는 작업지시 거부" 판정 — **동의?** (gold 96% 통과가 결정적 근거)
2. canary L1 drift(사안 D)는 **τ 재조정의 근거가 될 수 있는가?** 아니면 L1 특성상 정상인가?
3. shadow 경고 임계값(30%)을 **상향 조정**(예: 50%)하는 것이 타당한가?

---

## 사안 G (신규): 데몬 30h 부재 사고 — 복구 완료, 재발 방지 검증 (2026-10-09~10)

### 사건 (실측 타임라인)
| 시각 | 사건 | 근거 |
|---|---|---|
| 10-09 11:55 | 데몬 로그 마지막 기록 | core.out.log |
| 10-09 12:01 | Hermes 게이트웨이 재시작 (플러그인 재등록) | agent.log |
| **10-09 12:05:30** | **`Hermes_Gateway.cmd`/`.vbs`가 tools python(3.14.7) 경로로 변경** | 파일 mtime |
| 10-09 12:07:34 | PC 종료 (6006) | 이벤트 로그 |
| 10-10 10:14 | PC 재부팅 → 게이트웨이가 tools python으로 시작 | 6005 |
| 10-10 10:14~17:46 | **"Memory provider 'jev-mem' loaded but no provider instance found" 반복** | agent.log |
| 10-10 17:46 | 데몬 수동 재기동 → 정상 | 포트 47821 LISTEN |

### 근본 원인
1. **Hermes 설치/업데이트가 gateway 실행 파일을 tools python(3.14.7)으로 재생성**
2. tools python엔 `mnemosyne_hermes` 미설치 → jev-mem 플러그인(`harnesses/hermes_j1.py`)의 `from mnemosyne_hermes import ...` **ImportError**
3. provider 인스턴스 미생성 → **JevMemClient(auto_start=True)가 spawn 시도 자체를 못 함**
4. 결과: 30시간 동안 **JEV rerank 없는 운영** + query_log/shadow 기록 중단

### 복구 (1+3 병행)
| 방식 | 내용 | 성격 |
|---|---|---|
| 1. cmd/VBS 수정 | tools python → Hermes 정식 venv (`installs/.../099e00aba.../venv`) | 즉시 복구 (백업 `.bak-20261010`) |
| 3. 플러그인 폴백 | `hermes_j1.py`에 `_ensure_mnemosyne_hermes()` — import 실패 시 `installs/*/environments/*/venv/Lib/site-packages` **glob 탐색** + sys.path 추가 | **영구 방어선** (업데이트로 venv hash 변경에도 자동 추적) |

### 검증 (실증)
- 18:19 게이트웨이 venv python으로 재기동 (PID 17228)
- **18:31:47 `Memory provider 'jev-mem' activated`** (agent.log)
- 18:31:49 이 대화 "확인했어?"가 **query_log에 기록** — 데몬 경유 동작 실측
- 데몬 LISTENING(47821), health 정상, 문서: `STAGE106_DAEMON_OUTAGE_20261010.md`

### 판단 요청
1. **플러그인 폴백(glob 탐색, 최신 mtime 우선)의 견고성** — 멀티 venv 혹은 잘못된 venv 선택 위험?
2. **30h나 지속된 근본 문제 = 모니터링 부재** — shadow 기록 중단으로 발견했지만 30h 소요. **알림 체계**(예: daily 요약에 "데몬 부재" 감지 추가)가 필요한가?
3. tools python 사용 자체가 Hermes 신규 설계라면, **플러그인 폴백 외에 더 근본적 해결책**이 있는가?

---

## 사안 H (신규): LongMemEval-S 500문항 — JEV read-path 구조적 한계 (2026-10-10)

### 실측 설계
- 벤치: LongMemEval-S (ICLR 2025) 500문항, `longmemeval_s_cleaned.json`
- 파이프라인: ingest → JEV choice 1콜/문항 → deepcombo reader → deepcombo judge
- Full(전체 haystack) + Oracle(evidence 세션만) 2모드, JEV 500콜 (일일 무료 2.1%)

### 결과
| 지표 | Full | Oracle | Δ |
|---|---|---|---|
| **전체 정확도** | **24.1%** (119/494) | **25.1%** (123/491) | +1.0pp |
| abstention (30) | 100% | 96.7% | −1건 |
| single-session-user (70) | 51.4% | 54.3% | +2.9pp |
| single-session-preference (29) | 31.0% | **46.7%** | +15.7pp |
| knowledge-update (76) | 26.3% | 24.3% | −2.0pp |
| multi-session (133) | 9.0% | 9.8% | +0.8pp |
| temporal-reasoning (133) | 9.0% | 8.3% | −0.7pp |
| JEV abstain | 52% | 55% | +3pp |

### 해석 (실측 기반)
1. **oracle(evidence 세션 완벽 제공)에도 25.1%** → "pool에 답 없음"이 아니라 **JEV choice가 답 있는 메모리를 usable evidence로 인정 안 함** (판정 단계가 근본 원인)
2. abstain 261건 중 top-5에 정답 흔적 49건(19%)뿐 → abstain 임계 조정 상한 ≈ +49건 (24.1→~34%)
3. multi-session·temporal-reasoning은 oracle에서도 9% — **단일-best pick 구조의 한계** (답이 여러 세션 분산/시간 합성 필요)
4. abstention 100% (Full) — **정직 거부는 우리 설계 강점 유지**
5. 라이브 환경 차이: 라이브 abstain 7% vs 벤치 52% (filler 중심 haystack) — **JEV는 "답이 단일 메모리에 있는" 라이브에 최적화**

### 재판정 실측 (stage116/117, 2026-10-10 — "판정 모델이 문제" 가설 검증)
| 판정 모델 | 정확도 | 비고 |
|---|---|---|
| deepcombo (기존) | 24.1% | 문서 결과 |
| claude-haiku (재판정) | 18.6% | abstention 규칙 없음 (29/30 no) |
| claude-haiku (abstention 보정) | **23.0%** | 규칙 추가 (28/30 yes) |
| **두 모델 일치율** | **97.2%** | 보정 후 |

- **가설 기각 확정**: 판정 모델 교체로는 점수가 오르지 않음 — **24%는 진짜 read-path 한계**
- abstention 보정 후 no 2건은 실제 오답 (거부 없이 지어냄) — 판정 품질 정상
- 문서: `STAGE116_LMEV_REJUDGE_20261010.md`

### 현재 상태
- **read-path 구조 변경 불가 판정** (JEV choice 단일-best — 운영 회귀 위험, 사용자 원칙상 보류)
- 벤치 선택 조정: LongMemEval은 추출형/단일 메모리 중심이라 JEV read-path 평가엔 부적합 → **향후 라이브 쿼리 기반 회귀 셋 지향**
- 문서: `docs/longmemeval/2026-10-10_longmemeval-results.md` + `STAGE116_LMEV_REJUDGE_20261010.md`

### 판단 요청
1. **"JEV choice 단일-best가 합성/시간 추론에 구조적 한계"** — evidence aggregation 같은 rerank 구조 변경 가치? (운영 회귀 vs 벤치 개선)
2. abstain 임계 조정(0.3→0.5) 상한 +49건 — **라이브(abstain 7%)에서도 유효한가?**
3. 벤치 방향(라이브 회귀 셋 / abstention 포함 단일-세션 벤치) — 추천?

---

## 사안 I (신규): shadow enforcement 판정 완료 — gate 정상, enforcement 불필요 (10-10)

### 배경
- shadow 배치: 10-04 구축, cron 10분 (`921cdb47edf2`) + 일일 요약 09:00 (`0295b127ee8e`)
- 목적: 라이브 쿼리로 JEV rerank shadow 실행 → gate YES/NO/ABSTAIN + R2 갈림률 축적 → **enforcement 판정** (3~5일 데이터)

### 실측 (10-10, shadow_log 770건 전수 분석)
1. **소스별 gate 분포**
   | 소스 | YES | NO | ABSTAIN | 해석 |
   |---|---|---|---|---|
   | op-snapshot (gold 90건) | 81 (90%) | 4 (4%) | 5 (6%) | ✅ **gold 96% 통과** |
   | query_log-hermes | — | 284/508 (56%) | — | 작업지시 거부 (정상) |
   | query_log-opencode | — | 14/115 (12%) | — | 정보 질문 통과 |
   | '?' (20건, 과거) | 2 | 10 | 8 | 10-05 버그 정리 전 |
2. **R2 결정**: inject 258 / abstain(gate-NO) 321 / A-abstain 157 → gate-NO는 대부분 작업지시
3. **오류 33건 (4.3%)**: 429 25 + 502 4 + 503 4 — JEV API 일시적
4. **assistant 오염 14.8%** (86/580) — 10-05 [ASSISTANT] 제외 해제 후 정상 수준
5. **부수 발견**: 데몬 부재(10-09 12:07)로 기록 중단 — 사안 G의 발견 경로

### 현재 상태
- **enforcement 불필요 판정** — shadow는 운영과 동일 파이프라인이라 "판정 후 반영" 개념 없음 (관찰용)
- **90일 보존 정책 추가** (10-10): `shadow_daily_summary.py`에 매일 90일 초과 shadow_log/query_log 자동 삭제
- 문서: `STAGE105_SHADOW_ENFORCEMENT_20261010.md`

### 판단 요청
1. shadow 배치(10분) + 일일 요약 **유지 vs 중단** — 회귀 감지용 가치? (비용≈0, 이번 사고도 이걸로 발견)
2. 90일 보존 기간 — 적정?
3. **gate NO 41.7%의 "작업지시 거부" 판정에 동의?** (gold 96% 통과 근거)

---

## 사안 J (신규): 점수 융합(convex α) — 보류 확정 (10-08, stage100/101)

### 출처
- (외부 검토 중) fusion 제안 — stage100 0콜 시뮬에서 α=0.7 gold rank1 +6(44→50) 유망

### 실측
- **stage100 (0콜 시뮬)**: fusion α=0.7 op-90 gold rank1 44→50 (+6) — 유망
- **stage101 (400콜, same-session paired)**: op hit@1 78→80(+2)·hit@3 79→82(+3)·abstain 2→0, noans FP 21→22(+1)
- **stage101b (0콜 탐색)**: 조건부 α의 운영 신호 분리 불가 (top1 lane 구성·쿼리 단어 무변별)
- **프로세스 간 재현 노이즈 발견**: pool 순서 ±1~2 rank (fastembed ONNX 세션 차이 추정) — flip 8건은 8/8 일치로 결론은 견고

### 현재 상태
- **보류 확정** (2026-10-08) — 코드 미반영. flip +5/−3 = 순 +2가 재현 노이즈 범위인지 단정 불가
- 재검토 트리거: noans 방어 개선된 α 후보 또는 조건부 신호 발굴 시

### 판단 요청
1. **+2~3 이득이 재현 노이즈(±1~2 rank) 범위인지** — 재실측 가치?
2. noans FP +1 상쇄 방법 (fusion과 프레이밍/다른 레버 병행)?

---

## 사안 K (신규): 한국어 지시문 A/B — 무차이, 종결 후보 (10-08, stage102)

### 출처
- 외부 6편: '한국어 지시문 우위' 주장

### 실측
- **stage102 (400콜, same-session paired)**: op hit@1/3·abstain **완전 동일** (77/86·78/86·2), flip 0건, noans FP 24→23 (−1, 잡음)
- 한국어 지시문은 라이브 데이터에서 **무차이·무손해**

### 현재 상태
- **코드 미변경 — 현행 영어 유지**, 문서: HANDOFF (STAGE102 행)

### 판단 요청
1. **최종 종결로 확정**해도 되는가? (재실측 불필요?)
2. FP 2건이 과거사 질문에 몰린 패턴(n=5) — 추적 가치?

---

## 사안 L (신규): 판정 모델 표준화 — claude-haiku-5.5:free 확정 (10-10)

### 경위
| 모델 | 경로 | 결과 | 상태 |
|---|---|---|---|
| space-bunny 등 | opencode zen | FreeTierError (내부 전용, #49621) | 기각 |
| qwen3.8-flash-next-uncensored | Experlabs | 503/429 반복 (provider 지연) | 보관 |
| deepseek-v4.1-flash:free | 9router | 57초/콜 (느림), tokenharbor만 동작 | 중지 |
| **tokenharbor/claude-haiku-5.5:free** | 9router | **6.3초/콜, ERR 0, 배치 5건 OK** | **표준 확정** |

- opencode zen: "OpenCode's free tier can only be used from within OpenCode" — TLS/클라이언트 지문 게이트 (공식 이슈 #49621, 바이트 재생도 403). space-bunny-free만 UA 무관 200 (zero-retention 예외)
- 로컬 server API (127.0.0.1:49374, Basic opencode:service.json pw + x-opencode-ticket:1)로는 세션 생성→SSE 응답 가능 (CLI 스폰 없음)
- **9router의 tokenharbor/claude-haiku-5.5:free**: 1074건 판정 실증 (10-10) — 배치 5, 2워커, ERR 0, 품질 우수

### 현재 상태
- **판정 파이프라인 표준**: 생성·판정 모두 claude-haiku (STAGE104 이후 확정)

### 판단 요청
1. 판정 모델 표준(haiku)에 **동의?** (골드 판정용으로 충분한 품질?)
2. opencode zen은 **재시도 가치 없음으로 종결**?

---

## 사안 M (신규): 외부 메모리 시스템 리뷰 6건 종합 (10-08~10-10, 0콜 소스 대조+실측)

> v7 이후 타 세션에서 진행된 외부 시스템 리뷰. 모두 "직접 이식 없음"으로 종결.
> 외부 AI들이 판단할 사안은 아니나 **참고용으로 포함** (검토서가 전체 현황을 담기 위함).

| 시스템 | 판정 요약 | 문서 |
|---|---|---|
| **AnchorMind** (10-08) | ❌ 형태소 보조 벡터 기각 — pool miss 4/90에서 0/4 구제 (한영 미스매치·과단축·의역이 miss 원인) | `2026-10-08_anchormind-review.md` |
| **Honcho** (10-08) | 대척 설계, 직접 반영 없음 — RRF k=60 정합 + 보류 3건 (surprisal·모순 감지·...) | `2026-10-09_honcho-review.md` |
| **mem0 아티클** (10-09) | ❌ timestamp 노출 기각 (0콜 DB 프로브: supersede 113건+valid_until 159건으로 이미 차단) | `2026-10-09_mem0-review.md` |
| **OptMem** (10-09) | ⏸️ 보류 — age-aware exposure (세대별 노출 밀도)만 미실측 축, 코퍼스 2,085행은 시기상조 | `2026-10-09_optmem-review.md` |
| **agentmemory** (10-09) | ⏸️ 보류 4건 실측 종결 — 강등·자동 supersede 기각, retention evictable 0, slots=프레이밍 통합 | `2026-10-09_agentmemory-review.md` |
| **tigerless** (10-10) | ❌ recall_count boost 기각 (상위 행 도배 군집+자기 강화 루프) · ⏸️ Manage 레이어 보류 | `2026-10-10_tigerless-agent-memory-review.md` |
| **MemPalace** (10-10) | ✅ 정합 2 · ❌ 기각 4 (convex 퓨전·dedup delete·dynamics decay·temporal boost) · ⏸️ 보류 1 | `2026-10-10_mempalace-review.md` |
| **sift** (10-10) | ✅ 정합 2 · ❌ 기각 2 · ℹ️ 참고 2 | `2026-10-10_sift-review.md` |
| **synix 8-agent-memory** (10-10) | ✅ 정합 1 · ℹ️ 참고 5 · ⏸️ 보류 1 | `2026-10-10_synix-agent-memory-review.md` |
| **생태계 서베이** (10-10) | 24개 저장소 서베이 — 추적 대상 식별 | `2026-10-10_memory-ecosystem-survey.md` |

**공통 패턴**: 외부 시스템의 개별 메커니즘은 대부분 ① 우리 실측(단일-best choice·do-not-re-run 원칙)과 충돌하거나 ② 코퍼스 규모(2,085행) 대비 시기상조 → **직접 반영 없음**

### 판단 요청
1. 이 리뷰들은 **"참고 종결"로 두고 재검토 불필요**로 확정해도 되는가?
2. **tigerless recall_count boost 기각**(자기 강화 루프) — 우리 read-path 설계(도배 방지)와 일치하는 판정인지 교차 확인?
3. 생태계 서베이에서 **추적 가치가 있는 신규 축**이 있는가? (SQLite Vec1 ANN, sqlite-multiwriter 등)

---

## 부록 A: v7 확정·기각 사안 (재검토 불필요 — 상태 유지 확인)

| 사안 | 상태 | 비고 |
|---|---|---|
| B (IDF v2) | ❌ 기각 확정 | 발동 1.7% (stage90) |
| E (pool20) | ❌ 영구 종결 | 3/3 합의, 재오픈 조건 명시 |
| abstain 라벨 문구 | ✅ current 동결 | stage45 |
| 스냅샷 고정 | ✅ 채택 | 10-06 |
| gemma2 교체 | ❌ 기각 | bekko 유지 |
| 게이트 재정렬 | ❌ 기각 | stage80~82 |
| noul 구조 | ❌ 기각 | stage29~37 |
| excerpt 윈도우 | ❌ 기각 | stage47a~h |
| 허브 다운웨이트 등 | ❌ 기각 | stage57~59 |
| 후보 수 abstain 유도 | ❌ 기각 | stage84 |
| 2질문 분리 | ❌ 기각 | stage89~92 |

## 부록 B: raw 자료 (전부 커밋·푸시됨, `mandutt/jev-gatemem`)

| 파일 | 내용 |
|---|---|
| `STAGE104_RESULT.md` · `STAGE105_SHADOW_ENFORCEMENT_20261010.md` · `STAGE106_DAEMON_OUTAGE_20261010.md` · `STAGE107_108_K3_ANSWER_UTIL_20261010.md` | v8 사안별 상세 |
| `docs/longmemeval/2026-10-10_longmemeval-results.md` | 사안 H 상세 |
| `data/stage107_k3_answer_util{,_judge}.json` · `data/stage108_k3_run{2,3}{,_judge}.json` | 사안 A raw |
| `data/stage104_paired_haiku{,_judge}.json` | 사안 C raw |
| `data/stage102p_judge_claude.json` (+supplement) | 판정 1,074건 raw |
| `canary_log.jsonl` | 사안 D raw |
| `%LOCALAPPDATA%/jev-mem/core_state.db` (shadow_log) | 사안 F/I raw |
| `docs/review/2026-10-08~10_*.md` | 사안 M 상세 |
| `harnesses/hermes_j1.py` · `shadow_daily_summary.py` | 사안 G/I 코드 변경 |

---

## 요청 형식
사안별로 **① 판정 (채택/기각/수정/보류 유지) ② 근거 (실측 인용) ③ 권장 다음 단계 (콜·비용·실험 설계 포함)** 를 답변해 주십시오. 반대 의견 환영. 실측 신뢰성 한계 지적도 별도로 부탁드립니다. **각 사안은 (A AI/B AI/C AI 중) 특정 AI의 제안에서 출발했지만, 세 분 모두 전체 사안을 판단해 주시면 됩니다.**