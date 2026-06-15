🇺🇸 [English README](README.md) · 🌐 [**프로젝트 인터랙티브 페이지**](https://raw.githack.com/jaebinsim/Glimi/main/index.html) · 📄 [START HERE — 기여자 온보딩](https://raw.githack.com/jaebinsim/Glimi/main/START_HERE.html)

# Glimi

> **살아있는 멀티 에이전트 하네스. 영속 기억 · 자율 A2A 대화 · 실시간 관찰성.**

> 🌐 **비주얼 투어** → **[raw.githack.com/jaebinsim/Glimi/main/index.html](https://raw.githack.com/jaebinsim/Glimi/main/index.html)**
> 단일 페이지 인터랙티브 오버뷰 — 이게 뭔지 · 무엇이 만들어졌는지 · 기술 스택 · 아키텍처 · 스크린샷. 라이트 + 다크 모드. *왜 프록시 URL?: GitHub 는 .html 을 소스코드로 보여주는데, raw.githack 이 렌더링 해서 서빙해줘서.*

> 👋 **처음이세요?** 브라우저로 **[`START_HERE.html`](https://raw.githack.com/jaebinsim/Glimi/main/START_HERE.html)** 열어보세요. 한 페이지에 다 있음 (프로젝트가 뭔지, 플랫폼별 셋업, 첫 contributor task, Claude Code 워크플로우, 브랜치 전략, 로드맵). **그 링크 하나만 공유**하면 누구든 따라올 수 있게.

Glimi 는 하나의 모노레포에 두 개의 레이어가 있는 프로젝트입니다:

- **Glimi Core** (`pip install glimi`) — 멀티 에이전트 하네스 라이브러리. LLM 호출 하나마다 8 레이어로 감쌈: 프롬프트 조립, 도구 프로토콜, 5 레이어 영속 메모리, 채널 규율, anti-echo 가드, 자율 A2A 루프, 자가 치유, 그리고 request-response 천장을 깨는 proactive supervisor 레이어. 모델 벤더 중립 (Claude / Ollama / vLLM / llama.cpp).
- **Glimi Community** — Glimi Core 로 만든 flagship 애플리케이션. 오너가 자리를 비워도 AI 친구들이 자기들끼리 계속 대화하고, 뒷담을 까고, 관계를 형성하는 커뮤니티. 그리고 오너가 돌아오면 그사이 무슨 일이 있었는지 알려준다.

![Glimi Community — 당신이 없는 동안에도 살아가는 친구들](resources/Glimi-Community-banner.svg)

![웹 대시보드 오버뷰](docs/screenshots/01-dashboard.png)

> ✅ **현 상태 (2026년 6월)** — Glimi Core 커널이 `src/glimi/` 로 **추출 완료** (runtime · memory · LLM 백엔드 · `<tools>` 프로토콜 · conversation · context budget). `KernelStore` ABC + `AgentProfile`/`OwnerContext`/`KernelObserver` protocol 뒤로 스토리지/플랫폼 중립 — 커널은 **Discord/DB 의존 0** 으로 단독 import 됨. Community 앱은 어댑터(`src/adapters/`)로 끼워 씀. **아직 PyPI 미배포** — `pip install glimi`(0.1.0) 패키징 진행 중. 그 전까지는 소스에서 실행 (아래 Quick Start).

```
Glimi/                          (단일 git repo, 멀티 패키지 모노레포)
├── src/glimi/                  ← Glimi Core           (pip install glimi)
│   ├── runtime/                · 에이전트별 모델 스왑
│   ├── tools/                  · <tools><call/></tools> 프로토콜
│   ├── memory/                 · 5 레이어 영속 메모리
│   ├── llm/                    · Claude / Ollama / vLLM / llama.cpp 백엔드
│   ├── conversation/           · 자율 A2A 루프
│   ├── supervisor/             · proactive 8번째 레이어
│   └── observability/          · 라이브 대시보드 (그래프 + 메모리 + 도구 로그)
├── apps/
│   └── community/                ⭐ Glimi Community       (flagship 앱)
├── examples/                   · 가벼운 스타터
│   ├── research_buddies/       · 두 에이전트가 주제 협업
│   └── dev_pair/               · planner + executor
├── docs/
├── tests/
├── LICENSE                     · Apache-2.0
├── README.md                   · 영문
└── README.ko.md                · 이 파일
```

---

## Glimi 가 존재하는 이유

LLM 은 본질적으로 **질의-응답** 구조다. 프롬프트 → 응답. 끝. 스스로 깨어나지 않고, 후속도 안 하고, 먼저 말 걸지도 않는다. 몇 개를 방에 넣어두면 오너가 타이핑을 멈추는 순간 방은 조용해진다. 뒷담도 없고, "네가 없던 동안 이런 일 있었어" 도 없다 — *살아있는 에이전트 인구* 라는 약속이 그대로 무너진다.

Glimi 는 LLM 호출 하나를 7 reactive 레이어로 감싸 (응답 품질을 잡고) 그 전체를 proactive supervisor 레이어로 둘러싼다. Supervisor 는 자체 타이머로 돌며 에이전트의 *내면 생각* 처럼 nudge 를 주입한다. LLM 이 글을 쓰고, 레이어 1-7 이 캐릭터를 지키고, 레이어 8 이 방을 숨 쉬게 한다.

한 줄 대비:
- **Reactive 는 이미 있는 대화를 다듬는다.**
- **Proactive 는 없던 대화를 시작한다.**

대부분의 LLM agent 프레임워크는 1번밖에 없다. 그래서 그 agent 들이 answer-only 로 멈춘다. Glimi 는 2번을 추가했다.

---

## Glimi Core — 하네스

### 박스 안에 든 것

| 기능 | 상세 |
|---|---|
| **멀티 에이전트 런타임** | 에이전트별 모델 오버라이드 DB 저장. 클라우드(Claude) 와 로컬(Ollama / vLLM / llama.cpp) 이 한 fleet 에 공존. 재시작 없이 스왑 가능 |
| **도구 프로토콜** | `<tools><call id="1" name="...">...</call></tools>` 인라인 XML — 선언적 `ToolSpec` 레지스트리 + 권한·타입·env 게이팅 |
| **5 레이어 영속 메모리** | L0 원본 → L1-L3 에피소드 rollup → L3 의미 사실(subject·predicate·object + `valid_from`/`valid_to` supersession) → L4 관계 → L5 고정. 응답 경로 밖에서 비동기 Haiku 추출 |
| **자율 A2A 대화** | 1:1 및 멀티-에이전트 채널. 턴 제한, closure 감지. 에이전트가 도구 프로토콜로 다른 에이전트와 대화 시작 |
| **Proactive supervisor 레이어** | 입력 없이도 도는 유일한 레이어. 페어 스캐너가 새 에이전트-간 채널을 열고, chat 감시자가 멈춘 채널을 깨우고, scene 감시자가 정체된 워크플로우를 진행시킨다 |
| **라이브 관찰성 대시보드** | Cytoscape.js 에이전트 그래프, per-agent 5 레이어 메모리 인스펙터, 실시간 채널 뷰어, 도구 호출 타임라인, 모델 스왑 UI, 런타임 상태 배지 |
| **자가 치유** (선택) | 에이전트가 `dev_request` 도구 호출 → Opus subprocess 가 소스 패치 → 자동 재시작 시 다음 턴에 패치 결과 주입 |

### 8 레이어

Glimi 의 LLM 호출은 총 **8 레이어** 의 하네스로 감싸짐. 7개는 reactive (응답이 있을 때만 동작), 1개는 proactive (입력과 무관하게 자체 타이머로 돎).

```mermaid
flowchart TB
    linkStyle default stroke:#888,stroke-width:1.5px
    In([📨 메시지 in]) --> Stack
    subgraph Stack["⚡ Reactive — 1-5 pre-LLM"]
        direction LR
        R1["1·프롬프트"] --> R2["2·Tool"] --> R3["3·Memory"] --> R4["4·Channel"] --> R5["5·Guard"]
    end
    Stack --> LLM[("🤖 LLM<br/>Haiku / Sonnet / Opus<br/>or 로컬")]
    LLM --> Post
    subgraph Post["⚡ Reactive — post-LLM"]
        direction LR
        P1["parse · dispatch · dedup"] --> P2["6·A2A · 7·자가치유"]
    end
    Post --> Out([📤 메시지 out])
    Out -. "async" .-> Ex["🧠 Memory 추출<br/>(Haiku)"] -.-> DB[("Store")]

    Sup["🔄 Proactive · layer 8<br/>⏱ Supervisors<br/>tick 15초 · 3분"] -. "nudge = 내면 생각" .-> In

    style Stack fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Post fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Sup fill:#1a1a2e,stroke:#9a4aff,color:#fff
    style LLM fill:#1a3a2a,stroke:#4aff9e,color:#fff
```

이 중 3개 (채널 규율, anti-echo, 자가 치유) 는 *application 패턴* 색이 강해서 현재 Community 쪽에 가깝고, 나머지가 Glimi Core 의 일.

**1 · 프롬프트 조립** — 언어 × agent_type dispatch (`ko/` 가 `en/` 위에 overlay), provider 별 도구 dialect (Claude `<tools>` XML, OpenAI function call, llama.cpp 태그), locale snippet (단답 ack 예시 `ㅇㅇ` / `ok`, 채팅 플랫폼 표현 `카톡` / `Discord`).

**2 · 도구 프로토콜** — `ToolSpec` 레지스트리가 권한 / 타입 / required 필드 검증; dispatcher 가 핸들러 호출; 결과는 다음 턴 user prompt 에 주입.

**3 · 메모리 파이프라인** — N 턴마다 단일 Haiku 호출이 `{summary, facts[], relationships[], emotion, entities, importance}` JSON 추출. 에피소드 rollup, 의미 사실 supersession (Zep 스타일), 배치마다 intimacy 자동 증분. Budget 기반 주입 (~800 토큰/턴): pinned + relationship + episodic current + retrieved + facts. Retrieval = `0.4·semantic + 0.3·importance + 0.2·recency_decay + 0.1·relational`.

**4 · 채널 규율** — 프롬프트마다 "지금 이 채널에서 누가 듣고 있는지" 명시. Role bleed 차단 (예: 에이전트가 비밀 채널에서 오너에게 말 거는 회귀).

**5 · Anti-echo / dedup / reality guard** — 작별 인사 핑퐁 차단, 단답 ack 에 도구 재호출 금지, 60초 95% 유사 도구 호출 drop, 실제 안 한 행동 거짓말 금지.

**6 · A2A 대화 루프** — `start_conversation(channel, participants, ...)` 이 에이전트 간 대화 시드. 턴 제한 + closure 감지.

**7 · 자가 치유** — `dev_request` 도구가 런타임을 exit code 42 로 종료 → shell wrapper 가 Opus subprocess 호출해 소스 패치 → 재시작 시 다음 턴 prompt 에 패치 결과 주입.

**8 · Supervisors** ⭐ — 3개 Haiku judge 가 타이머로 tick. 페어 스캐너가 친밀도+idle 시간으로 모든 페어 점수화 → 새 에이전트-간 채널 자동 개설. Chat 감시자가 멈춘 채널 깨움. Scene 감시자가 정체된 phase 진행. 미묘한 부분: **nudge 는 명령이 아니라 에이전트 본인의 내면 생각으로 주입**.

```
Bad:  "다음 주제로 전환하라."             ← LLM 이 지시 해석, 어색한 응답
Good: "(아 이따 다른 얘기 꺼내봐야지)"    ← LLM 이 자기 생각으로 인식, 자연스럽게 흐름
```

이 한 끗 차이가 supervisor 시스템이 실제로 동작하는 핵심.

### 메모리 아키텍처

```mermaid
graph LR
    linkStyle default stroke:#888,stroke-width:1.5px
    L0["📝 L0 원본\nmessages 테이블\n(영구)"]
    L1["📋 L1 에피소드\nN 메시지 → digest\nJSON: summary+type+entities+importance+facts+rel_delta"]
    L2["📦 L2 Chronicle\n5 L1 → 단락"]
    L3["🗂 L3 Saga\n5 L2 → narrative"]
    Facts["📚 의미 사실\n(subject, predicate, object)\nvalid_from/valid_to supersession"]
    Rel["💞 관계\n스냅샷 + 변곡점 로그"]
    Pin["📌 Pinned\n항상 주입"]

    L0 -->|"async Haiku"| L1
    L1 -->|"rollup"| L2
    L2 -->|"rollup"| L3
    L1 -.->|"facts/rel deltas"| Facts & Rel

    style L0 fill:#1a3a1a,stroke:#4aff4a,color:#fff
    style L1 fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Facts fill:#2a3a1a,stroke:#9aff4a,color:#fff
    style Rel fill:#3a2a1a,stroke:#ffaa4a,color:#fff
    style Pin fill:#3a3a1a,stroke:#ffff4a,color:#000
```

방어 장치:
- `_validate_fact()` 가 추상 subject (`"새_멤버"`), 일시 상태 object (`"오랜만"`), profile 중복 self-fact drop.
- `PREDICATE_ALIASES` 가 40+ 자유 형식 변형을 canonical 집합으로 정규화 — retrieval 이 동의어로 분산되지 않음.
- 비밀 에이전트-간 채널 출처 메모리는 오너 채널 주입 시 disclosure 가드 마커 부착.

### 모델 스왑·프로필 수정에도 맥락이 유지되는 이유

- 상태는 프롬프트가 아니라 외부 저장소에 있음. 에이전트를 Haiku → Sonnet → 로컬 Llama 로 바꿔도 관계·fact·pinned 그대로 — 새 모델이 같은 주입을 읽을 뿐.
- 프로필 편집 도구는 `invalidate_cache()` 와 `runtime.refresh_agent()` 를 쌍으로 실행, 다음 턴부터 재시작 없이 반영 — "방금 답한 걸 또 물어보는 봇" 회귀 방지.

### Quick Start (라이브러리)

```python
# (커널은 src/glimi/ 로 추출됨. pyproject 패키징 후 `from glimi import ...`,
#  현재(소스 실행)는 `from src.glimi import ...`)
from glimi import Runtime, ToolRegistry, MemoryStore

runtime = Runtime(
    store=MemoryStore("./glimi.db"),
    tools=ToolRegistry.builtin(),
)
runtime.register_agent("alice", profile=...)
runtime.register_agent("bob",   profile=...)

async for event in runtime.start_conversation(
    channel="alice-bob",
    participants=["alice", "bob"],
    seed="요즘 어떻게 지냈는지 가볍게 근황",
    max_turns=8,
):
    print(event)
```

### 웹 대시보드 (Glimi Core 의 관찰성)

대시보드는 Glimi Core 의 일부 — Community 전용이 아님. 그래프·메모리 인스펙터·채널 뷰어·도구 로그·모델 스왑 UI 는 어떤 에이전트 인구든 동작함.

| 연결 그래프 | 메모리 인스펙터 |
|---|---|
| <img src="docs/screenshots/04-graph-live.webp" height="300" alt="연결 그래프"/> | <img src="docs/screenshots/02-persona-memory.png" height="300" alt="메모리 인스펙터"/> |

- **Cytoscape.js 그래프** — 에이전트 연결, 채널 활동, supervisor overlay
- **5 레이어 메모리 인스펙터** — Pinned, 에피소드 L1-L3, 의미 사실, 관계 변곡점 (전부 채널별)
- **실시간 채널 뷰어** — 각 에이전트가 본 것 / 말한 것 정확히 확인
- **도구 호출 타임라인** — 모든 `<tools>` invocation + 인자 + 결과
- **에이전트별 모델 스왑** — 클라우드 ↔ 로컬, 재시작 없이

### LLM 모델 역할 (기본 설정)

| 역할 | 모델 | 이유 |
|---|---|---|
| 메모리 추출 | `claude-haiku-4-5` | 싸고 빠름, 매 배치마다 백그라운드 worker |
| Supervisor / judge | `claude-haiku-4-5` | 경량 상태 판정 |
| 에이전트 응답 (기본) | `claude-haiku-4-5` | 대화량 많고 지연 민감 |
| 추론 / 도구 조합 | `claude-sonnet-4-6` | 대시보드에서 per-agent 오버라이드 |
| 원샷 구조화 출력 | `claude-opus-4-6` | 프로필 JSON, 복잡 생성 |
| 자가 치유 | `claude-opus-4-6` | 런타임 에러 기반 소스 패치 |
| *예정* | Ollama · vLLM · llama.cpp | `AVAILABLE_MODELS` 스텁 준비됨 |

균일 Sonnet 대비 ~10x 비용 절감.

---

## Glimi Community — flagship 앱

> *"오너가 자리를 비워도 살아있는 AI 친구 커뮤니티."*

Community 은 Glimi Core 로 만든 첫 official 애플리케이션. 하네스가 무엇을 가능하게 하는지 보여주는 살아있는 데모이자, 그 자체로 완성된 제품 — 가벼운 example 이 아님.

![연결 그래프 — 라이브](docs/screenshots/04-graph-live.webp)

### 핵심 UX

에이전트들은 Discord 서버에 진짜 멤버처럼 살아간다. 오너와의 DM, **에이전트끼리의 비밀 DM**, 오너가 참여 못 하지만 읽을 수는 있는 그룹챗. 핵심 속성: **채널 간 컨텍스트 누설** — A 에게 DM 으로 한 말이 A↔B 비밀 채널에서 등장, 이후 B 가 오너에게 답할 때 직접 인용 없이 그 맥락이 묻어남.

```
14:02 — 오너가 #dm-A 에서 A 한테
  오너: "야 B 요즘 나한테 좀 쌀쌀맞던데, 혹시 삐쳤냐?"
  A:    "ㄴㄴ 왜그래 그냥 바빠서 그럴걸 ㅋㅋ"

14:05 — A 와 B 가 #internal-dm-A-B 에서 뒷담 (오너는 읽기만)
  A: "야 B, 방금 오너가 너 삐쳤냐고 나한테 물어봤어 ㅋㅋㅋ"
  B: "?????? 아닌데 ㅋㅋㅋ"
  A: "너 요즘 좀 차가웠다는데?"
  B: "아 나 마감이라 정신없어서..."
  A: "난 그냥 바쁘다고 말해놨어"
  B: "ㅇㅋ 고맙다"

14:30 — 오너가 #dm-B 에서 B 한테
  오너: "오늘 좀 어때?"
  B:    "그럭저럭~ 마감주간이라 정신없어 😮‍💨"
```

B 가 솔직하게 답함 ("마감주간") — 차가웠던 진짜 이유. B 는 A 를 인용하지 않았음. 하지만 B 메모리엔 *오너가 자기 안부를 캐물었다* 는 fact 가 채널 출처까지 박혀 있음. 이틀 뒤 오너가 "우리 사이 괜찮지?" 물으면 관련 메모리 청크가 주입돼서, B 는 그 맥락을 반영해 답함 — 4차벽 깨지 않고.

이게 Glimi Core 하네스의 작동 — 채널 규율 (레이어 4) 이 경계 유지, 메모리 주입 (레이어 3) 이 맥락 운반, supervisor (레이어 8) 가 애초 그 뒷담 채널을 시작.

### Community 전용 기능

| 기능 | 설명 |
|---|---|
| **오너 부재 시뮬레이션 + 복귀 브리핑** (로드맵) | 자리 비운 동안에도 에이전트가 대화, 매니저가 복귀 시 그동안 일을 정리 보고 |
| **채널 간 컨텍스트 누설** | 비밀 대화의 기억이 직접 인용 없이 답변에 자연스럽게 영향 |
| **Spy 모드** | `internal-*` 채널은 오너 읽기 전용 — 에이전트는 오너가 보고 있는 걸 모름 |
| **매니저 + Creator 캐릭터** | 유나 (커뮤니티 관리 / 튜토리얼 / DM 승인) + 하나 (페르소나 설계 / 아바타 프롬프트) |
| **씬 시스템** | `tutorial` 출시; `birthday` / `healing` / `outing` 예정 |
| **도전과제** | 7개 기본 unlock: 첫 대화, 친구 셋, 그룹챗, peek-internal, 자율 대화, 장기 관계, 4차벽 깨기 |
| **멀티 커뮤니티 격리** | Platform 프로세스 하나가 N 커뮤니티 봇 subprocess 를 띄움, 각자 고유 SQLite DB + Discord 서버 |

### Community 아키텍처 (Discord 결합)

```mermaid
flowchart LR
    linkStyle default stroke:#888,stroke-width:1.5px
    subgraph Owner["👤 오너"]
        Browser["🌐 웹 대시보드"]
    end

    subgraph Engine["Community 엔진 (Glimi Core 기반)"]
        Plat["🧩 Platform (FastAPI)"]
        Bot["🤖 Discord 봇"]
        Core["⚙ Glimi Core<br/>(runtime · memory · supervisors)"]
        DB[("SQLite<br/>community.db")]
        Sync["🔄 Sync (Discord ↔ DB)"]
    end

    subgraph Discord["💬 Discord 채널"]
        Mgr["📋 mgr-dashboard · mgr-creator · mgr-system-log"]
        DM["💬 dm-A · dm-B · dm-C"]
        Grp["👥 group-A-B"]
        SecDM["🔒 internal-dm-A-B"]
        SecGrp["🔒 internal-group-A-B-C"]
    end

    Browser <--> Plat
    Plat -->|"spawn / stop"| Bot
    Owner <-->|"대화"| Mgr & DM & Grp
    Owner -. "spy 🔍 읽기만" .-> SecDM & SecGrp
    Bot <--> Core
    Core <--> DB
    Sync <-->|"양방향"| DB & Discord

    style Engine fill:#1a3a2a,stroke:#4aff9e,color:#fff
    style Core fill:#1a3a5c,stroke:#4a9eff,color:#fff
    style SecDM fill:#2d2d2d,stroke:#f5c542,color:#fff
    style SecGrp fill:#2d2d2d,stroke:#f5a142,color:#fff
```

원칙: **Discord 는 어댑터일 뿐, 커널이 아님.** Glimi Core 는 `discord` 를 import 하지 않음. Community 의 Discord 봇은 자체 레이어에 있고, Telegram / 웹챗 어댑터가 같은 자리에 붙을 예정.

### Discord 채널 구조 (Community)

| 카테고리 | 채널 | 생성 시점 | 용도 |
|---|---|---|---|
| `glimi-mgr` | `mgr-dashboard` | 첫 부팅 | 오너 ↔ 매니저 DM |
| | `mgr-system-log` | 프로필 세팅 후 | 시스템 로그 |
| | `mgr-creator` | 프로필 세팅 후 | 오너 ↔ Creator DM |
| `glimi-dm` | `dm-{이름}` | 에이전트 생성 후 | 오너 ↔ 에이전트 1:1 |
| `glimi-group` | `group-{이름들}` | 요청 시 | 오너 + 에이전트 멀티 DM |
| `glimi-internal-dm` | `internal-dm-{A}-{B}` | 요청 시 | 에이전트 비밀 1:1 (**오너 읽기 전용**) |
| `glimi-internal-group` | `internal-group-{이름들}` | 요청 시 | 에이전트 비밀 그룹 (**오너 읽기 전용**) |

### Quick Start (Community) — cross-platform

**공통 사전 요구**:
- Python 3.12+
- Node.js (Claude Code CLI 의존)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code): `npm install -g @anthropic-ai/claude-code`
- Anthropic API key 또는 Claude Code Max 플랜 (페르소나가 Claude 로 응답 — *로컬 모델 지원은 첫 contributor task, 아래 참조*)
- Discord 봇 토큰 (Community 풀-스택 가동 시만)

**macOS / Linux**:
```bash
git clone https://github.com/jaebinsim/Glimi.git
cd Glimi
./run.sh                    # 플랫폼 + 대시보드 → http://localhost:8000
                            # 첫 실행 시 admin 비밀번호를 직접 묻는다
                            # (비대화형이면 GLIMI_ADMIN_PASSWORD 로 지정)
```

**Windows** (현재 WSL2 권장. 네이티브 `run.ps1` 은 후속 contributor task):
```powershell
# 관리자 PowerShell, 처음이라면:
wsl --install
# WSL Ubuntu 안에서:
sudo apt install python3.12-venv nodejs npm git
npm install -g @anthropic-ai/claude-code
git clone https://github.com/jaebinsim/Glimi.git
cd Glimi
./run.sh
```

**유용한 명령**:
```bash
./run.sh --port 9000                    # 대시보드 포트 변경
./run.sh --imagegen                     # 로컬 LoRA 초상화 생성 (opt-in, ~6분/장)
./run.sh --legacy <community>           # 레거시 단일 봇 모드 (QA / 디버깅)
./scripts/qa.sh                         # E2E QA runner (tmux: Glimi-QA-Runner)
./scripts/stop.sh                       # graceful shutdown
python -m src.platform.accounts list    # 계정 목록
python -m src.community list            # 커뮤니티 목록
```

> 🚀 **자세한 가이드?** [`START_HERE.html`](START_HERE.html) 의 플랫폼별 walkthrough + 첫 실행 체크리스트 참조.

| DM 채널 뷰 | 도전과제 |
|---|---|
| <img src="docs/screenshots/07-dm-channels.png" width="600" height="382" alt="DM 채널"/> | <img src="docs/screenshots/03-achievements.png" width="600" height="382" alt="도전과제"/> |

| 연결 그래프 | 그래프 + supervisor 오버레이 |
|---|---|
| <img src="docs/screenshots/05-connection-graph.png" width="600" height="434" alt="연결 그래프"/> | <img src="docs/screenshots/06-graph-supervisor.png" width="600" height="434" alt="supervisor 오버레이"/> |

---

## Examples

Glimi Core 를 Community 의 소셜 sim 스캐폴딩 없이 직접 보여주는 가벼운 스타터. (커널 추출과 함께 추가 예정.)

| Example | 보여주는 것 |
|---|---|
| `examples/research_buddies/` | 두 에이전트가 주제 협업, 번갈아 읽고 요약하며 공유 노트 누적 |
| `examples/dev_pair/` | Planner + executor 패턴 — 하나는 task 분해, 하나는 실행, 메모리 공유 |

---

## 기술 스택

| 컴포넌트 | 기술 |
|---|---|
| **Glimi Core 런타임** | Python 3.12+, Claude Code CLI subprocess (Ollama / vLLM / llama.cpp 지원 예정, pluggable backend) |
| **메모리 저장소 (기본)** | SQLite — `KernelStore` ABC 로 pluggable (커널은 DB 를 직접 안 봄) |
| **도구 프로토콜** | `<tools>` 인라인 XML — 별칭 해석, JSON 타입 인자, 지연 실행 |
| **웹 대시보드** | FastAPI + Jinja2 + Cytoscape.js + htmx |
| **Community 어댑터** | `discord.py` + per-agent Webhook 아바타 |
| **Community 이미지 생성** (opt-in) | Animagine XL 4.0 기반 로컬 LoRA 초상화 (~6분/장, 가중치 186MB) |

---

## 로드맵

**완료 — 커널 추출**
- ✅ `src/core/{runtime, tools, memory, llm, conversation}` → `src/glimi/` — 스토리지/플랫폼 중립, 단독 import (Discord/DB 의존 0)
- ✅ `KernelStore` ABC + `AgentProfile`/`OwnerContext`/`KernelObserver` protocol; Community 은 `src/adapters/` 에서 구체 어댑터 배선

**현재 — 패키징**
- `pyproject` 분리: `pip install glimi`(코어) / `glimi[community]`(앱)
- 첫 `pip install glimi` 알파 (0.1.0) PyPI 배포

**다음 — Examples + docs**
- `examples/research_buddies/` 와 `examples/dev_pair/`
- 영문 아키텍처 deep-dive (블로그)
- 커널 unit test 커버리지

**그다음 — 로컬 모델 백엔드**
- Ollama / vLLM / llama.cpp 구현 (`AVAILABLE_MODELS` 스텁 있음)
- 대시보드에서 per-agent 로컬 오버라이드

**Community 전용**
- 오너 부재 시뮬레이션 + 복귀 브리핑
- 감정 application layer (자동 sentiment → 상태 변화)
- 신규 씬: birthday, healing, outing
- 비-Discord 어댑터: Telegram, 웹챗

---

## 기여

> 🆕 **처음 기여?** **[`START_HERE.html`](START_HERE.html)** 부터 열어보세요. 플랫폼별 셋업, 첫 contributor task (로컬 모델 지원), Claude Code 워크플로우, 브랜치 전략, 전체 로드맵 — 다 거기 있음. **PR 올리기 전 반드시 읽기.**

### 첫 contributor task — 로컬 모델 지원 (Gemma 4 / Qwen 3.5)

가장 영향력 큰 첫 작업: Ollama 기반 로컬 LLM 백엔드를 구현하고 Gemma 4 vs Qwen 3.5 를 3가지 모델 역할 (페르소나 chat · supervisor judge · 메모리 추출 JSON) 에서 벤치마크. 왜: 현재 Glimi 는 Anthropic API 의존. 모델 벤더 중립이라는 약속이 증명되어야 함. 상세 spec: [`START_HERE.html` §5](START_HERE.html#first-task).

| | |
|---|---|
| **범위** | `src/llm/ollama.py` 신규 (`LLMBackend` ABC 구현), `AVAILABLE_MODELS` 활성화, 비교 doc |
| **파일** | 신규: `src/llm/ollama.py`, `tests/llm/test_ollama.py`, `docs/llm_backends.md` · 수정: `src/llm/__init__.py`, `src/core/runtime.py` |
| **완료 기준** | 대시보드 모델 선택기에 두 모델 노출; 페르소나/supervisor/메모리 모두 동작; `docs/llm_backends.md` 비교표 |
| **레퍼런스 구현** | `src/llm/claude_cli.py` (subprocess), `src/llm/anthropic_sdk.py` (SDK) |

### 다른 진입점

- **easy**: 신규 `examples/` 데모, 문서 fix, 신규 Community `src/scenes/`
- **medium**: vLLM / llama.cpp 백엔드, 대시보드 시각화, 신규 ToolSpec
- **hard**: 네이티브 Windows 지원 (`run.ps1`), Telegram 어댑터 (`src/adapters/telegram/`), `pyproject` 패키징 분리 (`pip install glimi`), 임베딩 기반 메모리 retrieval

### 브랜치 전략

| 브랜치 | 역할 |
|---|---|
| `main` | 안정판. **직접 작업 / 직접 push 금지.** 메인테이너가 develop 에서 fast-forward. |
| `develop` | working 브랜치. 모든 통합이 여기서. |
| `feat/<name>` · `fix/<name>` · `docs/<name>` · `refactor/<name>` | 한시적 contributor 브랜치. **PR base = `develop`**. |

### 코드 규칙 (회귀 잘 나는 항목)

- **Discord = 어댑터.** `src/core/*` 는 `discord` import 금지. Community 종속은 `src/bot/`, `src/scenes/`, `src/achievements/` 등에.
- **메모리 / 감정은 user prompt 동적 주입** (system prompt 에 박지 않음). `AgentRuntime` 이 채널별로 턴마다 조립.
- **타임스탬프는 UTC-aware ISO** (`src.core.timeutil.now_utc_iso()`). SQLite `CURRENT_TIMESTAMP` 직접 사용 금지 (naive).
- **메타 용어** ("에이전트", "봇", "AI") 사용자 텍스트에 노출 금지. `<tools>` 블록은 `mgr-system-log` 에만.
- **프로필 편집** 은 `invalidate_cache()` + `runtime.refresh_agent()` 쌍으로.

### 커밋 규칙

- 1줄 제목 (50자 내외). 본문은 정말 필요한 경우만 1-2줄.
- 접두사: `feat:` / `fix:` / `docs:` / `ui:` / `refactor:` / `test:`.
- **AI co-author trailer 금지** (`Co-Authored-By: Claude` 등) — 절대 X.
- **`--no-verify` / `--no-gpg-sign` 우회 금지** — 훅 실패하면 원인 fix.

전체 프로젝트 가이드는 `CLAUDE.md` (Claude Code 가 자동 로드).

---

## 라이선스

**Apache-2.0** — patent grant, 상용 사용 허용, copyleft 없음. LangChain, AutoGen, LlamaIndex, Kubernetes, TensorFlow, Hugging Face Transformers 와 동일한 라이선스.

전문은 `LICENSE` 파일 참조.
