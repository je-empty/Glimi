[← README](../README.ko.md)

# Glimi — 내부 구조

Glimi Core 런타임 파이프라인, 메모리 레이어, Community 채널 모델 등 깊은 내부 동작을 모은 문서다. README 는 무엇·왜·어떻게(설치/실행)에 집중하고, 아키텍처 상세는 여기에 둔다.

---

## 8 레이어

Glimi 응답은 **8개 개념 레이어**를 통과한다. 일부는 LLM 호출 근처(프롬프트·도구·메모리)에, 나머지는 A2A 루프·supervisor·자가 치유 등 별도 서브시스템에 있다. 7개는 reactive, 1개는 proactive(타이머 구동)다.

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

    Sup["🔄 Proactive · layer 8<br/>⏱ Supervisors<br/>chat 15초 · scene 30초 · pair-scan 3분"] -. "nudge = 내면 생각" .-> In

    style Stack fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Post fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Sup fill:#1a1a2e,stroke:#9a4aff,color:#fff
    style LLM fill:#1a3a2a,stroke:#4aff9e,color:#fff
```

3개(채널 규율, anti-echo, 자가 치유)는 *application 패턴* 기반으로 Community 영역에, 나머지는 Glimi Core 가 담당한다.

**1 · 프롬프트 조립** — 언어 × agent_type dispatch (`ko/` 가 `en/` 위에 overlay). 백엔드별 도구 dialect (Claude `<tools>` XML, OpenAI function call). 로캘 snippet (`ㅇㅇ` / `ok`, `카톡` / `Discord`).

**2 · 도구 프로토콜** — `ToolSpec` 레지스트리가 권한·타입 검증을 수행한다. dispatcher 는 핸들러 결과를 다음 user prompt 에 주입한다.

**3 · 메모리 파이프라인** — N 턴마다 Haiku 가 `{summary, facts[], relationships[], emotion, entities, importance}` JSON 을 만든다. 에피소드 rollup, 사실 supersession(Zep 스타일), 친밀도 자동 증분이 포함된다. Budget 은 ~1000 토큰/턴. pinned + relationship + episodic-current + cross-channel + retrieved + facts 가 주입된다. Retrieval 가중치: `0.4·semantic + 0.3·importance + 0.2·recency_decay + 0.1·relational`.

**4 · 채널 규율** — 프롬프트에 채널 참여자를 명시해 role bleed 를 막는다.

**5 · Anti-echo / dedup / reality guard** — 작별 핑퐁 차단, 단답 ack 후 도구 재호출 금지, 60초 내 유사 95% 호출 drop, 허위 행동 차단.

**6 · A2A 대화 루프** — `start_conversation(...)` 으로 에이전트 간 대화를 시작한다. 턴 제한과 closure 감지를 수행한다.

**7 · 자가 치유** (실험, 기본 OFF) — `request_dev_fix` 큐잉 → supervisor 트리아지 → 승인 시 Opus subprocess(`GLIMI_DEV_DISPATCH=1`) 패치 → 재시작 시 요약 주입.

**8 · Supervisors** ⭐ — 타이머 기반 3개 트리오. 페어 스캐너가 새 채널을 생성하고, Chat 감시자가 멈춘 채널을 깨우며, Scene 감시자가 phase 를 진행한다. **nudge 는 명령이 아니라 내면 생각으로 주입**된다.

```
Bad:  "다음 주제로 전환하라."             ← LLM 이 지시 해석, 어색한 응답
Good: "(아 이따 다른 얘기 꺼내봐야지)"    ← LLM 이 자기 생각으로 인식, 자연스럽게 흐름
```

이 설계로 캐릭터 일관성을 유지한다. 명령은 메타 텍스트로 처리되고, 혼잣말은 대사로 통합된다.

## 메모리 아키텍처

```mermaid
graph LR
    linkStyle default stroke:#888,stroke-width:1.5px
    L0["📝 L0 원본\nconversations 테이블\n(영구)"]
    L1win["📋 L1 워킹 윈도우\n최근 ~15개 그대로\n(매 턴 라이브 주입)"]
    L2ep["📦 L2 에피소드"]
    Facts["📚 L3 의미 사실\n(subject, predicate, object)\nvalid_from/valid_to supersession"]
    Rel["💞 L4 관계\n스냅샷 + 변곡점 로그"]
    Pin["📌 L5 Pinned\n항상 주입"]

    subgraph Roll["에피소드 rollup 레벨"]
        direction LR
        D1["digest\nN 메시지 → 1"]
        D2["단락\n5 L1 → 1"]
        D3["월간\n5 L2 → 1"]
        D1 -->|"rollup"| D2 -->|"rollup"| D3
    end

    L0 -->|"라이브"| L1win
    L1win -->|"async Haiku"| L2ep
    L2ep --- Roll
    L1win -.->|"facts/rel deltas"| Facts & Rel

    style L0 fill:#1a3a1a,stroke:#4aff4a,color:#fff
    style L1win fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style L2ep fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Facts fill:#2a3a1a,stroke:#9aff4a,color:#fff
    style Rel fill:#3a2a1a,stroke:#ffaa4a,color:#fff
    style Pin fill:#3a3a1a,stroke:#ffff4a,color:#000
```

방어 장치:
- `_validate_fact()` 가 추상 subject(`"새_멤버"`), 일시 object(`"오랜만"`), 중복 self-fact 를 제거한다.
- `PREDICATE_ALIASES` 가 40+ 변형을 canonical 로 정규화한다.
- 비밀 채널 메모리는 오너 채널 주입 시 disclosure 마커를 붙인다.

## 모델 스왑·프로필 수정에도 맥락이 유지되는 이유

- 상태는 프롬프트 외부 저장소에 있다. Haiku → Sonnet → 로컬 Llama 로 교체해도 관계·fact·pinned 는 유지된다.
- 프로필 수정 시 `invalidate_cache()` 와 `runtime.refresh_agent()` 를 함께 실행해 즉시 반영한다. 반복 질문 회귀를 막는다.

## LLM 모델 역할 (기본 설정)

| 역할 | 모델 | 이유 |
|---|---|---|
| 메모리 추출 | `claude-haiku-4-5` | 싸고 빠름, 매 배치마다 백그라운드 worker |
| Supervisor / judge | `claude-haiku-4-5` | 경량 상태 판정 |
| 에이전트 응답 (기본) | `claude-haiku-4-5` | 대화량 많고 지연 민감 |
| 추론 / 도구 조합 | `claude-sonnet-4-6` | 대시보드에서 per-agent 오버라이드 |
| 원샷 구조화 출력 | `claude-opus-4-6` | 프로필 JSON, 복잡 생성 |
| 자가 치유 | `claude-opus-4-6` | 런타임 에러 기반 소스 패치 |
| 로컬 / 대안 | Ollama · Grok | 로컬 무료(Ollama) + Grok CLI; vLLM / llama.cpp 는 예정 (`AVAILABLE_MODELS` 스텁 준비됨) |

균일 Sonnet 대비 약 10배 저렴하다.

## 웹 대시보드 (Glimi Core 의 관찰성)

대시보드는 Glimi Core 에 포함된다. 그래프·메모리 인스펙터·채널 뷰어·도구 로그를 전 에이전트에 제공한다. **읽기 전용**이며 모델 스왑 *쓰기* 는 Community/Workspace 기능이다.

| 연결 그래프 | 메모리 인스펙터 |
|---|---|
| <img src="screenshots/ko/04-graph-live.png" height="300" alt="연결 그래프"/> | <img src="screenshots/ko/02-persona-memory.png" height="300" alt="메모리 인스펙터"/> |

- **Cytoscape.js 그래프** — 에이전트 연결·채널 활동·supervisor overlay 표시
- **메모리 인스펙터 (L0–L5)** — pinned, 에피소드, 의미 사실, 관계 변곡점 표시
- **실시간 채널 뷰어** — 각 에이전트의 현재 시점 표시
- **도구 호출 타임라인** — `<tools>` 호출 이력과 결과 표시
- **에이전트별 모델 (읽기 전용)** — 클라우드/로컬 모델 표시 (스왑은 Community/Workspace 전용)

## Community 아키텍처 (웹 우선; Discord = 선택 어댑터)

```mermaid
flowchart LR
    linkStyle default stroke:#888,stroke-width:1.5px
    subgraph Owner["👤 오너"]
        Web["🌐 내장 웹 채팅 + 대시보드"]
    end

    subgraph Engine["Community 엔진 (Glimi Core 기반)"]
        Plat["🧩 Platform (FastAPI · WebSocket)"]
        Core["⚙ Glimi Core<br/>(runtime · memory · supervisors)"]
        DB[("SQLite<br/>community.db")]
        Log["📄 logs/system.log<br/>(런타임 도구 로그)"]
        Bot["🤖 Discord 어댑터<br/>(선택)"]
    end

    subgraph Channels["💬 채널"]
        DM["💬 dm-{이름}<br/>매니저 dm-agent-mgr-001 포함"]
        Grp["👥 group-{이름들}"]
        SecDM["🔒 internal-dm-A-B"]
        SecGrp["🔒 internal-group-A-B-C"]
    end

    Web <-->|"대화 (WebSocket)"| Plat
    Plat <--> Core
    Core <--> DB
    Core -.->|"도구 호출 로그"| Log
    Owner <-->|"대화"| DM & Grp
    Owner -. "spy 🔍 읽기만" .-> SecDM & SecGrp
    Bot -. "선택 미러링" .-> Plat

    style Engine fill:#1a3a2a,stroke:#4aff9e,color:#fff
    style Core fill:#1a3a5c,stroke:#4a9eff,color:#fff
    style SecDM fill:#2d2d2d,stroke:#f5c542,color:#fff
    style SecGrp fill:#2d2d2d,stroke:#f5a142,color:#fff
```

원칙: **내장 웹 채팅이 1급 주력, Discord 는 선택 어댑터일 뿐 커널이 아니다.** Glimi Core 는 `discord` 를 import 하지 않는다. Community 가 1급 웹 채팅(FastAPI + WebSocket)을 제공하고, Discord 어댑터는 선택이며 같은 채널을 미러링한다. Telegram / 기타 어댑터가 같은 자리에 붙을 예정이다.

## 채널 구조 (Community)

| 채널 | 생성 시점 | 용도 |
|---|---|---|
| `dm-{에이전트}` (매니저 `dm-agent-mgr-001` 포함) | 첫 부팅 / 에이전트 생성 후 | 오너 ↔ 에이전트 1:1 |
| `group-{이름들}` | 요청 시 | 오너 + 에이전트 멀티 DM |
| `internal-dm-{A}-{B}` | 요청 시 | 에이전트끼리 비밀 1:1 (**오너 읽기 전용**) |
| `internal-group-{이름들}` | 요청 시 | 에이전트끼리 비밀 그룹 (**오너 읽기 전용**) |
| `logs/system.log` (파일) | 런타임 | 런타임 도구 호출 로그 — 채널 아님, 파일 |
