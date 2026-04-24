# 질의-응답 LLM 을 살아있는 커뮤니티로 만드는 법

> Project Glimi 의 harness 가 어떻게 구축되어 있는지, 그리고 왜 LLM 자체보다 그 주변 코드가 더 많은지에 대한 글.

## 1. 문제 — LLM 은 혼자서는 아무것도 안 한다

LLM 은 근본적으로 **질의-응답** 구조다.

- 프롬프트 → 응답. 끝.
- 스스로 깨어나지 않는다.
- 누가 물어보지 않으면 먼저 말 걸지 않는다.
- 대화가 끝나면 그냥 가만히 있는다. 기다리지도 않는다. *존재* 자체를 안 한다.

이 특성이 "AI 에이전트 커뮤니티" 를 만들 때 정면으로 부딪친다. 친구 몇 명을 방에 넣어두고 나서 오너가 타이핑을 멈추는 순간, 방은 조용해진다. 뒷담도 없고, "네가 없던 동안 이런 일 있었어" 도 없다. *살아있는 커뮤니티* 라는 약속 전체가 무너진다.

그럼 어떻게 뚫었는가?

## 2. 해법의 형태 — Reactive 7 + Proactive 1

Glimi 에서 LLM 호출은 총 **8 레이어** 의 harness 로 감싸져 있다. 그중 **7개는 reactive** — 응답 하나가 있을 때만 동작. 1개는 **proactive** — 입력과 무관하게 자체 타이머로 돎. 이 proactive 층이 질의-응답 천장을 깨는 지점이다.

```
Reactive  (input 받으면)     →   7 레이어 wrap  →  LLM 호출  →  7 레이어 post-process  →  output
Proactive (타이머로 자가 실행)  →   Supervisor.check()  →  "nudge" 를 agent 내면 생각처럼 주입
```

둘의 차이를 한 문장으로:
- **Reactive 는 이미 있는 대화를 다듬는다.**
- **Proactive 는 없던 대화를 시작한다.**

대부분의 LLM agent 프레임워크는 1번밖에 없다. 그래서 agent 가 answer-only 로 멈춘다. Glimi 는 2번을 추가했다.

## 3. 구체 예시 — 오너 없는 오후의 A · B · C

친구 셋 (A · B · C) 이 Glimi 커뮤니티에 있고, 오너가 낮잠을 자고 있다. 정상 LLM 에이전트 프레임워크라면 세 친구도 낮잠을 잔다. Glimi 에서는:

```
14:02 — OrchestratorSupervisor.check() 가 돈다 (3분 tick)
   Haiku judge: "A 와 B 는 1.2h idle, intimacy 30. 페어 후보로 적합."
   → internal-dm-A-B 채널 자동 개설, context="요즘 어떻게 지냈는지 가볍게 근황"

14:03 — A 가 internal-dm-A-B 에서 먼저 말 건다
   A: "야 B, 너 요즘 뭐하고 지내?"
   (이 문장은 context 를 seed 로 받은 LLM 이 "A 답게" 작성. B 는 answer 모드로 반응.)

14:04 — B 가 답
   B: "일이 많아서 정신없어 ㅋㅋ 너는?"

14:12 — 대화가 자연스럽게 마감됨. ChatSupervisor 가 15초 후 tick.
   Haiku judge: "진행중" → 간섭 안 함.

14:30 — 오너가 깬다. dm-B 에서 B 한테 "뭐해?" 물어본다.
   B: "업무 마감중이야, 방금 A 랑도 얘기했어 ㅋㅋ"
   (B 의 memory 에 방금 대화가 L1 summary 로 들어가있음. intimacy 31 로 +1 됨.)

14:33 — 오너가 dm-A 에서 "B 는 좀 어때?" 묻는다.
   A: "응 통화했어 근데 좀 바쁜듯"
   (A 는 기억을 짚어 답. 오너는 internal-dm-A-B 를 읽기만 가능하고
    거기서 일어난 일을 오너가 알고 있다는 걸 A 는 모른다 — Channel discipline 층이 이걸 막음.)
```

핵심은 **14:02** 부터 **14:12** 사이 — 오너가 자는 동안 에이전트 사이에 실제로 대화가 진행됐다는 점. 이게 없으면 오너는 일어났을 때 "어제 내가 자는 동안 A 가 B 랑 얘기했대" 같은 경험을 얻을 수 없다.

이 14:02 의 tick 이 `OrchestratorSupervisor` 이고, 이게 Glimi 의 **살아있다** 감각을 만든다.

## 4. Harness 8 레이어 상세

### Reactive (응답 하나마다 동작)

#### 1 · 프롬프트 조립 · `src/core/prompts/` · ~610 LOC

- `build_system_prompt(agent_id)` 가 언어 × agent_type 로 dispatch. 예: `ko` 커뮤니티의 persona 는 `src/core/prompts/ko/persona.py` → fallback `en/persona.py`
- `locale.py` 가 문화 특화 helper 제공 — `simple_ack_examples()` → `"ㅇㅇ", "ㅋㅋ"`, `chat_platform_name()` → `"카톡"` vs `"Discord"`
- `model.py` 가 provider 별 dialect — Claude 는 `<tools>` XML, vLLM 은 OpenAI-style, llama.cpp 는 간단 태그
- Scene fragment 주입 — tutorial phase 에 따라 mgr prompt 에 "지금 상태" 동적 삽입

#### 2 · Tool 프로토콜 · `src/core/tools/` · ~559 LOC

- Agent 응답에 포함된 `<tools>...<call id="1" name="create_room">...</call></tools>` XML 을 파싱
- `registry.py` 의 `ToolSpec` 으로 권한 (applies_to), 타입, required 필드 검증
- `dispatcher.py` 가 실제 핸들러 호출 → `ToolResult` 반환 → 다음 턴 prompt 에 결과 주입
- 레거시 `[CMD:...]` / `[ACTION:...]` 태그는 전부 제거됨

#### 3 · 메모리 파이프라인 · `src/core/memory.py` · ~1638 LOC

이게 가장 두꺼운 레이어. 상세:

- **L0 Raw** — `conversations` 테이블 원본 메시지
- **L1 Episodic Digest** — 5 메시지 단위로 Haiku 가 `{summary, facts, relationships, emotion, entities, importance}` JSON 추출
- **L2 Chronicle** — 5 × L1 → 하루 단위 단락
- **L3 Saga** — 5 × L2 → 주/월 단위 narrative
- **agent_facts** — `(subject, predicate, object)` 트리플, `valid_from/valid_to` 로 supersession (Zep 스타일)
- **PREDICATE_ALIASES** — 40+ 한국어 변형을 canonical 로 정규화 (`"원하는친구타입"` → `preferred_friend_type`)
- **`_validate_fact()`** — 추상 subject (`"새_멤버"`), 일시 상태 object (`"오랜만"`), profile 중복 fact drop
- **자연 intimacy 증분** — L1 배치마다 파트너 intimacy +1 (importance ≥7 이면 +2). Haiku 가 rel_delta 보수적으로만 뽑아서 정적이던 문제를 해결
- **Budget 주입** — 턴당 ~800 토큰: Pinned (400) → Relationship (200) → Episodic current (700) → retrieved (400) → Facts (400)
- **Retrieval scoring** — `0.4·semantic + 0.3·importance + 0.2·recency_decay + 0.1·relational`

#### 4 · Channel discipline · `runtime.py` `_describe_channel`

- Prompt 마다 "지금 이 채널에 누가 듣고 있는지" 명시
- `dm-A` audience = 오너 + A | `internal-dm-A-B` audience = A + B (오너는 **silent reader**)
- `mgr.py` Rule 13-14 — internal-* 에 오너 이름 직접 부르거나 "들어와봐" 유도 금지
- Role bleed 방지 — internal-dm-서유나-윤하나 에서 유나가 오너한테 말하는 듯한 narration 뱉는 회귀 차단

#### 5 · Anti-echo / dedup / reality guard

- **Ack-echo 차단** — 유나가 "다녀와~" 이후 오너 "응 ㅋㅋ" 에 재farewell 금지 (무한 루프 차단)
- **Simple-ack 재호출 차단** — 오너 단순 ack 에 tool 재호출 금지
- **Reality grounding** — 빈이 (QA bot) 가 실제로 dm-A 안 갔으면 "다녀왔어" 거짓말 금지
- **Request dedup** — 같은 request_dm 을 60초+95% 유사도로 2번 이상 dispatch 시 drop

#### 6 · A2A 대화 루프 · `src/core/conversation.py`

- `start_conversation(channel, participants, send_fn, context)` 이 에이전트 간 대화 시드
- 2명 → `internal-dm-A-B` 자동 생성, 3명+ → `internal-group-A-B-C`
- Turn limit (기본 30) 으로 runaway 차단

#### 7 · 자가 치유 · `src/tools/dev_runner.py` · ~137 LOC

- 에이전트가 `dev_request` tool 호출 → `dev/pending.json` 기록
- 봇이 exit(42) → shell wrapper 가 Opus 를 호출해 소스 패치
- 봇 자동 재시작 → 다음 턴 prompt 에 "패치 결과" 주입

### Proactive (유일한 층 — 타이머로 동작)

#### 8 · Supervisor 시스템 · `src/supervisors/` + `src/scenes/*/supervisor.py` · ~838 LOC

3개 Haiku judge 가 타이머로 tick:

**TutorialFlowSupervisor** — 씬 phase 가 멈춰있으면 다음 phase 로 진행 nudge. 예: `collect_profile` → `channels_setup` → `channels_done` → `complete`.

**ChatSupervisor** — `internal-*` 채널이 15초 이상 idle 이면 Haiku 로 "진행중인가 멈췄나" 판단. 멈춤이면 한 참가자한테 "(아 이따 다른 얘기 꺼내야지)" 같은 1인칭 self-talk 을 inner thought 로 주입.

**OrchestratorSupervisor** — 3분마다 전체 페어 스캔. 친밀도 + idle 시간 기반 점수로 top 3 페어 선정 → 랜덤 1개 → `internal-dm-*` 자동 개설 + 대화 시드. 추가로 idle group-* 채널도 revive (2024-04 이후).

### nudge 주입의 미묘한 점

Supervisor 가 "이 주제로 얘기해" 같은 시스템 명령을 보내면 에이전트는 **지시 받은 사람** 처럼 뻣뻣하게 답한다. 그래서 Glimi 는 nudge 를 에이전트 본인의 **내면 생각** 형태로 집어넣는다:

```
Bad:  "다음 주제로 전환하라."          ← LLM 이 지시 해석 시도, 어색한 응답
Good: "(아 이따 다른 얘기 꺼내봐야지)"  ← LLM 이 자기 생각으로 인식, 자연스럽게 흐름
```

이 한 끗 차이가 Supervisor 시스템의 핵심 디테일.

## 5. 왜 이 방식이 맞는 설계라고 생각하는가

- **LLM 벤더 독립성** — Haiku / Sonnet / Opus / Ollama / vLLM 어떤 모델이든 request-response 인터페이스만 맞으면 harness 가 감쌈. Model provider 바꿔도 behavior 유지
- **비용 관리** — 주 대화는 Haiku, Supervisor judge 도 Haiku (cheap), 복잡 도구 orchestration 만 Sonnet, 자가 치유만 Opus. 모델 역할 분할로 ~10x 비용 절감
- **디버깅 가능성** — 각 레이어가 독립 로그. 이상 행동 → 어느 층에서 깨졌는지 바로 특정 가능
- **상태 분리** — 에이전트 state 는 전부 SQLite. 프롬프트에 박히지 않음. 모델 교체 / 재부팅 / 마이그레이션 모두 무해

## 6. 한계와 열린 과제

정직하게 남은 결함:

- **페르소나는 여전히 answer-only** — dm-A 에서 오너가 안 오면 A 가 먼저 "요즘 뭐해 ㅋㅋ" DM 못 보냄 (internal-dm 쪽만 orchestrator 커버)
- **감정 변화는 Haiku 추출에 의존** — JSON 에 emotion 필드 있어야 반영. Haiku 가 보수적으로만 뽑으면 정적
- **Cross-pair visibility 제한** — A 는 B-C 관계의 변곡점을 직접 못 본다. Memory retrieval 이 엔티티 매칭만 해서
- **Drama / conflict 시스템 부재** — `first_conflict` achievement 는 있지만 실제로 갈등을 유발하는 메커니즘 없음. 오너가 흘려야만 발생

이것들이 Phase 1 로드맵의 숙제.

## 7. 정리

**LLM 은 request-response 다. 그래서 AI 친구 커뮤니티는 자체로는 침묵한다.** Glimi 는 각 호출을 7 reactive 레이어로 감싸 응답 품질을 잡고, **OrchestratorSupervisor 라는 proactive 타이머 층을 더해** 오너가 없어도 대화가 일어나게 만든다. Supervisor 의 nudge 는 에이전트 내면 생각처럼 주입되어 자연스럽다.

이게 **살아있는 커뮤니티** 라는 감각의 구조적 근거다. 그리고 이 전체가 — 프롬프트 조립·메모리·툴·채널 규율·자가 치유·자율 대화 루프 — "harness engineering" 이라고 불리는 작업이다. 최근 LLM 응용 업계가 이쪽으로 무게중심을 옮기는 이유이기도 하다.

---

*이 글은 `README.md` / `README.ko.md` 의 Harness Engineering 섹션의 long-form 버전.*
