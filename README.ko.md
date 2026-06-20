🇺🇸 [English README](README.md) · 📄 [START HERE — 기여자 온보딩](https://raw.githack.com/jaebinsim/Glimi/main/docs/START_HERE.html)

# Glimi

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white) ![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-A42E2B) ![Status: alpha 0.1.0](https://img.shields.io/badge/status-alpha%200.1.0-orange) ![Backends: Claude · Ollama · vLLM · llama.cpp](https://img.shields.io/badge/backends-Claude%20%C2%B7%20Ollama%20%C2%B7%20vLLM%20%C2%B7%20llama.cpp-4aff9e)

Glimi 는 각자 성격·기억·관계를 가진 AI 캐릭터 한 무리를 굴리는 파이썬 라이브러리다. 캐릭터마다 정하는 건 페르소나와 모델, 둘뿐. 그러면 캐릭터들은 당신하고도 자기들끼리도 대화한다. 뒤에서 supervisor 가 주기적으로 대화를 트고 끊긴 걸 이어줘서, 자리를 비웠다 와도 그사이 나눈 얘기가 채널에 쌓여 있다.

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # 오프라인: API 키·네트워크·추가 패키지 불필요
chat.add_agent("nova", persona="호기심 많은 친구")
print(chat.reply("nova", "안녕!"))     # 실제 모델: backend="claude_cli" 또는 "ollama"
```

캐릭터 두 줄이면 무리가 서는 건, 그 아래에서 엔진이 나머지를 다 떠안기 때문이다 — 이 엔진이 **Glimi Core** 다. 기억은 프롬프트가 아니라 저장소(기본 SQLite)에 쌓이기 때문에, 재시작해도 캐릭터의 모델을 Haiku 에서 로컬 Llama 로 갈아 끼워도 관계·사실·고정 기억이 그대로 따라온다. 들어가는 하드웨어의 컨텍스트 윈도우에 맞춰 기억을 잘라 넣어서 4GB 노트북에서도 24GB 워크스테이션에서도 성격이 잘려 나가지 않고, 모델은 캐릭터마다 클라우드(Claude)와 로컬(Ollama·vLLM·llama.cpp)을 섞어 써도 된다. 로컬로만 돌리면 비용은 0 이다.

그리고 그 무리가 돌아가는 걸 눈으로 본다. 캐릭터 관계 그래프, 캐릭터별 기억 인스펙터, 채널 뷰어, 도구 호출 타임라인, LLM 비용/사용량 카드가 엔진에 내장된 웹 대시보드에 실시간으로 뜬다.

![웹 대시보드](docs/screenshots/en/11-community-dashboard.png)

이 Core 위에 앱을 올린다. 플래그십은 **Glimi Community** — 내장 웹 UI(또는 디스코드)에서 대화하는 'AI 친구들' 무리로, 자기들 채널에서 떠들고, 비밀을 지키고, 당신이 없을 땐 당신 얘기도 하고, 그걸 다 기억한다. 역할을 나눈 작업용 **Glimi Workspace** (Coordinator 가 Researcher·Builder·Critic 에게 일을 배분 — 실시간 라이브 데모 포함), 그리고 `examples/` 의 라이브러리 스타터들도 같은 Core 위에 선다.

![Glimi Community](assets/brand/Glimi-Community-banner.svg)

> 용어 한 줄: 여기서 "에이전트"는 Stanford *Generative Agents* 계보 — 기억하고 생각을 형성하고 서로 말을 거는 캐릭터 — 의 의미지, 일을 자동으로 끝내는 task-runner 가 아니다. 코드·구조 얘기엔 *agent*, 사용자가 보는 자리엔 *친구·캐릭터*.

> **현황 (2026-06)** — Core 커널은 최상위 `glimi/` 패키지(Discord/DB 의존 0, 단독 import)이고, **두 앱 모두 의존성 주입(DI)으로 그 위에서 돈다**: 각자 자기 `KernelStore`/profile/observer 어댑터를 중립 커널에 주입(Community 는 `src/adapters/`, Workspace 는 `glimi` 패키지만으로). 대시보드 UI 는 `glimi/dashboard` 안의 단일 정본 셸을 셋(커널 데모·Community·Workspace) 다 렌더한다. 아직 PyPI 전이라 소스에서 설치 (`pip install -e ".[dashboard]"`). 이제 캐릭터와 얘기하는 기본 경로는 내장 **웹 챗**(라이트/다크, 답글, 반응, 스레드, 모바일)이라 **디스코드는 선택사항** — 예정된 여러 어댑터 중 하나. 최근 추가: **평가 하네스**(골든셋 + LLM-as-judge + 회귀 게이트), **도구 호출 + 비용/지연 관찰성**, Workspace 의 **사람 개입 승인 게이트(HITL)**.

```
Glimi/                            단일 git repo (모노레포) · `glimi` 는 PyPI 로 배포
├── glimi/                        ← Glimi Core — 커널   ·  pip install "glimi[dashboard]"
│   ├── runtime.py                · 에이전트 런타임, 에이전트별 모델 스왑; store/profile/observer 중립 (DI)
│   ├── memory.py                 · 5 레이어 영속 메모리 (비동기 추출, 사실 supersession)
│   ├── context_budget.py         · Elastic Memory — 하드웨어 인식 컨텍스트 예산
│   ├── conversation.py           · 자율 에이전트-간(A2A) 루프
│   ├── tools/                    · <tools><call/></tools> 프로토콜 + 레지스트리
│   ├── llm/                      · Claude CLI · Ollama · anthropic SDK 백엔드 (+ pricing)
│   ├── store.py · stores/        · KernelStore ABC + 인메모리 구현
│   └── dashboard/                · 라이브 관찰성 웹 UI (그래프 · 메모리 · 도구 로그 · 사용량)
├── src/                          ← Glimi Community — flagship 앱 (Core 가 여기서 추출됨)
│   ├── platform/                 · FastAPI 플랫폼 · 내장 웹 챗 · 대시보드 호스트
│   ├── adapters/kernel_store.py  · SqliteKernelStore(KernelStore) — 앱을 커널에 주입 (DI)
│   ├── core/                     · glimi(runtime·memory) 위 얇은 shim + 커뮤니티 전용 모듈
│   └── scenes/ · achievements/ · bot/   · 커뮤니티 전용 (씬, 도전과제, 디스코드 어댑터)
├── apps/workspace/               ← Glimi Workspace — 추출된 Core 위에 새로 지은 2번째 앱 (재사용성 증명)
├── examples/                     · 라이브러리 스타터 (research_buddies · dev_pair · dashboard_demo)
├── eval/                         · 평가 하네스 (골든셋 · LLM-judge · 회귀 게이트)
├── docs/ · tests/
├── LICENSE · NOTICE · CITATION.cff   · AGPL-3.0 + 저작자/인용
└── README.md · README.ko.md          · 영문 + 이 파일
```

> **왜 레이아웃이 두 개냐면** — Glimi Core(`glimi/`)는 **작동하는 앱(Glimi Community, `src/`)에서 추출**한 커널이라 이론이 아니라 검증된 물건이다. **Glimi Workspace**(`apps/workspace/`)는 그 추출된 `glimi` 패키지 *위에만* 새로 지었다(`src/` import 0) — 하나의 커널 위에 성격이 전혀 다른 두 번째 앱이 도는 게 Core 가 진짜 재사용 가능하다는 증거다. `glimi` 패키지는 이 모노레포에서 단독으로 빌드·PyPI 배포되고, 두 앱은 그걸 쓰는 **실제 애플리케이션**이다.

---

## Glimi 의 차별점

Glimi Core 는 세션마다 처음으로 돌아가지 않는 에이전트를 만드는 엔진이다. 보통의 도구는 일이 들어올 때마다 역할을 띄웠다 버리고, 컨텍스트가 차면 압축하고, 다음 세션엔 핸드오프 문서를 읽혀 복원시킨다. Glimi 는 그 단계를 두지 않는다. 각 에이전트가 자기 맥락 — 무슨 일을 해왔는지, 어떤 결정이 왜 내려졌는지, 당신의 취향과 가치, 당신과의 관계 — 을 자기 저장소에 들고 있어서, 세션이 끊겨도 모델을 갈아끼워도 그대로 따라온다. 같은 영속성이 일에서는 **Glimi Workspace**, 사람 사이에서는 **Glimi Community** 로 나타난다. 한쪽은 매번 다시 브리핑하지 않아도 되는 상주 팀이고, 다른 쪽은 당신을 정말로 기억하는 친구들이다. 두 앱은 Core 가 뭘 할 수 있는지 보여주는 예시고, 엔진은 그 아래 한 겹으로 똑같이 쓰인다.

요즘 오픈소스 에이전트 프레임워크는 많다: LangChain/LangGraph, AutoGen, CrewAI, OpenAI Agents SDK, Letta 등. 대부분은 에이전트를 **task** 에 태워 돌린 뒤 버린다. 일부는 영속 메모리를 갖췄고(Letta), 일부 연구·게임 프로젝트는 에이전트가 자기들끼리 살아가게 한다(Stanford Generative Agents, AI Town). Glimi 는 이 흩어진 조각들을 **하나의 pip 설치형 런타임**으로 모은다. 그중 둘은 정말로 드물다:

**1. 하드웨어에 맞는 메모리 (Elastic Memory).** Glimi 는 모델의 컨텍스트 윈도우를 측정해 주입할 메모리 양을 거기 맞게 조절하며, 절대 초과하지 않는 하드 보장을 둔다. 같은 에이전트가 4GB 노트북에서도, 24GB 워크스테이션에서도, 성격이 조용히 잘려나가는 일 없이 돈다. 에이전트 프레임워크들도 히스토리를 윈도우에 맞게 잘라낼 수는 있지만(CrewAI·Letta·OpenAI Agents SDK·AutoGen·LangGraph 가 각자 어떤 형태로든 한다), 메모리 버짓을 **하드웨어**에 맞춰 잡거나 **절대 초과하지 않는 하드 보장**을 주는 곳은 없다. 로컬 런타임들도 안 한다: Ollama 자체의 "VRAM 에 맞춰 컨텍스트 자동 조절" 요청은 2025년부터 미해결 이슈로 열려 있다.

**2. 무료·내장 런타임 안의 드리프트 방지 메모리.** Glimi 의 사실(fact)에는 유효기간이 있다. 새 사실이 옛 사실과 모순되면 옛 것을 supersede(이력은 보존, 삭제 X) 처리해서 에이전트가 낡은 믿음을 끌고 다니지 않는다. 이 아이디어의 레퍼런스 구현인 Zep 의 Graphiti 는 그래프 UI 가 Zep 의 독점 호스팅 플랫폼 안에 있는 메모리 *엔진*이고(무료 티어는 있지만, 그래프 UI 는 오픈소스 Graphiti 패키지에 포함되지 않는다), Mem0 는 2026년에 모순 해소 기능을 아예 제거했다. Glimi 는 supersession·런타임·대시보드를 한꺼번에, 무료로 제공한다. (Glimi 버전은 SQLite 의 행 단위 supersession 으로 스코프가 작다 — Graphiti 의 완전한 bi-temporal 그래프는 아니다 — 하지만 아이디어의 실용적 핵심이다.)

이 둘을 중심으로, 통합 자체가 포인트다:

- **설계된, 영속적인 인구.** 각 에이전트의 페르소나와 모델을 정의하고, 클라우드(Claude)와 로컬(Ollama / vLLM / llama.cpp)을 한 fleet 에 섞는다. 상태가 프롬프트가 아니라 스토리지에 살기 때문에, 모델을 갈아끼워도 에이전트는 모든 기억과 관계를 유지한다. 에이전트별 모델 선택 자체는 흔하다(Letta·CrewAI·AutoGen 다 됨). 드문 건 그걸 스왑에도 살아남는 영속 상태와 묶은 점이다.
- **스스로 움직이는 에이전트.** proactive supervisor 가 타이머로 돌며 새 에이전트-간 대화를 열고, 멈춘 채널을 되살리고, 씬을 진행시킨다. 그래서 인구가 당신 메시지 사이에도 계속 살아간다. 대부분의 프레임워크는 순수 reactive 다. 자율성을 제대로 구현한 프로젝트들(Stanford 의 마을, AI Town)은 연구 코드거나 게임 스택이지, 위에 빌드할 수 있는 라이브러리가 아니다.
- **저사양 친화적.** 여러 에이전트가 로컬 모델 하나를 공유하고 컨텍스트만 스왑한다(가중치 재로드 없음). 그래서 fleet 전체가 16GB 한 대에서 돈다. 이건 Ollama 의 상주 모델 동작에 얹힌 것이고, Glimi 의 몫은 에이전트별 상태를 관리해 그 공유를 매끄럽게 만드는 것이다.
- **인구 대시보드 내장.** 실시간 웹 UI 가 엔진과 함께 온다: 에이전트 관계 그래프, 에이전트별 5 레이어 메모리 인스펙터, 라이브 채널 뷰어, 에이전트별 모델 스왑. 무료 로컬 에이전트 대시보드는 이미 있지만(Letta ADE, Hermes HUD) 한 번에 한 어시스턴트를 들여다본다. Glimi 는 인구 전체의 *관계*를 중심으로 본다.

나머지는 솔직하게: Glimi 는 알파(0.1.0, 아직 PyPI 미배포)고, 거의 모든 개별 기능에는 더 강한 선두주자가 있다 — 순수 메모리 페이징은 Letta, 자율 마을 경험은 AI Town, 캐릭터 도구는 SillyTavern, 시간 그래프는 Zep. Glimi 의 승부수는 개별 항목이 아니라 그 조합이다.

### Glimi vs. 대안들

여기 어떤 프로젝트도 그냥 뒤처진 게 아니다. 각자 어딘가에서 앞선다. Glimi 의 위치는 이렇다.

| 기능 | Glimi | Letta (MemGPT) | AI Town | Zep / Graphiti | CrewAI / LangGraph | SillyTavern |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| pip 설치형 라이브러리, fleet 직접 설계 | ✅ | ✅ | ❌ TS 게임 스택 | ✅ 엔진만 | ✅ | ❌ 챗 프론트엔드 |
| 에이전트별 모델, 한 fleet 에 클라우드+로컬 | ✅ | ✅ | ❌ 단일 공유 모델 | — | ✅ | ◐ |
| 모델 스왑에도 메모리 유지 (상태=스토리지) | ✅ | ✅ | ✅ | ✅ | ◐ | ◐ |
| 시간 기반 fact supersession (드리프트 방지) | ✅ 스코프 | ❌ | ❌ | ✅ 레퍼런스 | ❌ | ❌ |
| 자율 에이전트-간 대화 (스스로 시작) | ✅ | ❌ | ✅ | ❌ | ❌ | ◐ |
| 하드웨어 인지 elastic 컨텍스트 버짓 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 관계 그래프 + 메모리 대시보드 내장 | ✅ | ◐ 단일 | ◐ 시뮬뷰 | ❌ 호스팅 | ❌ 별도 | ❌ |

✅ 됨 · ◐ 부분 · ❌ 안 됨 · — 해당 없음. 솔직한 평: 메모리 페이징은 Letta 가 더 깊고, AI Town 은 더 다듬어진 세계와 훨씬 많은 사용자를 가졌고, Zep 의 시간 그래프가 더 완전하고, SillyTavern 의 캐릭터 도구가 더 풍부하다. Glimi 는 이 일곱 줄을 한 번에, 하나의 AGPL-3.0 패키지로 하는 유일한 쪽이다.

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
| **라이브 관찰성 대시보드** | Cytoscape.js 에이전트 그래프, per-agent 5 레이어 메모리 인스펙터, 실시간 채널 뷰어, 도구 호출 타임라인, LLM 사용량/비용 카드, 모델 스왑 UI, 런타임 상태 배지 |
| **평가 하네스** | 페르소나 / 도구사용 / 메모리 / 폴백 / 슈퍼바이저 능력별 골든셋; 결정적(deterministic) 체크 + LLM-as-judge(재사용, 재발명 아님); 백엔드 태깅된 **회귀 게이트**(pass-rate 또는 judge 점수 하락 시 CI 실패); 플래그된 나쁜 턴을 골든 케이스로 승격하는 프로덕션 피드백 루프. 오프라인 `echo` 백엔드에서 무료 실행 |
| **비용·지연 정산** | 모든 LLM 호출이 토큰·추정 비용·지연을 한 choke-point 에서 기록하고, 모든 도구 호출이 args/result/지연/성공여부를 또 한 곳에서 기록. 설계상 정직 — 로컬/echo 는 $0, CLI/추정 행은 *est.* 표시, 실제 과금된 지출에만 달러 표기 |
| **사람 개입 게이트** | 중대한 액션 둘레의 승인 정책(`승인 / 수정 / 거부` + 폴백 + 결정 로그). Workspace 가 사용; 절대 멈추지 않음(비대화형은 자동 승인) |
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

이 한 끗 차이가 캐릭터를 깨는 에이전트와 안 깨는 에이전트를 가른다: 명령은 메타 텍스트로 응답에 새어 나오고, 혼잣말은 다음 대사에 자연스럽게 녹는다.

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

Glimi Core 는 **알파 (0.1.0, 아직 PyPI 미배포)** — 당분간은 소스 체크아웃에서
설치. 커널은 의존성 없는 인메모리 스토어와 **오프라인 `echo` 백엔드**를 기본 탑재해서,
아래 예제는 **의존성 0·API 키 없이** 바로 돌아간다 (`echo` 백엔드는 실제 모델을
호출하지 않고, 하네스가 배선되고 대화가 저장되는 걸 눈으로 확인시켜 줄 뿐):

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # 오프라인: 의존성·API 키·네트워크 전부 불필요
chat.add_agent("nova", persona="호기심 많고 잘 묻는 명랑한 친구.")

print(chat.reply("nova", "안녕! 이름이 뭐야?"))
print(chat.reply("nova", "좋네 — 재밌는 얘기 하나 해줘."))
```

백엔드만 바꾸면 실제 모델로 전환된다 (나머지 코드는 그대로):

```python
chat = Glimi(backend="claude_cli")    # Claude CLI 로그인 사용 (SDK 불필요) — 구독 무료가 아니라 사용량만큼 과금(metered)
chat = Glimi(backend="ollama")        # Ollama 로 완전 로컬 — 무료 옵션 (GLIMI_OLLAMA_MODEL 설정)
```

`Glimi` 가 구성요소를 알아서 배선해 준다 — 인메모리 `KernelStore`, 간단한
`ProfileProvider`/`OwnerContext`, `NullObserver`, 그리고 선택한 LLM 백엔드. 기본값을
넘어서고 싶으면 각 조각을 직접 가져다 쓸 수도 있다:

```python
from glimi import (
    InMemoryKernelStore, SimpleProfileProvider, SimpleOwnerContext,
    KernelStore, ProfileProvider, OwnerContext, KernelObserver,  # 직접 구현할 seam
    LLMBackend, LLMResponse, EchoBackend,
)
```

본인 DB 를 쓰려면 `KernelStore` (선택적으로 `ProfileProvider`/`OwnerContext`/
`KernelObserver`) 를 구현해 `glimi.runtime.set_store(...)` 등으로 주입. 완성된 실동작
배선(SQLite + Discord)은 repo 에 있음:

- `src/adapters/kernel_store.py` — `SqliteKernelStore` + 프로필/옵저버 어댑터
- `src/core/runtime.py` — 커널에 주입 + API 재export

### 웹 대시보드 (Glimi Core 의 관찰성)

대시보드는 Glimi Core 의 일부 — Community 전용이 아님. 그래프·메모리 인스펙터·채널 뷰어·도구 로그·모델 스왑 UI 는 어떤 에이전트 인구든 동작함.

| 연결 그래프 | 메모리 인스펙터 |
|---|---|
| <img src="docs/screenshots/en/04-graph-live.webp" height="300" alt="연결 그래프"/> | <img src="docs/screenshots/en/02-persona-memory.png" height="300" alt="메모리 인스펙터"/> |

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

Community 는 Glimi Core 위에 올린 **실제로 쓸 수 있는 애플리케이션** — flagship 이자, Core 가 처음 추출돼 나온 앱이다. (엔진이 뭘 가능하게 하는지 보여주는 reference 이기도 하지만, 데모가 아니라 실제로 돌리는 제품이다.)

Community 의 친구들은 당신을 기억한다. 처음 만난 사람한테 매번 자기소개부터 다시 하는 일이 없다. 같이 보낸 시간, 지난주에 주고받은 농담, 요즘 좀 힘들다고 털어놨던 날, A 한테만 말해둔 비밀까지 각자 자기 저장소에 쌓아둔다. 그래서 며칠 만에 돌아와도 "오랜만이네, 그때 그 일은 잘 됐어?" 하고 먼저 묻는다. 모델을 Haiku 에서 로컬 Llama 로 바꿔 끼워도 당신과 쌓은 관계와 분위기, 그 안의 결까지 그대로 따라온다. 매번 리셋돼서 당신이 누군지 다시 알려줘야 하는 챗봇이 아니라, 이미 당신을 아는 친구들이다.

![연결 그래프 — 라이브](docs/screenshots/en/04-graph-live.webp)

### 직접 대화 — 내장 웹 챗

이제 디스코드가 없어도 된다. Community 는 자체 채팅을 내장한다 — 캐릭터별 사이드바, 묶음 메시지 행(grouped rows), 답글, 반응, 스레드를 갖춘 디스코드식 레이아웃에 라이트/다크 테마, 모바일까지 된다. 대시보드에서 읽던 그 방이 곧 타이핑하는 방이다 — 연결 그래프와 채팅은 한 저장소의 두 화면이다(그래프의 선을 클릭하면 그 대화로 바로 들어간다).

| 웹 챗 (라이트) | 웹 챗 (다크) | 모바일 |
|---|---|---|
| <img src="docs/screenshots/en/08-web-chat.png" alt="웹 챗 — 라이트"/> | <img src="docs/screenshots/en/09-web-chat-dark.png" alt="웹 챗 — 다크"/> | <img src="docs/screenshots/en/10-web-chat-mobile.png" height="420" alt="모바일 웹 챗"/> |

디스코드도 그대로 작동한다 — 이제 필수가 아니라 어댑터 하나다. 채팅은 Core 안의 플랫폼 중립 outbox/inbox 심(seam)을 거쳐 WebSocket 으로 오가서, 로드맵의 Telegram 등 다른 어댑터가 같은 자리에 붙는다.

**데모가 이미 들어있다.** 처음 셋업하면 읽기 전용 **데모 커뮤니티**가 목록에 자동으로 하나 들어가 있다 — 토큰도 봇도 없이 채워 둔 목업이라, 뭘 연결하기 전에 Glimi 가 뭘 하는지 바로 본다. 둘러보기 전용 목업이라 메시지 전송은 막혀 있고, 배너로 그걸 분명히 알린다:

<img src="docs/screenshots/en/16-community-demo-readonly.png" alt="읽기 전용 데모 커뮤니티 — 둘러보기 전용 목업" width="820"/>

### 핵심 UX

에이전트들은 내장 웹 챗이든 디스코드든 진짜 멤버처럼 살아간다. 오너와의 DM, **에이전트끼리의 비밀 DM**, 오너가 참여 못 하지만 읽을 수는 있는 그룹챗. 핵심 속성: **채널 간 컨텍스트 누설** — A 에게 DM 으로 한 말이 A↔B 비밀 채널에서 등장, 이후 B 가 오너에게 답할 때 직접 인용 없이 그 맥락이 묻어남.

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
- Claude 백엔드 에이전트용: Anthropic API key *또는* Claude CLI 로그인. 어느 쪽이든 Claude 턴은 **사용량만큼 과금되는 API 크레딧**을 쓴다(headless `claude -p` 는 구독 무료가 아님) — setup 에서 월 상한을 정하라. **무료** 옵션은 **로컬 전용**(전 에이전트 Ollama, $0) 또는 **하이브리드**(페르소나는 로컬/무료, mgr/creator/dev 만 Claude — Glimi 느낌을 유지하는 가장 저렴한 구성).
- Discord 봇 토큰 (Community 풀-스택 가동 시만)

**아무것도 안 깔린 맥** — 한 줄이면 위 사전 요구(Homebrew·Python·Node·Claude CLI)를
알아서 설치하고, 프로젝트 셋업까지 한 뒤 브라우저로 setup 위저드를 열어 준다:
```bash
git clone https://github.com/jaebinsim/Glimi.git && cd Glimi && ./scripts/bootstrap.sh
```
이미 Python 3.12+ 있으면 아래 `./run.sh` 로 바로 가도 된다.

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
./run.sh workspace                      # Glimi Workspace 서버 (홈 + 데모 + 생성) → http://127.0.0.1:8800
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
| <img src="docs/screenshots/en/07-dm-channels.png" width="600" height="382" alt="DM 채널"/> | <img src="docs/screenshots/en/03-achievements.png" width="600" height="382" alt="도전과제"/> |

| 연결 그래프 | 그래프 + supervisor 오버레이 |
|---|---|
| <img src="docs/screenshots/en/05-connection-graph.png" width="600" height="434" alt="연결 그래프"/> | <img src="docs/screenshots/en/06-graph-supervisor.png" width="600" height="434" alt="supervisor 오버레이"/> |

---

## Glimi Workspace — 작업용 팀

한 사람이 운영하는 회사에도 팀은 있다. Glimi Workspace 의 에이전트는 매니저 격인 Coordinator 와 역할을 나눈 동료들(Researcher · Builder · Critic)로 구성된다. 프로젝트 맥락은 한 번만 정해두면 된다 — 무엇을 만드는 중인지, 지난번 그 결정을 왜 내렸는지, 당신이 일을 어떻게 굴리는지. 그걸 각자 자기 저장소에 들고 있어서, 새 세션을 열 때마다 처음부터 다시 설명할 필요가 없다. 모델을 Haiku 에서 Sonnet 으로, 클라우드에서 로컬로 바꿔 끼워도 팀은 같은 맥락 위에서 그대로 이어 일한다. 매번 새로 고용하는 도구가 아니라, 당신을 따라다니며 맥락을 쌓아가는 상주 인력에 가깝다.

Workspace 와 Community 는 *같은* Core 위의 의도적으로 다른 두 앱 — 한쪽은 상주 작업팀, 다른 쪽은 당신을 기억하는 친구들 — 이고 그게 핵심이다: 한 커널 위의 뚜렷이 다른 둘째 앱이야말로 Core 가 모놀리식이 아니라 재사용 가능하다는 증거다. Workspace 는 `glimi` 패키지만 import 한다(디스코드 0, Community 코드 0).

팀은 라운드로빈 한 방에서 일하지 않는다 — 실제 팀처럼 상호작용한다: 오너가 Coordinator 에게 DM, Coordinator 가 각 전문가에게 각도를 배분, 전문가들이 에이전트-투-에이전트 채널에서 **서로** 토론, 그리고 전체가 그룹 라운드로 수렴한 뒤 Coordinator 가 결과를 전달. 이 상호작용들이 작업 관계로 기록되고, 그게 Community 를 그리는 **그** 연결 그래프의 엣지가 된다 — 그래서 작업팀이 실제 상호작용 망으로 나타나고, 멤버마다 자기 5레이어 메모리를 가진다.

#### 한 서버에 여러 워크스페이스

`./run.sh workspace` 는 한 서버가 **여러 워크스페이스**를 띄우는 홈을 연다(Community 플랫폼이 여러 커뮤니티를 띄우는 것과 같다). 읽기 전용 **데모 워크스페이스**가 이미 하나 들어가 있어 둘러볼 수 있고, 이름과 목표를 주면 새 워크스페이스를 만들 수 있다 — 그러면 그 둘레로 새 팀이 꾸려진다. 아무 워크스페이스나 열면 그 팀이 일하는 걸 지켜본다.

<img src="docs/screenshots/en/15-workspace-home.png" alt="Glimi Workspace — 한 서버에 여러 워크스페이스" width="820"/>

#### 라이브로 보기

데모 워크스페이스는 시드된 실시간 쇼케이스다 — 런치 팀을 저장소에 올리고 백그라운드 루프로 계속 움직여서, 대시보드가 보는 앞에서 갱신된다(오프라인, API 키 불필요, **$0**). 한 화면에 전부 보인다: 그래프, 멤버별 메모리·fact, 채널 뷰어(오너 DM, 위임 DM, A2A 토론, 그룹 라운드, 그리고 `mgr-approvals` HITL 기록), 그리고 관찰성 패널 — 도구 호출 타임라인과 정직한 LLM 사용량 카드(로컬/echo 는 $0, 모든 카운트에 *est.* 표시).

| 라이브 팀 대시보드 | 에이전트 상세 — 메모리·fact·관계 |
|---|---|
| <img src="docs/screenshots/en/13-workspace-full.png" alt="Workspace 라이브 데모 대시보드"/> | <img src="docs/screenshots/en/14-workspace-agent-detail.png" alt="Workspace 에이전트 상세"/> |

```bash
./run.sh workspace                      # 워크스페이스 서버 (홈 + 데모 + 생성) → http://127.0.0.1:8800
./run.sh workspace --demo               # 시드된 데모 팀만 서빙
./run.sh workspace --serve              # 실제 목표를 한 번 돌린 뒤 결과를 서빙
./run.sh workspace --serve --approve final   # 최종 결과물에 오너 승인 요구
```

#### 사람 개입 — 승인 게이트

Coordinator 가 중대한 단 하나의 액션 — 최종 결과물 전달 — 을 커밋하기 전에, Workspace 는 그걸 **승인 게이트**로 보낼 수 있다: 오너가 승인/수정/거부하고, 거부 시 결정적 폴백이 들어가며, 결정 기록이 `mgr-approvals`(대시보드에서 확인 가능)에 남는다. 정책은 설정(`--approve auto|final|off`)이고 절대 멈추지 않는다 — 비대화형 실행(CI·파이프·데모)은 자동 승인. 평가자가 찾는 바로 그 HITL 심이다: 중요한 액션에 체크포인트, 사후 관찰 가능.

---

## Examples

Community 의 소셜 sim 스캐폴딩 없이 Glimi Core 를 직접 보여주는, 실제로 돌아가는 스타터들. `echo` 백엔드로 의존성 0·API 키 없이 바로 실행되고, 실제 모델로 바꾸면 진짜 협업이 나온다.

| Example | 보여주는 것 |
|---|---|
| [`examples/research_buddies`](examples/research_buddies/) | 두 에이전트가 주제 협업, 번갈아 읽고 요약하며 공유 노트 누적 |
| [`examples/dev_pair`](examples/dev_pair/) | Planner + executor 패턴 — 하나는 task 분해, 하나는 실행, 메모리 공유 |
| [`examples/dashboard_demo`](examples/dashboard_demo/) | 인메모리 저장소에 작은 인구를 시드해 읽기 전용 Core 대시보드로 서빙 (`glimi[dashboard]`) |

---

## 기술 스택

| 컴포넌트 | 기술 |
|---|---|
| **Glimi Core 런타임** | Python 3.12+. Claude 는 Claude CLI subprocess + 완전 로컬 Ollama 백엔드; vLLM / llama.cpp 는 pluggable backend seam 으로 |
| **메모리 저장소 (기본)** | SQLite — `KernelStore` ABC 로 pluggable (커널은 DB 를 직접 안 봄) |
| **도구 프로토콜** | `<tools>` 인라인 XML — 별칭 해석, JSON 타입 인자, 지연 실행 |
| **웹 대시보드** | FastAPI + Jinja2 + Cytoscape.js + htmx |
| **Community 어댑터** | `discord.py` + per-agent Webhook 아바타 |
| **Community 이미지 생성** (opt-in) | Animagine XL 4.0 기반 로컬 LoRA 초상화 (~6분/장, 가중치 186MB) |

---

## 로드맵

**완료 — 커널 추출 + 패키징**
- ✅ `src/core/{runtime, tools, memory, llm, conversation}` → 최상위 `glimi/` — 스토리지/플랫폼 중립, 단독 import (Discord/DB 의존 0)
- ✅ `KernelStore` ABC + `AgentProfile`/`OwnerContext`/`KernelObserver` protocol; Community 은 `src/adapters/` 에서 구체 어댑터 배선
- ✅ `pyproject` 분리: `pip install glimi`(코어, 런타임 의존 0) / `glimi[community]`(앱) — 커널 standalone wheel 빌드

**현재 — 첫 PyPI 배포**
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

**AGPL-3.0-or-later** — 강한 카피레프트. 누구나 자유롭게 사용·연구·수정·공유 가능; 대신 **배포하거나 네트워크 서비스로 제공하는 파생물은 반드시 AGPL 로 소스 공개 + 이 프로젝트 저작자 표기 유지** — 닫아서 독점 제품으로 못 만든다. 기여는 같은 라이선스로 환영하고, 저작권은 저자가 보유해 별도 상업 라이선스를 줄 수 있다. MongoDB·Grafana·Mastodon 과 같은 "열린 채로 + 컨트리뷰터와 성장 + 독점 free-riding 방지" 노선.

전문은 `LICENSE` 파일 참조.
