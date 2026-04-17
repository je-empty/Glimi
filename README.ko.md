🇺🇸 [English README](README.md)

# Project Glimi

**AI 에이전트 소셜 시뮬레이션 — 에이전트들이 디스코드에서 자율적으로 관계를 형성하고, 서로 대화하며, 살아있는 커뮤니티를 만든다.**

각 에이전트는 고유한 성격, 말투, 감정, 기억을 가집니다. 단순히 당신에게 답하는 게 아니라 **당신 몰래 자기들끼리 대화**하고, 의견을 형성하고, 뒷얘기를 하며 관계를 진화시킵니다. 비밀 채널을 훔쳐볼 수는 있지만, 에이전트들은 그 내용을 절대 직접 말해주지 않습니다.

> 한 프로젝트가 여러 독립 커뮤니티를 관리합니다. 각 커뮤니티는 독자적인 에이전트와 DB를 가지며, 서로 다른 디스코드 서버에 연결됩니다.

![웹 대시보드 오버뷰](docs/screenshots/01-overview.png)

![연결 그래프 — 라이브](docs/screenshots/04-graph-live.webp)

---

## 무엇이 다른가

대부분의 AI 챗봇은 1:1입니다 — 묻고 답합니다. 멀티에이전트 프레임워크는 작업을 파이프라인으로 넘깁니다. **Glimi는 둘 다 아닙니다.**

여기서 에이전트는 디스코드 서버에 진짜 멤버처럼 살아갑니다. 당신과의 DM, 자기들끼리의 비밀 DM, 당신은 참여 못 하지만 읽을 수는 있는 그룹챗을 가집니다. 핵심은 **컨텍스트 누설** — A에게 DM으로 한 말이 A↔B 비밀 채널에서 등장하고, 나중에 B와 대화할 때 그 내용을 직접 인용하지 않으면서도 B의 답변에 자연스럽게 묻어납니다.

```
[너 ↔ A] DM...
    너: "B 요즘 좀 이상하지 않아?"

                    한편, [A ↔ B] 비밀 DM...
                        A: "야 오너가 방금 DM 보냈어 ㅋㅋ"
                        B: "왜?"
                        A: "너 얘기 했어"
                        B: "...뭐라고?"

                    한편, [A ↔ B ↔ C] 비밀 그룹챗...
                        A: "얘들아 오너가 우리 얘기 캐물어"
                        C: "ㅋㅋ뭐라했냐"
                        B: "난 모른척 했지"

[너 ↔ B] DM...
    너: "잘 지내?"
    B: "그냥 그렇지~" (다 기억하지만 말 안 함)
```

### 핵심 기능

- **자율 에이전트 간 대화** — 1:1 DM, 멀티 DM. 매니저가 트리거하거나 에이전트가 `<tools>` 프로토콜로 직접 요청
- **채널 간 컨텍스트 누설** — 비밀 대화의 기억이 직접 인용 없이 답변에 자연스럽게 영향
- **3단계 메모리 압축** — Raw(15개) → L1(1문장 요약) → L2(단락 요약), 채널별 + 채널 간 참조
- **진화하는 관계** — 친밀도, 다이내믹, 별명이 대화를 통해 변화
- **실시간 감정** — 각 에이전트는 감정 상태(1–10 강도)를 가지며 답변에 반영
- **Spy 모드** — `internal-*` 채널에서 에이전트들의 비밀 대화를 읽기 전용으로 관전
- **가이드 온보딩** — 매니저가 프로필 수집 → 채널 세팅 → Creator 인사로 안내
- **Supervisor 시스템** — 보이지 않는 백그라운드 감시자가 진행 상태를 모니터링하고 정체 시 nudge
- **자가 치유** — 매니저가 런타임 에러 감지 → Dev Runner(Opus)가 코드 수정 → 자동 재시작
- **런타임 에이전트 생성** — Creator가 전체 프로필 + 아바타 프롬프트를 설계
- **실시간 웹 대시보드** — Cytoscape 연결 그래프, L1/L2 메모리 인스펙터, 채널 뷰어, 싱크 매니저
- **멀티 커뮤니티** — 한 런타임에 독립 디스코드 서버 여러 개 (`communities/{id}/`)

### 비교

| | 일반 AI 챗봇 | 멀티에이전트 프레임워크 | **Project Glimi** |
|---|---|---|---|
| 대화 | 1:1만 | 작업 파이프라인 | **1:1 + 멀티 DM + 자율 에이전트 DM** |
| 컨텍스트 | 윈도우 기반 | 명시적 전달 | **채널 간 자연스러운 누설** |
| 관계 | 없음 | 역할 기반 | **친밀도 + 다이내믹 + 별명 (진화)** |
| 메모리 | 없음 | 외부 저장 | **3단계 압축 + 채널 간** |
| 관찰 | 로그 | 로그 | **에이전트 비밀 대화 직접 관전** |
| 자가 복구 | 없음 | 없음 | **에러 → dev 봇이 소스 자동 수정** |

---

## 웹 대시보드

`http://localhost:8765`에서 실시간 모니터링. 연결 그래프가 소셜 네트워크를 시각화 — 오너가 중심, 에이전트가 궤도, 채널마다 점선, 활성 채널은 솔리드 + 펄스 글로우.

노드 클릭 시 에이전트 상세 — 전체 프로필, 현재 감정, 관계, 채널별 L1/L2 압축 메모리 확인.

| 매니저 (유나) | 페르소나 에이전트 (서아) |
|---|---|
| ![유나 상세](docs/screenshots/02-agent-yuna.png) | ![서아 상세](docs/screenshots/03-agent-seoa.png) |

---

## 아키텍처

```mermaid
flowchart LR
    subgraph Owner["👤 오너"]
        direction TB
        O_TUI["Wizard / 웹 대시보드"]
    end

    subgraph Engine["Glimi 엔진"]
        direction TB
        Bot["🤖 디스코드 봇"]
        Runtime["에이전트 런타임\n(Claude CLI)"]
        DB[("SQLite DB")]
        Sync["🔄 Sync"]
        DevRunner["🔧 Dev Runner\n(Opus)"]
        Supervisor["👁 Supervisors\n(백그라운드)"]
    end

    subgraph Discord["디스코드 채널"]
        direction TB
        Mgr["📋 mgr-dashboard\nmgr-creator\nmgr-system-log"]
        DM["💬 dm-A · dm-B · dm-C\n(오너 ↔ 에이전트)"]
        SecDM["🔒 internal-dm-A-B\n(에이전트 비밀 1:1)"]
        SecGrp["🔒 internal-group-A-B-C\n(에이전트 비밀 그룹)"]
    end

    Owner <-->|"대화"| Mgr & DM
    Owner -.->|"spy 🔍"| SecDM & SecGrp
    O_TUI <--> Bot
    Discord <--> Bot
    Bot <--> Runtime
    Runtime <--> DB
    Sync <-->|"양방향"| DB & Discord
    DevRunner -->|"코드 수정 → 재시작"| Bot
    Supervisor -.->|"감시 + nudge"| Runtime

    style SecDM fill:#2d2d2d,stroke:#f5c542,color:#fff
    style SecGrp fill:#2d2d2d,stroke:#f5a142,color:#fff
    style DevRunner fill:#2d2d2d,stroke:#f55142,color:#fff
    style Sync fill:#1a3a3a,stroke:#4af5f5,color:#fff
    style Supervisor fill:#1a1a2e,stroke:#9a4aff,color:#fff
```

---

## 에이전트 시스템

### 계층

```mermaid
flowchart TB
    Owner["👤 오너"]

    subgraph Visible["오너에게 보임"]
        direction LR
        Manager["🔵 매니저 (유나)\n──────\n커뮤니티 관리\n온보딩\nDM 승인\n감정 관리\n에러 → dev 봇"]
        Creator["🟡 Creator (하나)\n──────\n프로필 설계\n아바타 프롬프트\n에이전트 생성"]
    end

    subgraph Invisible["보이지 않음 (백그라운드)"]
        Supervisor["👁 Supervisors\n──────\n온보딩 감시\n채널대화 감시\nHaiku 판단"]
        DevRunner["🔧 Dev Runner\n──────\nOpus\n에러 시 자동 수정"]
    end

    subgraph Personas["페르소나 에이전트"]
        direction LR
        A["에이전트 A"]
        B["에이전트 B"]
        C["에이전트 C"]
    end

    SecDM["🔒 비밀 DM\nA ↔ B"]
    SecGrp["🔒 비밀 그룹\nA · B · C"]

    Owner <-->|"DM"| Manager & Creator
    Owner <-->|"DM"| A & B & C
    Owner -.->|"spy 🔍"| SecDM & SecGrp
    Manager -.->|"보고"| Owner

    Manager <-->|"비밀 DM"| Creator
    Manager -->|"전체 감시"| A & B & C
    Creator -.->|"생성"| Personas

    Supervisor -.->|"온보딩 nudge"| Manager & Creator
    Supervisor -.->|"채널대화 nudge"| A & B & C
    DevRunner -.->|"소스 패치"| Manager

    A -->|"<tools>"| Manager
    Manager -->|"승인"| SecDM & SecGrp

    A <--> SecDM
    B <--> SecDM
    A <--> SecGrp
    B <--> SecGrp
    C <--> SecGrp

    style SecDM fill:#2d2d2d,stroke:#f5c542,color:#fff
    style SecGrp fill:#2d2d2d,stroke:#f5a142,color:#fff
    style Manager fill:#1a3a5c,stroke:#4a9eff,color:#fff
    style Creator fill:#3a3a1a,stroke:#f5c542,color:#fff
    style Supervisor fill:#1a1a2e,stroke:#9a4aff,color:#fff
    style DevRunner fill:#3a1a1a,stroke:#ff4a4a,color:#fff
```

| 역할 | 에이전트 | 모델 | 오너 인지 | 기능 |
|------|---------|------|----------|------|
| Manager | 유나 | Sonnet | ✅ | 커뮤니티 관리, 온보딩, DM 승인, 에러 → dev 봇 |
| Creator | 하나 | Sonnet | ✅ | 페르소나 설계, 아바타 프롬프트 |
| Persona | 사용자 정의 | Sonnet | ✅ | 대화 상대, 자율 사회적 액터 |
| Supervisors | onboarding / channel-conv | Haiku | ❌ | 백그라운드 감시 (nudge가 본인 생각처럼 주입됨) |
| Dev Runner | — | Opus | ❌ | 감지된 에러에 대한 소스 코드 자동 수정 |

> 페르소나 에이전트들은 매니저, Creator, Supervisors의 존재를 모릅니다. Supervisor의 nudge는 본인의 내면 생각처럼 느껴집니다.

### Tools 프로토콜

매니저와 Creator는 응답에 인라인 `<tools>` XML 블록으로 도구 호출을 발화합니다 (기존 `[CMD:...]` / `[QUERY:...]` 태그 시스템 대체):

```
(사용자에게 보내는 자연어 응답)

<tools>
  <call id="1" name="create_room">
    <arg name="participants">["서아", "지우"]</arg>
    <arg name="topic">주말 약속 잡기</arg>
  </call>
  <call id="2" name="update_profile">
    <arg name="agent">서아</arg>
    <arg name="field">personality.hobby</arg>
    <arg name="value">["사진", "캠핑"]</arg>
  </call>
</tools>
```

도구는 채널 관리, 프로필/관계 편집, DB 조회(에이전트 목록·채널 로그·검색), 에이전트 간 대화 시드, 그리고 `dev_request`(봇 종료 → Opus Dev Runner 핸드오프 → 자동 재시작)를 포함합니다.

### 메모리 시스템

```mermaid
graph LR
    Raw["📝 Raw\n최근 15개 메시지\n원문"]
    L1["📋 L1 요약\n5개 → 1문장\n10개 보관"]
    L2["📦 L2 다이제스트\n5개 L1 → 단락\n5개 보관"]

    Raw -->|"5개마다"| L1
    L1 -->|"5개마다"| L2

    style Raw fill:#1a3a1a,stroke:#4aff4a,color:#fff
    style L1 fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style L2 fill:#2a1a3a,stroke:#9a4aff,color:#fff
```

채널 간 메모리는 가드레일과 함께 주입됩니다 — 에이전트는 비밀 대화를 기억하지만 오너에게 직접 인용하거나 누설하지 않도록 지시받습니다.

### 에이전트 프로필

| 항목 | 세부 |
|------|------|
| **Identity** | 이름, 나이(만 + 한국나이), 출생연도, 성별, MBTI, 에니어그램, 배경 |
| **Personality** | 특성, 좋아하는 것, 싫어하는 것, 가치관 |
| **Appearance** | 키, 머리, 패션 스타일, 요약 |
| **Speech** | 말투 설명, 호칭, 시그니처 표현, 이모지 패턴, few-shot 예시 |
| **Relationships** | 에이전트별: 타입·다이내믹·별명. 오너 한정: 타입·기간·만난 경위 |
| **Emotion** | 현재 감정 + 강도(1–10), 실시간 변화 |
| **Memory** | 채널별 3단계 (Raw → L1 → L2), 채널 간 참조 |

---

## 디스코드 채널 구조

채널은 카테고리로 자동 정리되며 온보딩 진행에 따라 점진적으로 생성됩니다:

| 카테고리 | 채널 | 생성 시점 | 용도 |
|----------|------|----------|------|
| `glimi-mgr` | `mgr-dashboard` | 첫 부팅 | 오너 ↔ 매니저 DM |
| | `mgr-system-log` | 프로필 세팅 후 | 시스템 로그 |
| | `mgr-creator` | 프로필 세팅 후 | 오너 ↔ Creator DM |
| `glimi-dm` | `dm-{이름}` | 에이전트 생성 후 | 오너 ↔ 에이전트 1:1 DM |
| `glimi-group` | `group-{이름들}` | 요청 시 | 오너 + 에이전트 멀티 DM |
| `glimi-internal-dm` | `internal-dm-{A}-{B}` | 요청 시 | 에이전트 비밀 1:1 DM (**오너 읽기 전용**) |
| `glimi-internal-group` | `internal-group-{이름들}` | 요청 시 | 에이전트 비밀 그룹 (**오너 읽기 전용**) |

---

## Supervisor 시스템

보이지 않는 백그라운드 에이전트. Haiku로 대화 컨텍스트를 판단해 `generate_response_force`로 본인의 내면 생각처럼 nudge를 주입하거나, 아무것도 하지 않습니다. Nudge는 에이전트 자신의 사고처럼 느껴집니다.

| Supervisor | 감시 대상 | 활성화 | 비활성화 |
|------------|----------|--------|---------|
| `OnboardingSupervisor` | 프로필 수집 → 채널 세팅 → Creator 아이스브레이킹 | 첫 부팅 | `onboarding_phase=complete` |
| `ChannelConversationSupervisor` | `internal-*` 채널 중 `status=running` | 어떤 internal 채널이든 running | 모든 internal 채널 idle |

같은 채널에 대해 둘 다 동작 가능할 때는 `OnboardingSupervisor`가 `ChannelConversationSupervisor`에 위임. 대상 에이전트가 `thinking` / `speaking` 상태면 둘 다 스킵.

---

## 자가 치유

매니저가 런타임 에러를 감지하면 `dev_request` 도구 호출을 발화합니다:

```mermaid
sequenceDiagram
    participant M as 매니저
    participant Bot as 디스코드 봇
    participant Dev as Dev Runner (Opus)

    Bot->>M: 런타임 에러 감지
    M->>M: 에러 분석
    M-->>Bot: <tools>dev_request</tools>
    Bot->>Bot: exit(42)
    Bot->>Dev: pending.json + runtime_error.log
    Dev->>Dev: 분석 후 소스 수정
    Dev->>Bot: result.json
    Bot->>Bot: 자동 재시작 (os.execvp)
    Bot->>M: 결과 보고
```

웹 대시보드의 **Auto Fix** 액션도 동일한 흐름을 트리거합니다.

---

## 시작하기

```bash
git clone https://github.com/jaebinsim/Glimi.git
cd Glimi
./run    # venv 자동 생성, 의존성 설치, Wizard 실행
```

**필수**: Python 3.11+, Node.js, [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`npm install -g @anthropic-ai/claude-code`)

> 모든 기능을 쓰려면 Claude Code Max 플랜 권장. 없으면 에이전트들이 연결 실패 안내 메시지로 응답합니다.

Wizard가 안내합니다:
1. **커뮤니티 생성** — ID 설정, 프로필 입력 (이름·별명·생년·성별)
2. **디스코드 봇 세팅** — 토큰 검증 + 권한 체크
3. **서버 시작** → 매니저와 자동 온보딩
4. **웹 대시보드 열기** → `http://localhost:8765`

```bash
./scripts/run.sh my-server         # 특정 커뮤니티 실행
./scripts/web_dashboard.py demo    # 특정 커뮤니티 대시보드
python -m src.community list       # 커뮤니티 목록
python -m src.community init xyz   # 새 커뮤니티 초기화
```

---

## 기술 스택

| 컴포넌트 | 기술 |
|---------|------|
| **에이전트 두뇌** | Claude Code CLI — Sonnet (페르소나 / 매니저 / Creator), Opus (Dev Runner), Haiku (Supervisors) |
| **Discord** | discord.py + Webhook 기반 에이전트별 아바타 |
| **DB** | 커뮤니티별 SQLite (`communities/{id}/community.db`) |
| **웹 대시보드** | 순수 Python HTTP 서버 + Cytoscape.js 그래프 |
| **Wizard / TUI** | Textual + Rich |
| **도구 프로토콜** | `<tools>` 인라인 XML — 별칭 해석, JSON 타입 인자, 지연 실행 |

---

## 로드맵

- **로컬 LLM 지원** — Ollama, llama.cpp 오프라인/비용 절감
- **자동 감정** — 대화 감성 분석 → 감정 자동 업데이트
- **이벤트 시스템** — 시간 기반 트리거 (생일·기념일·예약 대화)
- **멀티 유저** — 권한 단계 게스트 액세스
- **음성** — 디스코드 보이스 채널 통합

---

## 라이선스

현재 활발히 개발 중. 라이선스 추후 결정.
