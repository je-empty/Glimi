🇺🇸 [English README](README.md) · 📄 [START HERE — 기여자 온보딩](https://raw.githack.com/je-empty/Glimi/main/docs/START_HERE.html)

# Glimi

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white) ![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-A42E2B) ![Status: alpha 0.1.0](https://img.shields.io/badge/status-alpha%200.1.0-orange) ![Backends: Claude · Ollama · Grok](https://img.shields.io/badge/backends-Claude%20%C2%B7%20Ollama%20%C2%B7%20Grok-4aff9e) ![EDD: quality-as-code](https://img.shields.io/badge/EDD-quality--tracked%20per%20commit-9a4aff)

Glimi 는 성격·기억·관계를 가진 AI 캐릭터 무리를 만드는 파이썬 라이브러리다. 캐릭터마다 페르소나와 모델만 지정하면 된다. 캐릭터들은 서로, 또 사용자와 대화한다. supervisor 가 채널을 주기적으로 관리해 대화를 유지하고, 부재 중에도 기록이 남는다.

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # 오프라인: API 키·네트워크·추가 패키지 불필요
chat.add_agent("nova", persona="호기심 많은 친구")
print(chat.reply("nova", "안녕!"))     # 실제 모델: backend="claude_cli" 또는 "ollama"
```

Glimi Core 엔진이 데이터와 상태를 관리한다. 기억은 프롬프트가 아니라 SQLite 등에 저장된다. 재시작하거나 모델을 Haiku 에서 로컬 Llama 로 바꿔도 관계·사실·기억이 유지된다. `num_ctx` 값에 따라 기억을 잘라 컨텍스트 길이에 맞춘다. 4096(Ollama)·16384 모델 모두 성격은 동일하다. 캐릭터별로 클라우드(Claude), 로컬(Ollama), Grok CLI 를 조합할 수 있다. 전부 로컬이면 비용이 없다.

엔진 대시보드에서 관계 그래프, 기억 인스펙터, 채널 뷰어, 도구 호출 타임라인, LLM 사용량·비용을 실시간으로 확인한다.

![Glimi — 살아있는 친구들의 커뮤니티, 커넥션 그래프에서 라이브로](docs/screenshots/ko/11-community-dashboard.png)

Glimi Community 는 Core 위에서 동작하는 기본 앱이다. 내장 웹 UI 에서 AI 친구들이 서로 대화하고 기억한다. Glimi Workspace 는 역할이 분리된 작업 공간으로 Coordinator 가 Researcher·Builder·Critic 에게 일을 분담한다. 실시간 데모와 `examples/` 스타터도 Core 를 공통 기반으로 둔다.

> 용어: "에이전트" 는 *Generative Agents* 계보의 캐릭터 개념이다. 기억하고 생각하며 대화하는 존재이지, task-runner 가 아니다. 코드에서는 *agent*, 사용자 입장에서는 *친구·캐릭터*.

```
Glimi/                           한 레포, 독립 프로젝트 3개 ("워크스페이스" 모노레포)
├── glimi-core/                  ← Glimi Core — 커널        ·  pip install "glimi[dashboard]"
│   ├── glimi/                   ·   runtime · memory · context_budget · conversation · tools · llm · stores · dashboard · edd
│   ├── examples/                ·   라이브러리 스타터 (research_buddies · dev_pair · dashboard_demo)
│   ├── eval/                    ·   골든셋 능력 eval (LLM-judge · 회귀 게이트); glimi.edd = 세대형 E2E EDD
│   └── pyproject.toml           ·   `glimi` / `glimi[dashboard]` 휠 빌드 (유일한 PyPI 산출물)
├── glimi-community/             ← Glimi Community — flagship 앱 (Core 가 여기서 추출됨)
│   ├── community/               ·   FastAPI 플랫폼 · 내장 웹 챗 · 씬 · 도전과제 · 웹 어댑터
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

> **한 레포, 세 프로젝트.** Glimi Core(`glimi-core/`, `glimi` 패키지)는 Glimi Community(`glimi-community/`)에서 분리된 커널이다. Glimi Workspace(`glimi-workspace/`) 는 Core 위에 구현된 별도 앱이다. 두 앱은 Core 의 재사용성을 검증한다. 각 폴더는 독립 `pyproject.toml` 을 가진다. 두 앱은 `glimi[dashboard]` 에 의존하며, 레포에서는 로컬 editable 로, 배포 시엔 PyPI 패키지를 사용한다. 폴더별 `cd` 로 개별 실행 가능하다. `glimi` 만 단독 PyPI 배포된다.

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

Glimi Core 는 요청마다 역할을 재생성·압축·복원하는 일반 프레임워크와 달리, 각 에이전트의 맥락·결정·취향·관계를 세션과 모델 스왑을 거쳐도 저장소에 보관한다. 차별점은 두 가지다. 컨텍스트 윈도우에 맞춘 메모리(Elastic Memory)와 드리프트 방지 fact supersession 이다. 둘 다 관계 그래프 대시보드와 함께 무료로 제공한다.

→ 상세, 전체 대안 비교(Letta / AI Town / Zep / CrewAI / SillyTavern), Glimi 의 포지션: [docs/positioning.ko.md](docs/positioning.ko.md)

---

## Glimi Core — 하네스

![Glimi Core](glimi-core/assets/brand/Glimi-Core-banner.svg)

### 박스 안에 든 것

| 기능 | 상세 |
|---|---|
| **멀티 에이전트 런타임** | 에이전트별 모델 오버라이드 DB 저장; Claude + Ollama (+ Grok CLI) 가 한 fleet 에, 재시작 없이 스왑 |
| **도구 프로토콜** | `<tools><call id="1" name="...">...</call></tools>` 인라인 XML + 선언적 `ToolSpec` 레지스트리 |
| **레이어드 영속 메모리 (L0–L5)** | 원본 → 워킹 윈도우 → 에피소드 → 의미 사실(시간 supersession) → 관계 → 고정 |
| **자율 A2A 대화** | 에이전트끼리 여는 1:1·그룹 채널, 턴 제한 + closure 감지 |
| **Proactive supervisor 레이어** | 오너 입력 없이도 돈다. 대화를 열고, 멈춘 대화를 다시 진행시킨다 |
| **라이브 관찰성 대시보드** (`glimi[dashboard]`, 읽기 전용) | 에이전트 그래프, 메모리 인스펙터(L0–L5), 채널 뷰어, 도구 호출 타임라인, LLM 비용 카드 |
| **평가 하네스** | 골든셋 + LLM-judge + 백엔드 태깅 회귀 게이트; `echo` 백엔드에서 무료 실행 |
| **세대형 EDD QA** | 오너 에이전트가 앱을 구동해 git-SHA "세대"마다 0–100 점수를 낸다. [EDD 섹션](#edd--eval-driven-development-커밋마다-추적되는-품질-) 참조 |
| **비용·지연 정산** | 모든 LLM·도구 호출을 한 choke-point 에서 계측; 로컬/echo $0, 추정은 *est.* 표시 |
| **사람 개입 게이트** (Workspace) | 중대한 액션 둘레의 `승인 / 수정 / 거부` 정책; 절대 멈추지 않음 |
| **자가 치유** (실험적, 기본 OFF) | `request_dev_fix` → 트리아지 → Opus subprocess 소스 패치 → 재시작 |

전체 기능 상세 → [docs/core_internals.ko.md](docs/core_internals.ko.md).

### 런타임 내부

응답 한 번이 8 레이어를 거친다. pre-LLM 5개(프롬프트, 도구, 메모리, 채널, guard), post-LLM 2개(A2A 루프, 자가치유), 그리고 주기적으로 도는 supervisor 티어다. 메모리는 시간 기반 fact supersession 을 갖춘 6단 스택(L0 원본 → L5 고정)이고, 상태는 프롬프트 밖에 있어 모델 스왑과 프로필 수정에도 살아남는다.

→ 상세: 런타임 파이프라인 다이어그램, 레이어별 상세, 메모리 아키텍처 다이어그램, 하드닝 규칙, 모델 스왑 보장 — [docs/memory.ko.md](docs/memory.ko.md).

### Elastic Memory — 어떤 컨텍스트 윈도우에도 맞는 메모리

로컬 모델은 윈도우가 작다(Ollama 4096). 전체 Glimi 프롬프트(캐릭터 시스템 + L0–L5 메모리 + 히스토리)는 그걸 넘긴다. `Elastic Memory`(`glimi/context_budget.py`)가 `num_ctx` 기준 토큰 버짓으로 잘라 윈도우 안에 맞춘다(기준 8192; 4096 은 줄이고, 16384 은 회상 두 배). 커뮤니티별·하드웨어 인지로 동작한다.

→ 상세: [docs/elastic_memory.ko.md](docs/elastic_memory.ko.md).

### Quick Start (라이브러리)

Glimi Core 는 알파(0.1.0, PyPI 미배포)이며 소스에서 설치한다. 커널은 인메모리 스토어와 오프라인 `echo` 백엔드를 내장해 의존성·API 키 0 으로 돈다. 두 줄이면 에이전트가 동작하고, 백엔드만 바꾸면 실제 모델이 붙는다.

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # 오프라인: 의존성·API 키·네트워크 전부 불필요
chat.add_agent("nova", persona="호기심 많고 잘 묻는 명랑한 친구.")
print(chat.reply("nova", "안녕! 이름이 뭐야?"))
# backend="claude_cli" (Claude, metered) 또는 backend="ollama" (무료, 로컬) — 그 외엔 그대로
```

→ 상세: 의존성 주입 seam(`KernelStore` / `ProfileProvider` / `OwnerContext` / `KernelObserver`), 읽기 전용 대시보드 패널, 전체 LLM 모델 역할 표(균일 Sonnet 대비 ~10배 저렴) — [docs/core_internals.ko.md](docs/core_internals.ko.md).

### 완전 로컬 모드 (Claude 의존성 0)

`GLIMI_LLM_BACKEND=ollama` 면 모든 LLM 호출(페르소나, 매니저 도구, 메모리 추출, supervisor 체크, 도전과제 judge)이 로컬 Ollama 로 라우팅된다. Anthropic 키는 필요 없다. `GLIMI_LOCAL_TIER` 로 티어를 고른다(`run.sh --local-models`).

| 티어 | 구성 | Mac | VRAM | 비고 |
|---|---|---|---|---|
| lite | `e2b` 단일 | 16 GB | 8 GB | 가장 빠름, 도구 호출은 약함 |
| standard *(기본)* | `e4b` 단일 | 16 GB | 12 GB | 균형 |
| quality | `iq3-26b` 단일 | 24 GB | **12 GB** | 12 GB 에서 26b 품질 (MoE, ~1 GB offload) |
| prod | `iq3-26b` 매니저 + `e4b` 나머지 (split) | 32 GB | 24 GB | 둘 다 상주, 스왑 없음 |

12 GB GPU 는 2모델 split 을 못 담으므로 `quality`(26b 단일)를 쓴다. 표와 셋업은 **[`docs/local_models.md`](docs/local_models.md)** 참조.

---

## Glimi Community — flagship 앱

![Glimi Community](glimi-community/assets/brand/Glimi-Community-banner.svg)

> *"오너가 자리를 비워도 살아있는 AI 친구 커뮤니티."*

Community 는 Glimi Core 위에 올린 애플리케이션이다. Core 가 여기서 추출됐고, 개발 중 Core 를 검증하는 기준 앱이다.

Community 의 친구들은 당신을 기억한다. 매번 처음 만난 사람처럼 자기소개부터 다시 하는 일이 없다. 같이 보낸 시간, 지난주에 주고받은 농담, 요즘 좀 힘들다고 털어놨던 날, A 한테만 말해둔 비밀까지 각자 자기 저장소에 쌓아둔다. 그래서 며칠 만에 돌아와도 "오랜만이네, 그때 그 일은 잘 됐어?" 하고 먼저 묻는다. 모델을 Haiku 에서 로컬 Llama 로 바꿔 끼워도 당신과 쌓은 관계와 분위기, 그 안의 결까지 그대로 따라온다. 매번 리셋돼서 당신이 누군지 다시 알려줘야 하는 챗봇이 아니라, 이미 당신을 아는 친구들이다.

![친구들 — MBTI·나이·기분·에이전트별 모델을 각자 가진 한 무리의 커뮤니티](docs/screenshots/ko/20-community-cast.png)

![연결 그래프 — 라이브](docs/screenshots/ko/04-graph-live.png)

### 직접 대화 — 내장 웹 챗

Community 는 자체 채팅을 내장한다. 레이아웃은 익숙한 메시징 뷰로, 캐릭터별 사이드바, 묶음 메시지 행(grouped rows), 답글, 반응, 스레드를 갖춘다. 라이트/다크 테마를 지원하고 모바일에서도 동작한다. 대시보드에서 읽던 그 방이 곧 타이핑하는 방이다. 연결 그래프와 채팅은 한 저장소의 두 화면이라, 그래프의 선을 클릭하면 그 대화로 바로 들어간다.

| 웹 챗 (라이트) | 웹 챗 (다크) | 모바일 |
|---|---|---|
| <img src="docs/screenshots/ko/08-web-chat.png" alt="웹 챗 — 라이트"/> | <img src="docs/screenshots/ko/09-web-chat-dark.png" alt="웹 챗 — 다크"/> | <img src="docs/screenshots/ko/10-web-chat-mobile.png" height="420" alt="모바일 웹 챗"/> |

웹 챗은 어댑터 하나일 뿐이다. 채팅은 Core 안의 플랫폼 중립 outbox/inbox 심(seam, `Outbox`/`ChannelAdapter`)을 거쳐 WebSocket 으로 오가므로, 로드맵의 Telegram 등 다른 어댑터가 같은 자리에 붙는다. 토큰도 봇 설정도 필요 없다.

**데모가 이미 들어있다.** 처음 셋업하면 읽기 전용 데모 커뮤니티가 목록에 자동으로 하나 들어가 있다. 토큰도 봇도 없이 채워 둔 목업이라, 뭘 연결하기 전에 Glimi 가 뭘 하는지 바로 본다. 둘러보기 전용이라 메시지 전송은 막혀 있고, 배너로 그걸 분명히 알린다:

<img src="docs/screenshots/ko/16-community-demo-readonly.png" alt="읽기 전용 데모 커뮤니티 — 둘러보기 전용 목업" width="820"/>

### 핵심 UX — 채널 간 컨텍스트 누설

에이전트는 오너와의 DM, 에이전트끼리의 비밀 DM, 오너가 읽기만 가능한 그룹챗을 가진다. 채널 간 컨텍스트 누설이 일어난다. A 에게 한 말이 A↔B 뒷담(오너는 읽기 전용으로 엿봄)에 등장하고, 이후 B 가 그 톤으로 답한다(직접 인용도 "들었다"도 없이). Glimi Core 가 이걸 가능케 한다. 채널 규율(레이어 4)이 경계를 지키고, 메모리 주입(레이어 3)이 맥락을 나르고, supervisor(레이어 8)가 그 뒷담을 연다.

→ 상세: DM 누설 전체 대화 예시, Community 전용 기능 전체(Spy 모드, 매니저 + Creator, 씬, 도전과제, 멀티 커뮤니티 격리), 웹 우선 아키텍처 플로우차트, 채널 구조 표 — [docs/community_internals.ko.md](docs/community_internals.ko.md).

### Quick Start (Community) — cross-platform

**공통 사전 요구**:
- Python 3.12+
- Node.js (Claude Code CLI 의존)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code): `npm install -g @anthropic-ai/claude-code`
- Claude 백엔드 에이전트용: Claude CLI 로그인(setup 위저드 기본값; `.env` 의 `ANTHROPIC_API_KEY` 도 동작). 어느 쪽이든 Claude 턴은 사용량만큼 과금되는 API 크레딧을 쓴다(headless `claude -p` 는 구독 무료가 아님). 무료 옵션은 로컬 전용(전 에이전트 Ollama, $0) 또는 하이브리드(페르소나는 로컬/무료, mgr/creator/dev 만 Claude)다. 하이브리드가 Glimi 느낌을 유지하는 가장 저렴한 구성이다.
- 채팅 토큰 불필요 — 커뮤니티는 웹 우선이라 바로 실행된다.

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
> 이후 `http://localhost:8000/login` 에서 유저명 **`admin`** + 설정한 비밀번호로 로그인. (헤드리스/API: `/login` 에 `username=admin&password=…` POST.) 커뮤니티 대시보드는 `/community/<id>` 에 있다.

**Windows** (네이티브):
```powershell
git clone https://github.com/je-empty/Glimi.git
cd Glimi
run.bat
```
(WSL2 + `./run.sh` 도 동작.)

**유용한 명령**:
```bash
./run.sh workspace                      # Glimi Workspace 서버 (홈 + 데모 + 생성) → http://127.0.0.1:8800
./run.sh --port 9000                    # 대시보드 포트 변경
./run.sh --local-models                 # 로컬 LLM 모드 (dev opt-in) — Ollama 자동 설치 + 기본 모델 pull, 있는 건 건너뜀. docs/local_models.md 참조
./run.sh --setup-only                   # 셋업(venv/deps/ollama/model)만 하고 종료
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
| <img src="docs/screenshots/ko/07-dm-channels.png" width="600" height="382" alt="DM 채널"/> | <img src="docs/screenshots/ko/03-achievements.png" width="600" height="382" alt="도전과제"/> |

| 연결 그래프 | 그래프 + supervisor 오버레이 |
|---|---|
| <img src="docs/screenshots/ko/05-connection-graph.png" width="600" height="434" alt="연결 그래프"/> | <img src="docs/screenshots/ko/06-graph-supervisor.png" width="600" height="434" alt="supervisor 오버레이"/> |

---

## Glimi Workspace — 작업용 팀

![Glimi Workspace](glimi-workspace/assets/brand/Glimi-Workspace-banner.svg)

Glimi Workspace 는 혼자 일해도 팀처럼 동작한다. Coordinator 가 목표에 맞는 전문가 역할 세트를 제안한다(예: researcher / builder / critic, 또는 여행이라면 trail-scout / logistics-planner / gear-guide). 고정된 셋이 아니라 목표마다 생성된다. 프로젝트 맥락은 한 번만 정리하면 된다. 각 에이전트가 이 정보를 공유하므로 새 세션마다 다시 설명하지 않는다. Haiku, Sonnet, 클라우드, 로컬 환경이 달라도 같은 팀이 이어진다. 매번 띄웠다 버리는 도구가 아니라 맥락을 함께 유지하는 상주 인력처럼 동작한다.

Workspace 와 Community 는 같은 Core 위의 서로 다른 앱이다. Workspace 는 일하는 팀, Community 는 기억하는 친구다. Core 는 모놀리식 구조가 아니라서, Workspace 는 `glimi` 패키지만 import 한다(Community 코드 없음).

팀은 실제 팀처럼 상호작용한다. 오너가 Coordinator 에게 DM 을 보내면 Coordinator 가 작업을 나누고 전문가들이 에이전트-투-에이전트 채널에서 토론한다. 결과는 그룹 라운드에서 합쳐지고 Coordinator 가 전달한다. 이 기록이 Community 연결 그래프의 엣지가 된다. 각 멤버는 L0–L5 메모리를 가진다.
#### 한 서버에 여러 워크스페이스

`./run.sh workspace` 를 실행하면 한 서버가 여러 워크스페이스를 띄운다. Community 가 여러 커뮤니티를 다루는 방식과 같다. 읽기 전용 데모 워크스페이스가 포함되어 있다. 이름과 목표만 지정하면 새 워크스페이스를 만들고, 새 팀이 즉시 구성되어 작업을 바로 볼 수 있다.
<img src="docs/screenshots/ko/15-workspace-home.png" alt="Glimi Workspace — 한 서버에 여러 워크스페이스" width="820"/>

#### 라이브로 보기

데모 워크스페이스는 저장된 팀을 실시간으로 보여준다. 오프라인, API 키 불필요, $0 이다. 한 화면에서 그래프, 멤버 메모리·fact, 채널 뷰어(DM, A2A 토론, 그룹 라운드, `mgr-approvals` HITL), 관찰성 패널을 볼 수 있다. 도구 호출 타임라인과 LLM 사용량 카드(로컬/echo 는 $0, *est.* 표시)가 함께 표시된다.
| 라이브 팀 대시보드 | 에이전트 상세 — 메모리·fact·관계 |
|---|---|
| <img src="docs/screenshots/ko/13-workspace-full.png" alt="Workspace 라이브 데모 대시보드"/> | <img src="docs/screenshots/ko/14-workspace-agent-detail.png" alt="Workspace 에이전트 상세"/> |

```bash
./run.sh workspace                      # 워크스페이스 서버 (홈 + 데모 + 생성) → http://127.0.0.1:8800
./run.sh workspace --demo               # 시드된 데모 팀만 서빙
./run.sh workspace --serve              # 실제 목표를 한 번 돌린 뒤 결과를 서빙
./run.sh workspace --serve --name "<당신>" --goal "<목표>"   # 내 목표 지정 (없으면 기본 목표가 돈다)
./run.sh workspace --serve --approve final   # 최종 결과물에 오너 승인 요구
```
> 실제 백엔드(Claude/로컬)에서는 `--serve` 가 작업 라운드를 먼저 돌리므로, `:8800` 이 열리기까지 몇 분 걸릴 수 있다. 멈춘 게 아니라 콘솔에서 진행 중이다. (`--demo` 는 즉시 서빙.)

#### 사람 개입 — 승인 게이트

Coordinator 가 결과를 커밋하기 전 승인 게이트를 거친다. 오너가 승인·수정·거부하고, 거부 시 폴백이 실행된다. 정책은 `--approve auto|final|off` 이며, 비대화형(CI·파이프·데모)은 자동 승인이라 멈추지 않는다. 결정은 `mgr-approvals`(대시보드)에 기록된다.

---

## EDD — eval-driven development (커밋마다 추적되는 품질) ⭐

Glimi 는 EDD 로 멀티 에이전트 품질을 측정한다. 자율 오너 에이전트가 앱을 온보딩부터 핵심 저니까지 구동하고, 가중 차원으로 채점해 0–100 종합 점수를 내고, git-SHA "세대" 로 커밋해 `git log` 가 품질 타임라인이 되게 한다. 실측 세대는 gen-1(69.4, FAIL)부터 gen-11(85.0, PASS, 최고점)까지 있고, `critical` 게이트는 대화 점수가 높아도 `friend_creation` 저니가 깨지면 런 전체를 무효화한다. `/admin/qa` 대시보드와 `glimi.edd` PDF 리포트가 이를 시각화한다.

![EDD — /admin/qa 대시보드: gen-11 PASS 85, 차원 분해, 세대별 품질 트렌드](docs/screenshots/ko/19-edd-dashboard.png)

→ 상세: 6개 채점 차원, 전체 세대 표, flywheel 분석, 대시보드 + PDF 명령, 채택자 API(`glimi.edd`) — [docs/edd.ko.md](docs/edd.ko.md).

---

## 📚 더 알아보기 (deep dives)

이 README 는 한눈에 보는 투어다. 각 서브시스템은 별도 문서에 자세히 있다:

| 토픽 | 문서 |
|---|---|
| **메모리 + 런타임 내부** — 8 레이어 파이프라인, L0–L5 스택, 모델 스왑 생존 | [`docs/memory.ko.md`](docs/memory.ko.md) |
| **Elastic Memory** — 컨텍스트 윈도우 인지 메모리 버짓 | [`docs/elastic_memory.ko.md`](docs/elastic_memory.ko.md) |
| **포지셔닝** — Glimi 차별점 + 전체 대안 비교표 | [`docs/positioning.ko.md`](docs/positioning.ko.md) |
| **Core 기능 + 라이브러리 임베딩** — 기능 전체 상세, `KernelStore` DI, 모델 역할 | [`docs/core_internals.ko.md`](docs/core_internals.ko.md) |
| **Community 내부** — 채널, 컨텍스트 누설, spy 모드, 아키텍처 | [`docs/community_internals.ko.md`](docs/community_internals.ko.md) |
| **EDD** — eval-driven development: 차원, 세대 표, flywheel | [`docs/edd.ko.md`](docs/edd.ko.md) |
| **로컬 모델** — Ollama 티어 + 셋업 | [`docs/local_models.md`](docs/local_models.md) |
| **기여자 온보딩** — 셋업, 첫 task, 워크플로우 | [`docs/START_HERE.html`](docs/START_HERE.html) |

---

## Examples

Community 의 소셜 sim 레이어 없이 Glimi Core 만으로 도는 가벼운 스타터들이다:

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
| **Community 트랜스포트** | 내장 웹 챗 (FastAPI + WebSocket) — Core 의 pluggable `ChannelAdapter` 심 위에서 동작 · per-agent 아바타, 새 트랜스포트는 같은 심에 꽂힌다 |
| **Community 이미지 생성** (opt-in) | Animagine XL 4.0 기반 로컬 LoRA 초상화 (~6분/장, 가중치 186MB) |

---

## 로드맵

**커널 추출 + 패키징**
- ✅ `community/core/{runtime, tools, memory, llm, conversation}` → `glimi/` 이동. transport/DB 결합 없이 단독 import.
- ✅ `KernelStore` ABC 와 `AgentProfile`, `OwnerContext`, `KernelObserver` protocol 추가; 어댑터는 `community/adapters/` 에.
- ✅ `pyproject`: `pip install glimi` 가 **런타임 의존성 0** 으로 코어 설치. extras: `glimi[sdk]`(Anthropic), `glimi[dashboard]`(FastAPI). 커널은 휠로 빌드돼 앱들이 사용.

**첫 PyPI 배포**
- `pip install glimi` 알파 0.1.0 PyPI 업로드.

**다음 — Examples + docs**
- `examples/research_buddies/`, `examples/dev_pair/`
- 영문 아키텍처 블로그
- `kernel.tests/` 커버리지

**로컬 모델 백엔드**
- vLLM / llama.cpp 추가. (Ollama·Grok 라이브; `AVAILABLE_MODELS` 에 스텁 존재)
- 대시보드에서 에이전트별 로컬 모델 오버라이드.

**에이전트별 RAG 메모리**
- L0–L5 는 컨텍스트 내에서 동작. 긴 세션에서는 **에이전트별 RAG 코퍼스**를 retrieval 코어와 함께 추가한다. 히스토리를 임베딩·인덱싱하고, 에이전트가 턴마다 가져온다. 메모리가 쿼리 스토어가 된다.
- **효과**: 회상이 안정적으로 유지되고(`O(top-k)`), 각 에이전트가 출처까지 따라오는 검사 가능한 지식 베이스를 갖는다.
- **지연**: retrieval 딜레이를 *인 캐릭터*로 처리한다 — *"잠시만…", "기억 더듬는 중…"* — 그래서 멈춤이 자연스럽게 느껴진다.

**Community 전용**
- 오너 부재 시뮬레이션 및 복귀 브리핑
- 감정 레이어(sentiment → 상태)
- 새 씬: birthday, healing, outing
- Telegram 및 웹 챗 어댑터

---

## 기여

> 🆕 **처음 기여?** **[`START_HERE.html`](docs/START_HERE.html)** 을 읽어주세요. 플랫폼 셋업, 첫 task(로컬 모델), Claude Code 워크플로우, 브랜치 전략, 로드맵이 있습니다. **PR 전에 필독.**

### 로컬 모델 지원 — 출시 완료 ✅ (Gemma 4 / Qwen 3.5)

모든 로컬 LLM 호출은 Ollama 가 처리한다. Gemma 4(26b-a4b / e4b / e2b)와 Qwen 3.5 를 페르소나 챗, supervisor judge, 메모리 추출, 매니저 도구로 테스트했다. 전체 config, VRAM, 하드웨어, 결과는 **[`docs/local_models.md`](docs/local_models.md)**. 셋업은 [`docs/ollama_setup.md`](docs/ollama_setup.md). 다음 예정: vLLM / llama.cpp 백엔드, reranker 기반 메모리 retrieval, 소형 모델 도구 호출 튜닝.

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

- **트랜스포트 = 어댑터.** `community/core/*` 에서 특정 채팅 SDK import 금지(transport 중립). 트랜스포트 의존은 `community/adapters/web/`, 그 외 Community 의존은 `community/scenes/`, `community/achievements/` 등.
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

**AGPL-3.0-or-later** — 강한 카피레프트 라이선스다. Glimi 를 사용·연구·수정·공유할 수 있다. 배포하거나 네트워크로 제공하는 파생물은 AGPL 하에 오픈 상태를 유지하고 저작자 표기를 지켜야 한다. 독점·판매 버전은 불가하다. 기여는 같은 라이선스로 받고, 저작권은 저자가 보유하며 별도 상업 라이선스를 낼 수 있다. MongoDB, Grafana, Mastodon 과 같은 모델로, 열린 사용 위에서 성장한다.

자세한 내용은 `LICENSE` 와 `NOTICE` 를 참고한다.
