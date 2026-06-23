# Glimi Community QA System — eval-driven, generational

> 자율 오너 에이전트가 커뮤니티를 **처음(온보딩)부터 끝까지 실제로 구동**하고, 그 세션을
> 여러 차원(온보딩·친구생성·대화품질·환각·누수·응답성)으로 채점해 **0–100 품질 점수**를 내고,
> 그 점수를 **git 세대(commit)별로 추적**한다. = *agent-driven eval harness with generational
> quality tracking* (eval-driven development / "eval flywheel").

이건 디스코드 기반 구판 QA(`tests/e2e/runner.py`·`test_user_bot.py`, **폐기**)의 후계 —
같은 목적("커뮤니티가 잘 도는가")을 **웹 기반·시스템화·포폴급**으로 다시 세운 것.

## 무엇을 검증하나 (차원)

각 차원은 0–10 점 + 가중치. 종합 = 가중평균을 0–100 으로 정규화. (`tests/e2e/qa_quality.py`)

| 차원 | 종류 | 가중치 | 무엇을 보는가 |
|---|---|---|---|
| `onboarding` | 구조 | 1.0 | 막 들어온 오너가 매니저(유나)한테 인사하고 오리엔테이션을 받는가 |
| `friend_creation` | 구조 | 1.5 | 오너 요청으로 **진짜 새 친구가 생성**되어 그 친구와 대화까지 이어지는가 |
| `conversation_quality` | LLM-judge | 2.0 | 친구 답이 사람처럼 자연·일관·맥락있게 좋은가 (5축: in_character/coherence/naturalness/engagement/no_meta) |
| `no_hallucination` | LLM-judge | 1.5 | 친구가 사실을 지어내거나 안 한 일을 했다고 하지 않는가 |
| `no_leaks` | 구조 | 1.0 | 메타(자신=AI 고백)·에러·도구블록 누수가 0 인가 |
| `responsiveness` | 구조 | 1.0 | 구동된 모든 DM 이 (서로 다른) 답을 받고 멈춤·오류가 없는가 |

**정직성 규칙**: LLM-judge 차원은 **실제 백엔드 + claude CLI 존재** 시에만 채점. `echo` 셀프테스트에선
SKIP(종합에서 제외) — 가짜 점수를 만들지 않는다.

> 차원은 의도적으로 확장형. 향후 `achievements`(도전과제 처리)·`group_chat`·`memory_recall` 등을
> 같은 패턴(`Dimension` + evaluator)으로 추가.

## 세대(generation)와 git 전략 — eval flywheel

**세대 = 한 commit 위에서 돈 한 번의 QA 평가.** 두 군데 저장 (`tests/e2e/qa_history.py`):

1. **SQLite** `tests/e2e/results/qa_history.db` *(gitignore)* — 풀 로그. 웹 대시보드 런 목록 + 트렌드용.
2. **커밋되는 JSON** `tests/e2e/qa_generations/gen-NNNN-<ts>-<sha>.json` *(git 추적)* — 세대별 작은 요약.
   각 파일은 **돈 시점의 git SHA** 가 박혀 있어, 품질의 변화가 git 에 그대로 남는다.

### flywheel 한 사이클
```
gen N  (develop@SHA1)  ──QA──▶  점수 S, 버그 B 발견 (예: friend_creation FAIL)
   │
   └─ fix/<B> 브랜치에서 B 고침  ──QA 재실행──▶  gen N+1, 점수 S′ > S
        │
        └─ 커밋 = 코드fix + gen N+1 JSON.  커밋 메시지에 점수 델타:
           fix(community): creator가 create_agent_profile 실제 호출
           qa: friend_creation 0→10, overall 68→79
        └─ PR → develop  (브랜치 전략은 CLAUDE.md 준수: feat/fix/* ← develop, PR base=develop)
```

### git 에 남는 것
- `git log -- tests/e2e/qa_generations/` → **측정된 품질 우상향 타임라인**.
- `git log --grep "qa:"` → 품질에 영향 준 모든 변경을 **점수 델타와 함께**.
- (옵션) 마일스톤 세대에 태그: `git tag qa-gen-10`.

이 자체가 포폴 멘트: *"품질을 git-추적 1급 메트릭으로 계측 — 모든 커밋의 제품 품질 영향이 측정·가시화."*

## 개발자 자아 = 오너 에이전트 (네 페르소나로 QA)

오너 에이전트(`tests/e2e/community_owner_agent.py`)는 **사람 오너의 대역**이다. 실제 개발자가
**자기 자아를 주입**해서 자기 커뮤니티를 QA 한다. env 로 설정:

```bash
export QA_OWNER_NAME="심재빈"      # 오너 본명 (기본: 심재빈)
export QA_OWNER_NICKNAME="재빈"    # 호칭/별칭
export QA_OWNER_AGE="29"           # 한국 나이
```

오너는 온보딩→친구 요청(매니저 유나 경유)→대화 순으로 **스스로 판단하며** 채팅 WS 를 구동한다.
no-meta 가드(자신이 테스트/시스템임을 절대 안 드러냄)가 걸려 있어 사람처럼 군다.

> **친구 생성 경로 주의**: 오너는 친구를 **매니저(유나)** 한테 부탁한다. 유나가 `request_dm` 으로
> 창작자(하나)에게 릴레이 → 하나가 `create_agent_profile` 로 생성. 오너가 하나한테 *직접* 세부를
> 따지면 Q&A 에서 stall (구판 회귀). 의도된 경로 = 오너→유나→하나.

## 실행

```bash
# 무료 셀프테스트 (echo, judge 생략, 플로우/구조 차원만)
GLIMI_LLM_BACKEND=echo .venv/bin/python -m tests.e2e.community_e2e --owner-agent --rounds 2 --qa

# 실측 세대 기록 (claude_cli, judge 포함) — 한 세대를 SQLite + 커밋용 JSON 으로 남김
GLIMI_LLM_BACKEND=claude_cli .venv/bin/python -m tests.e2e.community_e2e \
    --owner-agent --rounds 10 --qa --report

# 라이브 관전 (터널로 처음부터 보기) — 드라이브 시작 전 N 초 일시정지
./scripts/community_e2e.sh --owner-agent --rounds 10 --keep-serving --host 0.0.0.0 --watch-pause 180 --qa
```

격리 임시 DATA/COMMUNITIES dir + 비표준 포트 → 실데이터·je-empty(:8200) 무접촉.

## 코드 맵

| 파일 | 역할 |
|---|---|
| `tests/e2e/community_e2e.py` | 실 커뮤니티 서버 spawn + 오너 에이전트 드라이브 + `--qa` 훅 |
| `tests/e2e/community_owner_agent.py` | 개발자 자아 오너 에이전트 (온보딩→유나경유 친구요청→대화) |
| `tests/e2e/qa_quality.py` | **차원 정의 + 평가 + 종합 0–100 점수** |
| `tests/e2e/qa_history.py` | **세대 저장**: SQLite(트렌드) + 커밋용 git-SHA JSON |
| `tests/e2e/community_verdict.py` | 구조 판정 (차원이 재사용) |
| `tests/e2e/community_judge.py` | 대화품질 5축 LLM-judge (차원이 재사용) |
| `tests/e2e/community_report.py` | 마크다운 리포트 |

## 로드맵

- **Phase 1 (현재)**: 다차원 평가 + 종합 점수 + git-앵커 세대 히스토리. ✅ 엔진/차원/히스토리.
- **Phase 2**: PDF 리포트 추출 + 플랫폼 **웹 QA 대시보드**(별도 메뉴: 런 목록·리포트·**품질 우상향 트렌드 차트**).
- **Phase 3**: 시나리오 라이브러리(도전과제/그룹챗/드라마) + 차원 확장 + 다개발자 자아 문서.

## 알려진 gen-1 baseline 이슈 (= 시스템이 잡은 첫 실버그)

`friend_creation` 이 현재 **FAIL** (0/10): 오너가 유나 경유로 친구를 부탁해도, claude_cli 실런타임에서
유나(`request_dm`)·하나(`create_agent_profile`)가 도구를 **말로만 하고 `<tools>` 블록을 안 뱉어**
실제 생성이 안 된다. 이것이 gen-1→gen-2 의 첫 개선 타깃 — 고치면 `friend_creation 0→10`, 종합 점수가
오르고 그 델타가 git 에 남는다. (격리 `llm.generate`+clean confirm 에선 하나가 도구를 뱉는 것으로
확인 — 멀티턴 대화에서 commit 도달을 못 하는 게 핵심.)
