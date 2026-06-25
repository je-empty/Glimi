🇺🇸 [English README](README.md) · 📄 [START HERE — 기여자 온보딩](https://raw.githack.com/je-empty/Glimi/main/docs/START_HERE.html)

# Glimi

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white) ![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-A42E2B) ![Status: alpha 0.1.0](https://img.shields.io/badge/status-alpha%200.1.0-orange) ![Backends: Claude · Ollama · Grok](https://img.shields.io/badge/backends-Claude%20%C2%B7%20Ollama%20%C2%B7%20Grok-4aff9e) ![EDD: quality-as-code](https://img.shields.io/badge/EDD-quality--tracked%20per%20commit-9a4aff)

Glimi 는 성격·기억·관계를 가진 AI 캐릭터 무리를 만드는 파이썬 라이브러리다. 캐릭터마다 **페르소나** 와 **모델** 만 지정하면 된다. 캐릭터들은 서로, 또 사용자와 대화한다. supervisor 가 채널을 주기적으로 관리해 대화를 유지하고, 부재 중에도 기록이 남는다.

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # 오프라인: API 키·네트워크·추가 패키지 불필요
chat.add_agent("nova", persona="호기심 많은 친구")
print(chat.reply("nova", "안녕!"))     # 실제 모델: backend="claude_cli" 또는 "ollama"
```

**Glimi Core** 엔진이 데이터와 상태를 관리한다. 기억은 프롬프트가 아니라 SQLite 등에 저장된다. 재시작하거나 모델을 Haiku→로컬 Llama 로 바꿔도 관계·사실·기억이 유지된다. `num_ctx` 값에 따라 기억을 잘라 컨텍스트 길이에 맞춘다. 4096(Ollama)·16384 모델 모두 성격은 동일하다. 캐릭터별로 클라우드(Claude), 로컬(Ollama), Grok CLI 를 조합할 수 있다. 전부 로컬이면 비용이 없다.

엔진 대시보드에서 관계 그래프, 기억 인스펙터, 채널 뷰어, 도구 호출 타임라인, LLM 사용량·비용을 실시간으로 확인한다.

![Glimi — 살아있는 친구들의 커뮤니티, 커넥션 그래프에서 라이브로](docs/screenshots/en/11-community-dashboard.png)

**Glimi Community** 는 Core 위에서 동작하는 기본 앱이다. 내장 웹 UI(또는 디스코드)에서 AI 친구들이 서로 대화하고 기억한다. **Glimi Workspace** 는 역할이 분리된 작업 공간으로 Coordinator 가 Researcher·Builder·Critic 에게 일을 분담한다. 실시간 데모와 `examples/` 스타터도 Core 를 공통 기반으로 둔다.

> 용어: "에이전트" 는 *Generative Agents* 계보의 캐릭터 개념이다. 기억하고 생각하며 대화하는 존재다. task-runner 가 아니다. 코드에서는 *agent*, 사용자 입장에서는 *친구·캐릭터*.

```
Glimi/                           한 레포, 독립 프로젝트 3개 ("워크스페이스" 모노레포)
├── glimi-core/                  ← Glimi Core — 커널        ·  pip install "glimi[dashboard]"
│   ├── glimi/                   ·   runtime · memory · context_budget · conversation · tools · llm · stores · dashboard · edd
│   ├── examples/                ·   라이브러리 스타터 (research_buddies · dev_pair · dashboard_demo)
│   ├── eval/                    ·   골든셋 능력 eval (LLM-judge · 회귀 게이트); glimi.edd = 세대형 E2E EDD
│   └── pyproject.toml           ·   `glimi` / `glimi[dashboard]` 휠 빌드 (유일한 PyPI 산출물)
├── glimi-community/             ← Glimi Community — flagship 앱 (Core 가 여기서 추출됨)
│   ├── community/               ·   FastAPI 플랫폼 · 내장 웹 챗 · 씬 · 도전과제 · 디스코드 어댑터
│   ├── assets/ · i18n/          ·   프로필 이미지 · 다국어
│   └── pyproject.toml · run.sh  ·   glimi[dashboard] 의존
├── glimi-workspace/             ← Glimi Workspace — 커널 위에 새로 지은 2번째 앱 (재사용성 증명)
│   ├── workspace/               ·   코디네이터가 리서처 · 빌더 · 크리틱에게 일을 배분
│   └── pyproject.toml · run.sh  ·   glimi[dashboard] 의존, 커뮤니티 import 0
├── docs/ · tests/ · scripts/ · skills/
├── run.sh · run.bat            ·   개발 런처 (공용 venv 부트스트랩 · 두 앱 실행)
├── LICENSE · NOTICE · CITATION.cff  ·  AGPL-3.0 + 저작자/인용
└── README.md · README.ko.md         ·  영문 + 이 파일
```

> **한 레포, 세 프로젝트.** Glimi Core(`glimi-core/`, `glimi` 패키지)는 **Glimi Community(`glimi-community/`)에서 분리된 커널**이다. **Glimi Workspace**(`glimi-workspace/`) 는 Core 위에 구현된 별도 앱이다. 두 앱은 Core 의 재사용성을 검증한다. 각 폴더는 독립 `pyproject.toml` 을 가진다. 두 앱은 `glimi[dashboard]` 에 의존하며, 레포에서는 로컬 editable 로, 배포 시엔 PyPI 패키지를 사용한다. 폴더별 `cd` 로 개별 실행 가능하다. `glimi` 만 단독 PyPI 배포된다.

---

## 빠른 시작

```bash
git clone https://github.com/je-empty/Glimi.git && cd Glimi
./run.sh                 # Glimi Community (웹 대시보드) → http://localhost:8000
./run.sh workspace       # Glimi Workspace → http://localhost:8800
```

`run.sh` 가 공용 venv 를 만들고 브라우저를 연다. 첫 화면에서 모델(Claude 로그인 또는 로컬 Ollama)과 관리자 비밀번호만 정하면 끝이다. 라이브러리로 임베드하려면 → [Quick Start (라이브러리)](#quick-start-라이브러리). 사전 요구사항과 OS 별 셋업은 → [Quick Start (Community)](#quick-start-community--cross-platform).

---

## Glimi 의 차별점

Glimi Core 는 세션이 끊겨도 초기화되지 않는 에이전트 엔진이다. 요청마다 역할을 재생성하는 일반 도구와 달리, Glimi 는 압축·복원 단계를 생략한다. 각 에이전트는 자기 맥락·결정·사용자 취향·가치를 저장소에 보관한다. 모델을 바꿔도 같은 데이터를 따른다. 이 영속성은 **Glimi Workspace**(작업 팀), **Glimi Community**(기억하는 친구) 로 구현된다. 두 앱은 Core 예시이며 같은 엔진을 쓴다.

기존 오픈소스 프레임워크(LangChain/LangGraph, AutoGen, CrewAI, OpenAI Agents SDK, Letta 등)는 에이전트를 **task** 단위로 실행 후 폐기한다. Letta 에는 영속 메모리가 있고, Stanford Generative Agents·AI Town 에서는 자율 군집이 있다. Glimi 는 이 조각들을 **단일 pip 런타임**으로 묶는다. 핵심 구성은 다음 두 가지다.

**1. 컨텍스트 윈도우 맞춤 메모리 (Elastic Memory).** 메모리를 `num_ctx` 목표값에 맞춰 잘라 프롬프트를 윈도우 내에 유지한다. 완전 보장은 아니며 추정치로 동작한다. 4096·8192·16384 윈도우에서도 동작 방식은 동일하다. CrewAI·Letta·AutoGen 도 히스토리를 자르지만, Glimi 는 윈도우 크기를 직접 버짓으로 삼는다. Ollama 의 VRAM 기반 컨텍스트 조절 이슈는 미해결 상태다.

**2. 내장 런타임의 드리프트 방지 메모리.** `agent_facts` 는 유효기간을 가지며 모순된 정보는 supersede 처리된다(이력 유지). Zep Graphiti 는 독점 UI 포함 엔진, Mem0 는 2026 년 모순 해소 기능이 제거되었다. Glimi 는 supersession, 런타임, 대시보드를 모두 무료 제공한다. SQLite 행 단위 supersession 을 사용하며 작지만 동일하게 동작한다.

이 구조 위에서 다음 기능이 작동한다.

- **영속 인구.** 각 에이전트의 페르소나와 모델을 정의하고 Claude·Ollama 를 묶어 fleet 으로 운영한다. 상태는 스토리지 기반이라 모델 전환 후에도 기억과 관계가 남는다.
- **자율 실행.** proactive supervisor 가 주기적으로 채널을 열어 대화를 이어간다. 대부분 reactive 만 지원하지만 Glimi 는 인구가 스스로 동작한다.
- **저사양 친화.** 여러 에이전트가 로컬 모델 하나를 공유해 16GB 환경에서도 실행된다. Ollama 모델 위에 상태 관리층을 추가했다.
- **인구 대시보드.** 관계 그래프, L0–L5 메모리 뷰, 라이브 채널, 모델 조회를 실시간 표시한다. Letta ADE·Hermes HUD 는 단일 어시스턴트만 다루지만, Glimi 는 인구 단위로 본다.

현재 알파 버전(0.1.0, PyPI 미배포)이다. 기능적으로 Letta·AI Town·SillyTavern·Zep 이 앞서지만, Glimi 는 이 조합으로 차별화된다.

<!--
### Glimi vs. 대안들

프로젝트별 강점은 다르다. Glimi 의 포지션은 다음과 같다.

| 기능 | Glimi | Letta (MemGPT) | AI Town | Zep / Graphiti | CrewAI / LangGraph | SillyTavern |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| pip 설치형 라이브러리, fleet 직접 설계 | ✅ | ✅ | ❌ TS 게임 스택 | ✅ 엔진만 | ✅ | ❌ 챗 프론트엔드 |
| 에이전트별 모델, 한 fleet 에 클라우드+로컬 | ✅ | ✅ | ❌ 단일 공유 모델 | — | ✅ | ◐ |
| 모델 스왑에도 메모리 유지 (상태=스토리지) | ✅ | ✅ | ✅ | ✅ | ◐ | ◐ |
| 시간 기반 fact supersession (드리프트 방지) | ✅ 스코프 | ❌ | ❌ | ✅ 레퍼런스 | ❌ | ❌ |
| 자율 에이전트-간 대화 (스스로 시작) | ✅ | ❌ | ✅ | ❌ | ❌ | ◐ |
| 하드웨어 인지 elastic 컨텍스트 버짓 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 관계 그래프 + 메모리 대시보드 내장 | ✅ | ◐ 단일 | ◐ 시뮬뷰 | ❌ 호스팅 | ❌ 별도 | ❌ |

✅ 됨 · ◐ 부분 · ❌ 안 됨 · — 해당 없음. 메모리 페이징은 Letta 가 깊고, AI Town 은 완성도가 높다. Zep 은 시간 그래프가 더 완전하며, SillyTavern 은 캐릭터 도구가 많다. Glimi 는 이 일곱 줄을 하나의 AGPL-3.0 패키지로 제공하는 유일한 프로젝트다.
-->

---

## Glimi Core — 하네스

![Glimi Core](glimi-core/assets/brand/Glimi-Core-banner.svg)

### 박스 안에 든 것

| 기능 | 상세 |
|---|---|
| **멀티 에이전트 런타임** | 에이전트별 모델 오버라이드 DB 저장. 클라우드(Claude) 와 로컬(Ollama) 이 한 fleet 에 공존 — Grok CLI 도 가능, vLLM / llama.cpp 는 pluggable backend seam 으로 예정. 재시작 없이 스왑 가능 |
| **도구 프로토콜** | `<tools><call id="1" name="...">...</call></tools>` 인라인 XML — 선언적 `ToolSpec` 레지스트리 + 권한·타입·env 게이팅 |
| **레이어드 영속 메모리 (L0–L5)** | L0 원본(`conversations`) → L1 워킹 윈도우(최근 발화 그대로, 라이브 주입) → L2 에피소드 rollup(`memories` 안 L1→L2→L3 digest) → L3 의미 사실(`agent_facts`: subject·predicate·object + `valid_from`/`valid_to` supersession) → L4 관계(`relationships` + 이력) → L5 고정(`memories.is_pinned`). 응답 경로 밖에서 비동기 Haiku 추출 |
| **자율 A2A 대화** | 1:1 및 멀티-에이전트 채널. 턴 제한, closure 감지. 에이전트가 도구 프로토콜로 다른 에이전트와 대화 시작 |
| **Proactive supervisor 레이어** | 입력 없이도 도는 유일한 레이어. 페어 스캐너가 새 에이전트-간 채널을 열고, chat 감시자가 멈춘 채널을 깨우고, scene 감시자가 정체된 워크플로우를 진행시킨다 |
| **라이브 관찰성 대시보드** (`glimi[dashboard]`, 읽기 전용) | Cytoscape.js 에이전트 그래프, per-agent 메모리 인스펙터(L0–L5), 실시간 채널 뷰어, 도구 호출 타임라인, LLM 사용량/비용 카드, 런타임 상태 배지. (라이브 모델 스왑 *쓰기*는 Community/Workspace 플랫폼 기능 — Core 대시보드는 에이전트별 모델을 조회용으로 보여줄 뿐) |
| **평가 하네스** | 페르소나 / 도구사용 / 메모리 / 폴백 / 슈퍼바이저 능력별 골든셋; 결정적(deterministic) 체크 + LLM-as-judge(재사용, 재발명 아님); 백엔드 태깅된 **회귀 게이트**(pass-rate 또는 judge 점수 하락 시 CI 실패); 플래그된 나쁜 턴을 골든 케이스로 승격하는 프로덕션 피드백 루프. 오프라인 `echo` 백엔드에서 무료 실행 |
| **세대형 EDD QA** | 골든셋 eval 의 통합 짝: 자율 **오너 에이전트**가 앱을 온보딩부터 핵심 저니까지 구동하고, 가중 차원으로 채점해 **0–100 품질 점수**, 각 런은 **git-SHA 앵커 "세대"**(SQLite + 커밋 JSON)로 commit-over-commit 추적. flagship 차별점 — **[실측 세대 + flywheel](#edd--eval-driven-development-커밋마다-추적되는-품질-)** 은 위 전용 섹션에. |
| **비용·지연 정산** | 모든 LLM 호출이 토큰·추정 비용·지연을 한 choke-point 에서 기록하고, 모든 도구 호출이 args/result/지연/성공여부를 또 한 곳에서 기록. 설계상 정직 — 로컬/echo 는 $0, CLI/추정 행은 *est.* 표시, 실제 과금된 지출에만 달러 표기 |
| **사람 개입 게이트** (Workspace) | 중대한 액션 둘레의 승인 정책(`승인 / 수정 / 거부` + 폴백 + 결정 로그). Workspace 가 사용; 절대 멈추지 않음(비대화형은 자동 승인) |
| **자가 치유** (실험적, 기본 비활성) | 에이전트가 `request_dev_fix` 호출 → dev_requests 행 큐잉 → dev-queue supervisor 가 트리아지 → 승인 시 Opus subprocess(`GLIMI_DEV_DISPATCH=1`)가 소스 패치 → 봇 재시작 시 패치 요약 주입 |

런타임 8 레이어 파이프라인(프롬프트 조립 → 도구 → 메모리 → 채널 규율 → guard → A2A → 자가치유 → supervisor), L0–L5 메모리 아키텍처와 드리프트 방어 장치, 모델 스왑·프로필 수정에도 맥락이 유지되는 이유는 → [내부 구조 문서](docs/internals.ko.md).

### Quick Start (라이브러리)

Glimi Core 는 **알파 (0.1.0, PyPI 미배포)**. 소스에서 설치한다. 커널은 인메모리 스토어와 **오프라인 `echo` 백엔드**를 내장한다. 예제는 **의존성·API 키 0**으로 실행된다. `echo` 는 모델 호출 없이 하네스 배선을 검증한다:

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # 오프라인: 의존성·API 키·네트워크 전부 불필요
chat.add_agent("nova", persona="호기심 많고 잘 묻는 명랑한 친구.")

print(chat.reply("nova", "안녕! 이름이 뭐야?"))
print(chat.reply("nova", "좋네 — 재밌는 얘기 하나 해줘."))
```

백엔드 교체만으로 실제 모델로 전환된다.

```python
chat = Glimi(backend="claude_cli")    # Claude CLI 로그인 사용 (SDK 불필요) — 구독 무료가 아니라 사용량만큼 과금(metered)
chat = Glimi(backend="ollama")        # Ollama 로 완전 로컬 — 무료 옵션 (GLIMI_OLLAMA_MODEL 설정)
```

`Glimi` 는 인메모리 `KernelStore`, `ProfileProvider`/`OwnerContext`, `NullObserver`, 지정 LLM 백엔드를 자동 배선한다. 세부 제어가 필요하면 각 구성요소를 직접 로드해 사용한다.

```python
from glimi import (
    InMemoryKernelStore, SimpleProfileProvider, SimpleOwnerContext,
    KernelStore, ProfileProvider, OwnerContext, KernelObserver,  # 직접 구현할 seam
    LLMBackend, LLMResponse, EchoBackend,
)
```

자체 DB 를 쓰려면 `KernelStore` 와 필요한 provider/observer 를 구현해 `glimi.runtime.set_store(...)` 로 등록한다. 완성 예시(SQLite + Discord):

- `community/adapters/kernel_store.py` — `SqliteKernelStore` + 프로필/옵저버 어댑터
- `community/core/runtime.py` — 커널 주입 + API 재export

읽기 전용 웹 대시보드(Cytoscape.js 그래프·L0–L5 메모리 인스펙터·채널 뷰어·도구 호출 타임라인)와 기본 LLM 모델 역할 매핑(추출·judge·응답=Haiku, 추론=Sonnet, 구조화 출력·자가치유=Opus, 로컬=Ollama·Grok)은 → [내부 구조 문서](docs/internals.ko.md).

---

## Glimi Community — flagship 앱

![Glimi Community](glimi-community/assets/brand/Glimi-Community-banner.svg)

> *"오너가 자리를 비워도 살아있는 AI 친구 커뮤니티."*

Community 는 Glimi Core 위에 올린 **실제로 쓸 수 있는 애플리케이션** — flagship 이자, Core 가 처음 추출돼 나온 앱이다. (엔진이 뭘 가능하게 하는지 보여주는 reference 이기도 하지만, 데모가 아니라 실제로 돌리는 제품이다.)

Community 의 친구들은 당신을 기억한다. 매번 처음 만난 사람처럼 자기소개부터 다시 하는 일이 없다. 같이 보낸 시간, 지난주에 주고받은 농담, 요즘 좀 힘들다고 털어놨던 날, A 한테만 말해둔 비밀까지 각자 자기 저장소에 쌓아둔다. 그래서 며칠 만에 돌아와도 "오랜만이네, 그때 그 일은 잘 됐어?" 하고 먼저 묻는다. 모델을 Haiku 에서 로컬 Llama 로 바꿔 끼워도 당신과 쌓은 관계와 분위기, 그 안의 결까지 그대로 따라온다. 매번 리셋돼서 당신이 누군지 다시 알려줘야 하는 챗봇이 아니라, 이미 당신을 아는 친구들이다.

![친구들 — MBTI·나이·기분·에이전트별 모델을 각자 가진 한 무리의 커뮤니티](docs/screenshots/en/20-community-cast.png)

![연결 그래프 — 라이브](docs/screenshots/en/04-graph-live.webp)

### 직접 대화 — 내장 웹 챗

이제 디스코드가 없어도 된다. Community 는 자체 채팅을 내장한다 — 캐릭터별 사이드바, 묶음 메시지 행(grouped rows), 답글, 반응, 스레드를 갖춘 디스코드식 레이아웃에 라이트/다크 테마, 모바일까지 된다. 대시보드에서 읽던 그 방이 곧 타이핑하는 방이다. 연결 그래프와 채팅은 한 저장소의 두 화면이라, 그래프의 선을 클릭하면 그 대화로 바로 들어간다.

| 웹 챗 (라이트) | 웹 챗 (다크) | 모바일 |
|---|---|---|
| <img src="docs/screenshots/en/08-web-chat.png" alt="웹 챗 — 라이트"/> | <img src="docs/screenshots/en/09-web-chat-dark.png" alt="웹 챗 — 다크"/> | <img src="docs/screenshots/en/10-web-chat-mobile.png" height="420" alt="모바일 웹 챗"/> |

디스코드도 그대로 작동한다 — 이제 필수가 아니라 어댑터 하나다. 채팅은 Core 안의 플랫폼 중립 outbox/inbox 심(seam)을 거쳐 WebSocket 으로 오가서, 로드맵의 Telegram 등 다른 어댑터가 같은 자리에 붙는다.

**데모가 이미 들어있다.** 처음 셋업하면 읽기 전용 **데모 커뮤니티**가 목록에 자동으로 하나 들어가 있다 — 토큰도 봇도 없이 채워 둔 목업이라, 뭘 연결하기 전에 Glimi 가 뭘 하는지 바로 본다. 둘러보기 전용이라 메시지 전송은 막혀 있고, 배너로 그걸 분명히 알린다:

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

B 가 솔직하게 답한다("마감주간") — 차가웠던 진짜 이유다. B 는 A 를 인용하지 않았다. 하지만 B 메모리엔 *오너가 자기 안부를 캐물었다* 는 fact 가 채널 출처까지 박혀 있다. 이틀 뒤 오너가 "우리 사이 괜찮지?" 하고 물으면 관련 메모리 청크가 주입되고, B 는 4차벽을 깨지 않으면서 그 맥락을 반영해 답한다.

이게 Glimi Core 하네스가 돌아가는 모습이다 — 채널 규율(레이어 4)이 경계를 지키고, 메모리 주입(레이어 3)이 맥락을 나르고, supervisor(레이어 8)가 애초에 그 뒷담 채널을 열었다.

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

Community 아키텍처(웹 우선; Discord = 선택 어댑터) 플로우와 채널 구조(`dm-{이름}`·`group-{이름들}`·오너 읽기 전용 `internal-*` + `logs/system.log`)는 → [내부 구조 문서](docs/internals.ko.md). 원칙은 그대로다: 내장 웹 채팅이 1급 주력, Discord 는 선택 어댑터일 뿐 커널이 아니며 Glimi Core 는 `discord` 를 import 하지 않는다.

### Quick Start (Community) — cross-platform

**공통 사전 요구**:
- Python 3.12+
- Node.js (Claude Code CLI 의존)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code): `npm install -g @anthropic-ai/claude-code`
- Claude 백엔드 에이전트용: **Claude CLI 로그인**(setup 위저드 기본값; `.env` 의 `ANTHROPIC_API_KEY` 도 동작). 어느 쪽이든 Claude 턴은 **사용량만큼 과금되는 API 크레딧**을 쓴다(headless `claude -p` 는 구독 무료가 아님). **무료** 옵션은 **로컬 전용**(전 에이전트 Ollama, $0) 또는 **하이브리드**(페르소나는 로컬/무료, mgr/creator/dev 만 Claude — Glimi 느낌을 유지하는 가장 저렴한 구성).
- Discord 봇 토큰 (선택 Discord 어댑터를 켤 때만)

**아무것도 안 깔린 맥** — 한 줄이면 위 사전 요구(Homebrew·Python·Node·Claude CLI)를
알아서 설치하고, 프로젝트 셋업까지 한 뒤 브라우저로 setup 위저드를 열어 준다:
```bash
git clone https://github.com/je-empty/Glimi.git && cd Glimi && ./scripts/bootstrap.sh
```
이미 Python 3.12+ 있으면 아래 `./run.sh` 로 바로 가도 된다.

**macOS / Linux**:
```bash
git clone https://github.com/je-empty/Glimi.git
cd Glimi
./run.sh                    # 플랫폼 + 대시보드 → http://localhost:8000
                            # 첫 실행 시 브라우저 /setup 마법사가 열려 admin 비밀번호를 설정한다
                            # (헤드리스/비대화형이면 GLIMI_ADMIN_PASSWORD 로 지정)
```

**Windows** (현재 WSL2 권장. 네이티브 `run.ps1` 은 후속 contributor task):
```powershell
# 관리자 PowerShell, 처음이라면:
wsl --install
# WSL Ubuntu 안에서:
sudo apt install python3.12-venv nodejs npm git
npm install -g @anthropic-ai/claude-code
git clone https://github.com/je-empty/Glimi.git
cd Glimi
./run.sh
```

**유용한 명령**:
```bash
./run.sh workspace                      # Glimi Workspace 서버 (홈 + 데모 + 생성) → http://127.0.0.1:8800
./run.sh --port 9000                    # 대시보드 포트 변경
./run.sh --imagegen                     # 로컬 LoRA 초상화 생성 (opt-in, ~6분/장)
./run.sh --legacy <community>           # 레거시 단일 봇 모드 (QA / 디버깅)
./scripts/community_e2e.sh --owner-agent --qa   # 웹 E2E EDD QA — 오너 에이전트 구동, 채점 세대 기록 (docs/qa_system.md)
./scripts/stop.sh                       # graceful shutdown
python -m community.platform.accounts list    # 계정 목록
python -m community.community list            # 커뮤니티 목록
```

> 🚀 **자세한 가이드?** [`START_HERE.html`](docs/START_HERE.html) 의 플랫폼별 walkthrough + 첫 실행 체크리스트 참조.

| DM 채널 뷰 | 도전과제 |
|---|---|
| <img src="docs/screenshots/en/07-dm-channels.png" width="600" height="382" alt="DM 채널"/> | <img src="docs/screenshots/en/03-achievements.png" width="600" height="382" alt="도전과제"/> |

| 연결 그래프 | 그래프 + supervisor 오버레이 |
|---|---|
| <img src="docs/screenshots/en/05-connection-graph.png" width="600" height="434" alt="연결 그래프"/> | <img src="docs/screenshots/en/06-graph-supervisor.png" width="600" height="434" alt="supervisor 오버레이"/> |

---

## Glimi Workspace — 작업용 팀

![Glimi Workspace](glimi-workspace/assets/brand/Glimi-Workspace-banner.svg)

Glimi Workspace 는 혼자 일해도 팀처럼 동작한다. Coordinator 와 Researcher·Builder·Critic 이 역할을 나눈다. 프로젝트 맥락은 한 번만 정리하면 된다. 각 에이전트가 이 정보를 공유하므로 새 세션마다 다시 설명하지 않는다. Haiku, Sonnet, 클라우드, 로컬 환경이 달라도 같은 팀이 이어진다. 일하는 도구가 아니라 맥락을 함께 유지하는 상주 인력처럼 동작한다.

Workspace 와 Community 는 같은 Core 위의 서로 다른 앱이다. Workspace 는 일하는 팀, Community 는 기억하는 친구다. Core 는 모놀리식 구조가 아니다. Workspace 는 `glimi` 패키지만 import 한다(디스코드·Community 코드 없음).

팀은 실제 팀처럼 상호작용한다. 오너가 Coordinator 에게 DM 을 보내면 Coordinator 가 작업을 나누고 전문가들이 에이전트-투-에이전트 채널에서 토론한다. 결과는 그룹 라운드에서 합쳐지고 Coordinator 가 전달한다. 이 기록이 Community 연결 그래프의 엣지가 된다. 각 멤버는 L0–L5 메모리를 가진다.
#### 한 서버에 여러 워크스페이스

`./run.sh workspace` 를 실행하면 한 서버가 여러 워크스페이스를 띄운다. Community 가 여러 커뮤니티를 다루는 방식과 같다. 읽기 전용 **데모 워크스페이스**가 포함되어 있다. 이름과 목표만 지정하면 새 워크스페이스를 만든다. 새 팀이 즉시 구성되고 작업을 바로 볼 수 있다.
<img src="docs/screenshots/en/15-workspace-home.png" alt="Glimi Workspace — 한 서버에 여러 워크스페이스" width="820"/>

#### 라이브로 보기

데모 워크스페이스는 저장된 팀을 실시간으로 보여주는 쇼케이스다. 오프라인, API 키 불필요, **$0**. 한 화면에서 그래프, 멤버 메모리·fact, 채널 뷰어(DM, A2A 토론, 그룹 라운드, `mgr-approvals` HITL), 관찰성 패널을 볼 수 있다. 도구 호출 타임라인과 LLM 사용량 카드(로컬/echo 는 $0, *est.* 표시)가 함께 표시된다.
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

Coordinator 가 결과를 커밋하기 전 **승인 게이트**를 거친다 — 오너가 승인·수정·거부하고, 거부 시 폴백이 실행된다. 정책은 `--approve auto|final|off`, 비대화형(CI·파이프·데모)은 자동 승인이라 멈추지 않는다. 결정은 `mgr-approvals`(대시보드)에 기록된다.
---

## EDD — eval-driven development (커밋마다 추적되는 품질) ⭐

Glimi 는 **EDD(eval-driven development)** 로 멀티 에이전트 품질을 측정한다. 자율 **오너 에이전트**가 앱 온보딩과 주요 저니를 수행하고, 세션을 **가중 차원**으로 채점해 **0–100 종합 점수**를 낸다. 각 런은 **git-SHA "세대"** 로 커밋되어 `git log` 가 품질 타임라인이 된다. 프레임워크는 **`glimi.edd`**, `glimi` 커널 일부이며 Community·Workspace **모두 상속**한다(자기 차원 + 오너 에이전트만 구현).

**채점 규칙** — 각 차원 0–10 점과 가중치, 종합 0–100 정규화. `critical` 실패는 자동 FAIL. LLM-judge 차원은 `echo` 백엔드 없을 때 **skip**. 셀프테스트로 점수가 오르지 않는다. Community 기본 차원 6개:
| 차원 | 종류 | 가중치 | critical | 무엇을 보는가 |
|---|---|:--:|:--:|---|
| `onboarding` | 구조 | 1.0 | | 막 들어온 오너가 매니저한테 인사하고 오리엔테이션을 받는가 |
| `friend_creation` | 구조 | 1.5 | ⭐ | 오너 요청으로 진짜 새 친구가 생성되고 대화까지 이어지는가 |
| `conversation_quality` | LLM-judge | 2.0 | | 답이 사람처럼 자연·일관·맥락있는가 (5축: in_character · coherence · naturalness · engagement · no_meta) |
| `no_hallucination` | LLM-judge | 1.5 | | 사실을 지어내거나 안 한 일을 했다고 하지 않는가 |
| `no_leaks` | 구조 | 1.0 | | 메타 / 에러 / 도구블록 누수가 0 인가 |
| `responsiveness` | 구조 | 1.0 | | 구동된 모든 DM 이 (서로 다른) 답을 받고 멈춤·오류가 없는가 |

### flywheel, 실측치로

`tests/e2e/qa_generations/*.json` 에 **커밋된 세대 데이터**가 있다. `claude_cli` 런 결과를 judge 가 채점했고 각 git SHA 가 기록된다. 목적은 세대별 **품질 데이터 축적 방법**이다. 파일을 보면 흐름이 보인다:
| 세대 | git SHA | 브랜치 | 종합 / 100 | 판정 | `conversation_quality` | `friend_creation` (critical) | 실패 차원 |
|:--:|:--:|---|:--:|:--:|:--:|:--:|---|
| **1** | `1eb4c46`* | `feat/community-qa-system` | **69.4** | ❌ FAIL | 6.0 | **0.0** | friend_creation, conversation_quality |
| **2** | `b3eaf74`* | `feat/community-qa-system` | **75.0** | ❌ FAIL | **9.0** ▲ | **0.0** | friend_creation |
| **3** | `f1eb58a`* | `develop` | **72.5** | ❌ FAIL | 8.0 | **0.0** | friend_creation |
| **4** | `f1eb58a`* | `develop` | **56.9** | ❌ FAIL | 4.0 ▼ | **0.0** | friend_creation, conversation_quality, no_hallucination |
| ⋯ | gens 5–10 | web-native 온보딩 빌드 | 56.9 → 85.0 | 빌드 중 | — | 0.0 → **10.0** | — |
| **11** | `a8d874d`* | `feat/web-native-onboarding` | **85.0** | ✅ **PASS** | 7.0 | **10.0** ▲▲ | — *(첫 PASS)* |

`*` 는 커밋 시점 dirty 상태다. 점수는 JSON 그대로. **gen-11** 에서 web-native 온보딩 빌드(gens 5–10 단계)로 critical `friend_creation` 이 **0 → 10**, 처음으로 ✅ PASS(85/100) 되었다.

세부 지표:
- **`conversation_quality` 6.0 → 9.0 → 8.0 → 4.0 … → 7.0** 은 LLM 변동성을 보여준다. gen-1→2 에서 중복 질문 제거, gen-4 회귀, gen-11 재안정화(7.0).
- **`friend_creation` 은 `critical`, gens 1–10 은 0.0.** supervisor 가 디스코드 봇 내부에만 있어 웹 E2E 실패한 **어댑터 갭**을 수치로 남겼다. web-native 빌드 후 **gen-11 = 10.0 → 첫 ✅ PASS(85/100)**. (`conversation_quality` 7.0, `no_hallucination` 6.0 은 개선 중.)

**요약:** 품질을 git 에 1급 메트릭으로 기록한다. 모든 커밋의 영향이 수치로 보인다. 아래 대시보드·PDF 가 그 타임라인을 나타낸다.
### 보기: `/admin/qa` 대시보드 + PDF 리포트

`/admin/qa` 는 **QA 대시보드**다(admin 로그인 → "QA"). 최신 점수, **트렌드 차트**, 세대별 표를 보여준다. 각 세대를 **PDF** 로 내보낼 수 있다(`glimi.edd.report` 가 HTML 1페이지를 생성하고, Playwright headless Chromium 으로 출력. 서버 렌더 SVG 트렌드 라인을 포함).
![EDD — /admin/qa 대시보드: gen-11 PASS 85, 차원 분해, 세대별 품질 트렌드](docs/screenshots/en/19-edd-dashboard.png)

```bash
# 채점 세대 한 번 (무료 셀프테스트: echo 백엔드, judge skip, 구조 차원만)
GLIMI_LLM_BACKEND=echo .venv/bin/python -m tests.e2e.community_e2e --owner-agent --rounds 2 --qa

# 실측·judged 세대 → SQLite + 커밋용 gen-NNNN-*.json
GLIMI_LLM_BACKEND=claude_cli .venv/bin/python -m tests.e2e.community_e2e \
    --owner-agent --rounds 10 --qa --report

# + PDF 리포트 (트렌드 차트 + 차원; Playwright 필요). --pdf 는 --qa 포함.
GLIMI_LLM_BACKEND=claude_cli .venv/bin/python -m tests.e2e.community_e2e \
    --owner-agent --rounds 10 --pdf --report
```

```bash
git log -- tests/e2e/qa_generations/   # 품질 타임라인 (커밋된 세대들)
git log --grep "qa:"                   # 품질에 영향 준 모든 변경 + 점수 델타
```

**어댑터 재사용** — `glimi.edd` 는 `glimi` 휠에 포함되고 도메인 중립이다. 차원 정의와 오너 에이전트만 구현하면 종합 채점, git-앵커 세대 저장(SQLite + 커밋 JSON), HTML/PDF 리포트를 바로 쓸 수 있다:
```python
from glimi.edd import Dimension, DimResult, build_assessment, GenerationStore

DIMS = [Dimension("onboarding", "온보딩", 1.0, "structural", "신규 사용자 오리엔테이션"),
        Dimension("core_journey", "핵심 저니", 1.5, "structural", "...", critical=True)]
results = [DimResult.for_dim(d, score=..., passed=..., detail="...") for d in DIMS]  # 앱이 평가
assessment = build_assessment(results, min_overall=70)                              # 코어가 0–100 채점
store = GenerationStore(db_path="qa.db", generations_dir="qa_generations/")          # 코어가 영속화
store.record(assessment.as_dict(), run_id="run-1")                                   # → SQLite + git-SHA JSON
```

Community 는 6차원을 사용한다. Glimi Workspace 는 같은 `glimi.edd` 코어를 산출물/위임/A2A 차원에 확장한다. 하나의 EDD 프레임워크, 두 앱이다. 전체 설계는 [`docs/qa_system.md`](docs/qa_system.md)에 있다.
---

## Examples

Community 없이 Glimi Core 를 바로 실행하는 스타터다. `echo` 백엔드는 별도 의존성이나 API 키 없이 작동한다. 실제 모델을 연결하면 협업이 시작된다.

| Example | 보여주는 것 |
|---|---|
| [`examples/research_buddies`](glimi-core/examples/research_buddies/) | 두 에이전트가 주제 협업, 번갈아 읽고 요약하며 공유 노트 누적 |
| [`examples/dev_pair`](glimi-core/examples/dev_pair/) | Planner + executor 패턴 — 하나는 task 분해, 하나는 실행, 메모리 공유 |
| [`examples/dashboard_demo`](glimi-core/examples/dashboard_demo/) | 인메모리 저장소에 작은 인구를 시드해 읽기 전용 Core 대시보드로 서빙 (`glimi[dashboard]`) |

---

## 기술 스택

| 컴포넌트 | 기술 |
|---|---|
| **Glimi Core 런타임** | Python 3.12+. Claude(Claude CLI subprocess + Anthropic SDK), 완전 로컬 Ollama 백엔드, Grok CLI 백엔드; `LLMBackend` seam 은 pluggable (vLLM / llama.cpp 는 예정 — 아직 미출시) |
| **메모리 저장소 (기본)** | SQLite — `KernelStore` ABC 로 pluggable (커널은 DB 를 직접 안 봄) |
| **도구 프로토콜** | `<tools>` 인라인 XML — 별칭 해석, JSON 타입 인자, 지연 실행 |
| **웹 대시보드** | FastAPI + Jinja2 + Cytoscape.js + htmx |
| **Community 어댑터** | `discord.py` + per-agent Webhook 아바타 |
| **Community 이미지 생성** (opt-in) | Animagine XL 4.0 기반 로컬 LoRA 초상화 (~6분/장, 가중치 186MB) |

---

## 로드맵

**완료 — 커널 추출 + 패키징**
- ✅ `community/core/{runtime, tools, memory, llm, conversation}` → `glimi/` 이동. 스토리지·플랫폼 의존 제거, 단독 import 가능.
- ✅ `KernelStore` ABC, `AgentProfile`/`OwnerContext`/`KernelObserver` protocol 구현. Community 는 `community/adapters/` 에서 어댑터 연결.
- ✅ `pyproject` 분리. `pip install glimi`(코어), `glimi[community]`(앱) 빌드 완료.

**현재 — 첫 PyPI 배포**
- `pip install glimi` 알파(0.1.0) PyPI 업로드.

**다음 — Examples + docs**
- `examples/research_buddies/`, `examples/dev_pair/`
- 영문 아키텍처 블로그
- 커널 unit test 보강

**그다음 — 로컬 모델 백엔드**
- vLLM·llama.cpp 백엔드 예정. (Ollama·Grok 지원 완료, `AVAILABLE_MODELS` 스텁 존재)
- 대시보드에서 에이전트별 로컬 모델 지정.

**그다음 — 에이전트별 RAG 메모리** ⭐
- L0–L5 메모리는 컨텍스트 내 동작. 오래된 에이전트는 기억이 윈도우를 넘긴다. 각 에이전트에 RAG 코퍼스 배치, 검증된 retrieval 코어로 기록 검색. 히스토리 전체 대신 **관련 항목만 사용**.
- **효과**: 큰 히스토리에서도 안정적 회상(`O(top-k)`), 출처 정확, 드리프트 최소.
- **지연 표현**: 검색은 인메모리보다 느리다. 에이전트는 온로드 중 RAG 호출하며 *"잠시만…"*, *"기억 더듬는 중…"*으로 랙을 표현.

**Community 전용**
- 오너 부재 시뮬레이션 및 복귀 브리핑
- 감정 레이어(sentiment→상태 변화)
- 새 씬: birthday, healing, outing
- 비-Discord 어댑터: Telegram, 웹챗

---

## 기여

> 🆕 **처음 기여?** **[`START_HERE.html`](docs/START_HERE.html)** 을 읽어주세요. 플랫폼 셋업, 첫 task(로컬 모델), Claude Code 워크플로우, 브랜치 전략, 로드맵이 있습니다. **PR 전에 필독.**

### 첫 contributor task — 로컬 모델 지원 (Gemma 4 / Qwen 3.5)

첫 작업은 Ollama 로컬 LLM 백엔드 구현과 Gemma 4·Qwen 3.5 벤치마크입니다. 모델은 chat, judge, 메모리 추출 JSON 역할을 합니다. Glimi는 Anthropic API에 의존하므로 벤더 중립성 검증이 필요합니다. 자세한 내용은 [`START_HERE.html` §5](docs/START_HERE.html#first-task)를 참고하세요.

| | |
|---|---|
| **범위** | `community/llm/ollama.py` 신규 (`LLMBackend` ABC 구현), `AVAILABLE_MODELS` 활성화, 비교 doc |
| **파일** | 신규: `community/llm/ollama.py`, `tests/llm/test_ollama.py`, `docs/llm_backends.md` · 수정: `community/llm/__init__.py`, `community/core/runtime.py` |
| **완료 기준** | 대시보드 모델 선택기에 두 모델 노출; 페르소나/supervisor/메모리 모두 동작; `docs/llm_backends.md` 비교표 |
| **레퍼런스 구현** | `community/llm/claude_cli.py` (subprocess), `community/llm/anthropic_sdk.py` (SDK) |

### 다른 진입점

- **easy**: `examples/` 데모, 문서 수정, Community `community/scenes/`
- **medium**: vLLM / llama.cpp 백엔드, 대시보드 시각화, 신규 ToolSpec
- **hard**: Windows(`run.ps1`), Telegram(`community/adapters/telegram/`), `pyproject` 분리(`pip install glimi`), 임베딩 기반 retrieval

### 브랜치 전략

| 브랜치 | 역할 |
|---|---|
| `main` | 안정판. **직접 작업 / 직접 push 금지.** 메인테이너가 develop 에서 fast-forward. |
| `develop` | working 브랜치. 모든 통합이 여기서. |
| `feat/<name>` · `fix/<name>` · `docs/<name>` · `refactor/<name>` | 한시적 contributor 브랜치. **PR base = `develop`**. |

### 코드 규칙 (회귀 잘 나는 항목)

- **Discord = 어댑터.** `community/core/*` 에서 `discord` import 금지. Community 의존은 `community/bot/`, `community/scenes/`, `community/achievements/` 등.
- **메모리·감정은 user prompt 주입.** system prompt는 고정 불가. `AgentRuntime`이 턴마다 구성.
- **타임스탬프는 UTC-aware ISO.** `community.core.timeutil.now_utc_iso()` 사용. SQLite `CURRENT_TIMESTAMP` 금지.
- **"에이전트"·"봇"·"AI" 금지.** `<tools>` 블록은 대화 채널에 노출되지 않음. 도구 호출 로그: `logs/system.log`.
- **프로필 편집 후** `invalidate_cache()`, `runtime.refresh_agent()` 호출.

### 커밋 규칙

- 제목 1줄(50자 내외), 본문 2줄 이하.
- 접두사: `feat:` / `fix:` / `docs:` / `ui:` / `refactor:` / `test:`
- **AI co-author trailer 금지.**(`Co-Authored-By: Claude` 등)
- **`--no-verify` / `--no-gpg-sign` 금지.** 훅 오류는 수정할 것.

전체 가이드는 `CLAUDE.md`(Claude Code 자동 로드)에 있습니다.

---

## 라이선스

**AGPL-3.0-or-later**는 강한 카피레프트 라이선스다. 누구나 사용할 수 있지만 **배포나 네트워크 서비스 시 파생물 소스 공개와 저자 표기**가 필요하다. 독점 제품화는 불가하다. 기여는 같은 라이선스로 받고, 저작권은 저자가 보유하며 별도 상업 라이선스를 낼 수 있다. MongoDB, Grafana, Mastodon이 같은 방식을 쓴다.

자세한 내용은 `LICENSE`를 참고한다.
